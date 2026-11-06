"""SQLite 工程持久化：工程、点、观测、方案版本、快照与结果缓存。

设计要点（对应 ``docs/redesign_plan.md`` §4）：

- 方案（scenario）带版本号与父方案，观测按方案保存，支持“基准 → 增补”
  的分支关系；
- 快照（snapshot）把方案物化为规范化 JSON，计算 SHA-256 ``input_hash``；
  同一输入哈希只插入一次，快照不可变；
- 结果（results）按 ``input_hash`` 缓存，返回时从数据库中的 JSON 反序列化，
  因此“首次计算”和“重新打开数据库后读取”逐位一致；
- 只使用标准库 ``sqlite3``，不引入 ORM 或迁移框架。

模块级函数（``save_project`` 等）接收数据库路径；:class:`ProjectStore`
提供相同能力的面向对象接口。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext

import hashlib
import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import __version__
from .adjustment import solve
from .design import build_parameter_index
from .model import (
    Angle,
    Direction,
    Distance,
    GnssBaseline2D,
    Network,
    Point,
)
from .precision import analyze_precision
from .reliability import analyze_reliability

SCHEMA_VERSION = "2.0"
ENGINE_VERSION = __version__

_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    schema_version  TEXT NOT NULL DEFAULT '2.0',
    crs             TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS points (
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    e               REAL NOT NULL,
    n               REAL NOT NULL,
    fixed           INTEGER NOT NULL DEFAULT 0,
    sigma_e         REAL,
    sigma_n         REAL,
    elevation_m     REAL,
    lon             REAL,
    lat             REAL,
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (project_id, name)
);

CREATE TABLE IF NOT EXISTS scenarios (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    parent_id       TEXT REFERENCES scenarios(id),
    description     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS ix_scenarios_project
    ON scenarios(project_id, created_at);

CREATE TABLE IF NOT EXISTS observations (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scenario_id     TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    ordinal         INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    payload_json    TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS ix_observations_scenario
    ON observations(scenario_id, ordinal);

CREATE TABLE IF NOT EXISTS snapshots (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scenario_id     TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    input_hash      TEXT NOT NULL UNIQUE,
    schema_version  TEXT NOT NULL,
    engine_version  TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_snapshots_scenario
    ON snapshots(scenario_id, created_at);

CREATE TABLE IF NOT EXISTS results (
    input_hash      TEXT PRIMARY KEY,
    project_id      TEXT,
    scenario_id     TEXT,
    engine_version  TEXT NOT NULL,
    options_json    TEXT NOT NULL DEFAULT '{}',
    result_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_results_scenario
    ON results(scenario_id, created_at);
"""


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_load(value: Optional[str], default: Any = None) -> Any:
    if value in (None, ""):
        return default if default is not None else {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default if default is not None else {}


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _normalize_value(value: Any) -> Any:
    """把对象规范化为可哈希的 JSON 值。

    字典按键排序，浮点按 15 位有效数字格式化（消除平台/序列化差异），
    拒绝 NaN/Inf，保证同一输入得到同一哈希。
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("快照中不能包含 NaN/Inf")
        if number == 0.0:
            return 0
        if number.is_integer():
            return int(number)
        formatted = float(f"{number:.15g}")
        if formatted.is_integer():
            return int(formatted)
        return formatted
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _normalize_value(value[key]) for key in sorted(value, key=str)}
    raise TypeError(f"无法规范化的类型：{type(value)!r}")


def canonical_json(value: Any) -> str:
    """规范化 JSON 字符串（键排序、紧凑分隔符、浮点格式化）。"""
    return json.dumps(
        _normalize_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def compute_input_hash(snapshot: Mapping[str, Any]) -> str:
    """计算快照的 SHA-256 输入哈希。"""
    payload = dict(snapshot)
    # snapshot_id 由哈希派生，不应参与哈希本身。
    payload.pop("snapshot_id", None)
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _observation_kind(row: Mapping[str, Any]) -> str:
    kind = str(row.get("kind") or row.get("type") or "").strip().lower()
    aliases = {
        "baseline": "gnss",
        "gnss_baseline": "gnss",
        "level": "leveling",
        "coordinate_constraint": "constraint",
    }
    return aliases.get(kind, kind)


def _observation_model_data(row: Mapping[str, Any]) -> Dict[str, Any]:
    """把存储行转换为快照/模型可用的规范观测字典。"""
    kind = _observation_kind(row)
    data: Dict[str, Any] = {"type": kind}
    if row.get("id") is not None:
        data["id"] = str(row["id"])

    def pick(*names: str, default: Any = None) -> Any:
        for name in names:
            if name in row and row[name] is not None:
                return row[name]
        return default

    if kind == "distance":
        data.update(
            {
                "from": str(pick("from", "frm")),
                "to": str(pick("to")),
                "a_m": float(pick("a", "a_m", "sigma_a_m", default=0.002)),
                "b_ppm": float(pick("b_ppm", "sigma_b_ppm", default=2.0)),
                "sigma_model": str(pick("sigma_model", default="quadrature")),
            }
        )
        value = pick("value_m", "value")
        if value is not None:
            data["value_m"] = float(value)
    elif kind == "angle":
        data.update(
            {
                "rear": str(pick("backsight", "rear")),
                "station": str(pick("station")),
                "front": str(pick("foresight", "front")),
                "sigma_arcsec": float(pick("sigma_arcsec", "sigma", default=1.0)),
            }
        )
        value = pick("value_rad", "value_deg", "value")
        if value is not None:
            data["value_rad" if "value_rad" in row else "value_deg"] = float(value)
    elif kind == "direction":
        data.update(
            {
                "station": str(pick("station")),
                "target": str(pick("target")),
                "sigma_arcsec": float(pick("sigma_arcsec", "sigma", default=1.0)),
            }
        )
        value = pick("value_rad", "value_deg", "value")
        if value is not None:
            data["value_rad" if "value_rad" in row else "value_deg"] = float(value)
    elif kind == "gnss":
        data.update(
            {
                "from": str(pick("from", "frm")),
                "to": str(pick("to")),
                "sigma_E": float(pick("sigma_E", "sigma_e")),
                "sigma_N": float(pick("sigma_N", "sigma_n")),
                "correlation": float(pick("correlation", "rho", default=0.0)),
            }
        )
    elif kind == "constraint":
        data.update(
            {
                "point": str(pick("point")),
                "component": str(pick("component", default="E")).upper(),
                "sigma": float(pick("sigma")),
                "value": pick("value"),
            }
        )
    else:
        raise ValueError(f"未知观测类型：{kind!r}")
    data["enabled"] = bool(row.get("enabled", True))
    return data


def observation_to_model(data: Mapping[str, Any]) -> Any:
    """把规范观测字典转换为 :mod:`ctrlnet.model` 对象。"""
    kind = _observation_kind(data)
    if kind == "distance":
        return Distance(
            data.get("from", data.get("frm")),
            data["to"],
            a=float(data.get("a_m", data.get("a", 0.002))),
            b_ppm=float(data.get("b_ppm", 2.0)),
            sigma_model=str(data.get("sigma_model", "quadrature")),
        )
    if kind == "angle":
        return Angle(
            data.get("rear", data.get("backsight")),
            data["station"],
            data.get("front", data.get("foresight")),
            sigma_arcsec=float(data.get("sigma_arcsec", 1.0)),
        )
    if kind == "direction":
        return Direction(
            data["station"],
            data["target"],
            sigma_arcsec=float(data.get("sigma_arcsec", 1.0)),
        )
    if kind == "gnss":
        return GnssBaseline2D(
            data.get("from", data.get("frm")),
            data["to"],
            sigma_E=float(data["sigma_E"]),
            sigma_N=float(data["sigma_N"]),
            correlation=float(data.get("correlation", 0.0)),
        )
    raise ValueError(f"观测类型 {kind!r} 不能直接构建设计矩阵（仅支持 distance/angle/direction/gnss）")


def _point_row(point: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(point["name"]),
        "E": float(point["E"] if "E" in point else point.get("e", 0.0)),
        "N": float(point["N"] if "N" in point else point.get("n", 0.0)),
        "fixed": bool(point.get("fixed", False)),
        "sigma_E": None if point.get("sigma_E") is None else float(point["sigma_E"]),
        "sigma_N": None if point.get("sigma_N") is None else float(point["sigma_N"]),
        "elevation_m": None
        if point.get("elevation_m") is None
        else float(point["elevation_m"]),
        "lon": None if point.get("lon") is None else float(point["lon"]),
        "lat": None if point.get("lat") is None else float(point["lat"]),
        "metadata": dict(point.get("metadata") or {}),
    }


def _point_payload(point: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(point["name"]),
        "E": float(point["E"]),
        "N": float(point["N"]),
        "fixed": bool(point.get("fixed", False)),
        "sigma_E": None if point.get("sigma_E") is None else float(point["sigma_E"]),
        "sigma_N": None if point.get("sigma_N") is None else float(point["sigma_N"]),
        "elevation_m": None
        if point.get("elevation_m") is None
        else float(point["elevation_m"]),
        "lon": None if point.get("lon") is None else float(point["lon"]),
        "lat": None if point.get("lat") is None else float(point["lat"]),
        "metadata": dict(point.get("metadata") or {}),
    }


def _build_network(
    points: Sequence[Mapping[str, Any]], observations: Sequence[Mapping[str, Any]]
) -> Tuple[Network, List[Mapping[str, Any]]]:
    models: List[Point] = []
    for row in points:
        models.append(
            Point(
                str(row["name"]),
                float(row["E"]),
                float(row["N"]),
                fixed=bool(row.get("fixed", False)),
                sigma_E=row.get("sigma_E"),
                sigma_N=row.get("sigma_N"),
            )
        )
    obs_models = []
    enabled: List[Mapping[str, Any]] = []
    for row in observations:
        if not bool(row.get("enabled", True)):
            continue
        obs_models.append(observation_to_model(row))
        enabled.append(row)
    return Network(models, obs_models, name="snapshot"), enabled


# ---------------------------------------------------------------------------
# 数据库句柄
# ---------------------------------------------------------------------------
def _resolve_db_path(path: Path | str) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


DATABASE_VERSION = 1
BUSY_TIMEOUT_MS = 30000


class VersionConflictError(RuntimeError):
    """调用者的方案版本已过期；重新读取、合并后重试。"""


def _row_hash(*values: Any) -> str:
    return hashlib.sha256(_json_dump(values).encode("utf-8")).hexdigest()


@contextmanager
def _write_transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _migrate(conn: sqlite3.Connection) -> None:
    # user_version 是数据库迁移版本；SCHEMA_VERSION 仍为快照格式 2.0。
    with _write_transaction(conn):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > DATABASE_VERSION:
            raise ValueError(f"不支持的数据库版本：{version}")
        if version == DATABASE_VERSION:
            return
        for statement in _SCHEMA_SQL.split(";"):
            if statement.strip():
                conn.execute(statement)
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(scenarios)")}
        if "version" not in columns:
            conn.execute("ALTER TABLE scenarios ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
        conn.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            operation TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_id TEXT NOT NULL,
            before_hash TEXT,
            after_hash TEXT
        )""")
        # 行级触发器覆盖级联删除、批量替换和缓存写入，回滚时审计一起回滚。
        for table in ("projects", "points", "scenarios", "observations", "snapshots", "results"):
            names = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
            def digest(prefix):
                return "store_row_hash(" + ",".join(f'{prefix}."{n}"' for n in names) + ")"
            def identity(prefix):
                if table == "points":
                    return f"json_array({prefix}.project_id,{prefix}.name)"
                key = "input_hash" if table == "results" else "id"
                return f'{prefix}."{key}"'
            for operation in ("INSERT", "UPDATE", "DELETE"):
                old = digest("OLD") if operation != "INSERT" else "NULL"
                new = digest("NEW") if operation != "DELETE" else "NULL"
                obj = identity("OLD" if operation == "DELETE" else "NEW")
                conn.execute(f"""CREATE TRIGGER IF NOT EXISTS audit_{table}_{operation.lower()}
                    AFTER {operation} ON {table} BEGIN
                    INSERT INTO audit_log(timestamp,operation,object_type,object_id,before_hash,after_hash)
                    VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),'{operation}','{table}',{obj},{old},{new});
                    END""")
        conn.execute(f"PRAGMA user_version = {DATABASE_VERSION}")


def connect(path: Path | str) -> sqlite3.Connection:
    """打开 WAL 工程库，原子迁移旧库；每个线程/进程单独创建连接。"""
    connection = sqlite3.connect(str(_resolve_db_path(path)), timeout=BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.create_function("store_row_hash", -1, _row_hash, deterministic=True)
    try:
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        _migrate(connection)
        return connection
    except BaseException:
        connection.close()
        raise


def _scenario_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "version": int(row["version"]),
        "parent_id": row["parent_id"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": _json_load(row["metadata_json"], {}),
    }


def _observation_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    payload = _json_load(row["payload_json"], {})
    payload["id"] = row["id"]
    payload["kind"] = row["kind"]
    payload["enabled"] = bool(row["enabled"])
    payload["ordinal"] = int(row["ordinal"])
    payload["metadata"] = _json_load(row["metadata_json"], {})
    return payload


def _project_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "schema_version": row["schema_version"],
        "crs": row["crs"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": _json_load(row["metadata_json"], {}),
    }


def _fetch_points(conn: sqlite3.Connection, project_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM points WHERE project_id=? ORDER BY rowid", (project_id,)
    ).fetchall()
    return [
        {
            "name": row["name"],
            "E": float(row["e"]),
            "N": float(row["n"]),
            "fixed": bool(row["fixed"]),
            "sigma_E": None if row["sigma_e"] is None else float(row["sigma_e"]),
            "sigma_N": None if row["sigma_n"] is None else float(row["sigma_n"]),
            "elevation_m": None
            if row["elevation_m"] is None
            else float(row["elevation_m"]),
            "lon": None if row["lon"] is None else float(row["lon"]),
            "lat": None if row["lat"] is None else float(row["lat"]),
            "metadata": _json_load(row["metadata_json"], {}),
        }
        for row in rows
    ]


def _fetch_observations(
    conn: sqlite3.Connection, scenario_id: str
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM observations WHERE scenario_id=? ORDER BY ordinal, rowid",
        (scenario_id,),
    ).fetchall()
    return [_observation_row_to_dict(row) for row in rows]


def _fetch_scenario_dict(
    conn: sqlite3.Connection, scenario_id: str, *, include_observations: bool = True
) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
    if row is None:
        return None
    payload = _scenario_row_to_dict(row)
    if include_observations:
        payload["observations"] = _fetch_observations(conn, scenario_id)
        payload["n_observations"] = sum(
            1 for item in payload["observations"] if item.get("enabled", True)
        )
    else:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM observations WHERE scenario_id=? AND enabled=1",
            (scenario_id,),
        ).fetchone()
        payload["n_observations"] = int(count["n"] if count else 0)
    return payload


def _resolve_project_id(
    conn: sqlite3.Connection, project_id: Optional[str] = None
) -> str:
    if project_id is not None:
        row = conn.execute("SELECT id FROM projects WHERE id=?", (str(project_id),)).fetchone()
        if row is None:
            raise KeyError(f"工程不存在：{project_id!r}")
        return str(row["id"])
    row = conn.execute(
        "SELECT id FROM projects ORDER BY created_at, rowid LIMIT 1"
    ).fetchone()
    if row is None:
        raise KeyError("数据库中没有工程")
    return str(row["id"])


def _resolve_scenario_id(
    conn: sqlite3.Connection,
    scenario_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> str:
    if scenario_id is not None:
        row = conn.execute(
            "SELECT id FROM scenarios WHERE id=?", (str(scenario_id),)
        ).fetchone()
        if row is None:
            raise KeyError(f"方案不存在：{scenario_id!r}")
        return str(row["id"])
    pid = _resolve_project_id(conn, project_id)
    row = conn.execute(
        "SELECT id FROM scenarios WHERE project_id=? ORDER BY created_at, rowid LIMIT 1",
        (pid,),
    ).fetchone()
    if row is None:
        raise KeyError(f"工程 {pid!r} 没有方案")
    return str(row["id"])


# ---------------------------------------------------------------------------
# 保存 / 读取
# ---------------------------------------------------------------------------
def _insert_observation(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    project_id: str,
    scenario_id: str,
    kind: str,
    ordinal: int,
    payload: Mapping[str, Any],
) -> None:
    raw = dict(payload)
    raw.pop("id", None)
    raw.pop("kind", None)
    raw.pop("ordinal", None)
    raw.pop("metadata", None)
    enabled = bool(raw.pop("enabled", True))
    conn.execute(
        "INSERT INTO observations "
        "(id, project_id, scenario_id, kind, ordinal, enabled, payload_json, metadata_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            observation_id,
            project_id,
            scenario_id,
            kind,
            int(ordinal),
            1 if enabled else 0,
            _json_dump(raw),
            _json_dump(payload.get("metadata") or {}),
        ),
    )


def _insert_scenario(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    scenario: Mapping[str, Any],
    fallback_name: str,
    scenario_id: Optional[str] = None,
    default_parent: Optional[str] = None,
    used_observation_ids: set,
) -> str:
    sid = str(scenario.get("id") or scenario_id or f"sc-{uuid.uuid4().hex[:12]}")
    if scenario.get("id") is None and scenario_id is None:
        sid = f"sc-{uuid.uuid4().hex[:12]}"
    now = _utcnow()
    conn.execute(
        "INSERT INTO scenarios "
        "(id, project_id, name, version, parent_id, description, created_at, updated_at, metadata_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            sid,
            project_id,
            str(scenario.get("name") or fallback_name),
            int(scenario.get("version", 1)),
            scenario.get("parent_id", default_parent),
            scenario.get("description"),
            str(scenario.get("created_at") or now),
            str(scenario.get("updated_at") or now),
            _json_dump(scenario.get("metadata") or {}),
        ),
    )
    observations = list(scenario.get("observations") or [])
    for index, item in enumerate(observations):
        kind = _observation_kind(item)
        oid = item.get("id")
        if oid is None or str(oid) in used_observation_ids:
            oid = f"{sid}-o{index + 1:03d}"
        oid = str(oid)
        while oid in used_observation_ids:
            oid = f"{oid}-x"
        used_observation_ids.add(oid)
        _insert_observation(
            conn,
            observation_id=oid,
            project_id=project_id,
            scenario_id=sid,
            kind=kind,
            ordinal=index,
            payload=item,
        )
    return sid


def save_project(
    path: Path | str,
    project: Mapping[str, Any],
    *,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """保存完整工程（点 + 一个或多个方案），返回读回后的工程字典。

    ``project`` 至少包含 ``name`` 与 ``points``；方案放在 ``scenarios`` 列表，
    也接受单个 ``scenario`` / ``observations``（自动建立默认方案）。
    """
    if not isinstance(project, Mapping):
        raise TypeError("project 必须是字典/映射")
    db_path = _resolve_db_path(path)
    project_id = str(project.get("id") or f"prj-{uuid.uuid4().hex[:12]}")
    now = _utcnow()
    points = list(project.get("points") or [])
    scenarios: List[Mapping[str, Any]] = list(project.get("scenarios") or [])
    if not scenarios and project.get("scenario") is not None:
        scenarios = [project["scenario"]]
    if not scenarios:
        scenarios = [
            {
                "id": project.get("default_scenario_id") or "base",
                "name": project.get("default_scenario_name") or "基准方案",
                "version": 1,
                "observations": list(project.get("observations") or []),
            }
        ]

    conn = connect(db_path)
    try:
        with _write_transaction(conn):
            existing = conn.execute(
                "SELECT id FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if existing is not None and not overwrite:
                raise FileExistsError(
                    f"工程 {project_id!r} 已存在；如需覆盖请传 overwrite=True"
                )
            if existing is not None:
                from .lifecycle import describe
                for row in conn.execute('SELECT metadata_json FROM scenarios WHERE project_id=?', (project_id,)):
                    workflow = describe(_json_load(row['metadata_json'], {}))
                    if workflow['state'] != 'draft' or workflow['history']:
                        raise ValueError('Cannot overwrite a project with lifecycle history')
                conn.execute("DELETE FROM results WHERE project_id=?", (project_id,))
                conn.execute("DELETE FROM snapshots WHERE project_id=?", (project_id,))
                conn.execute("DELETE FROM observations WHERE project_id=?", (project_id,))
                conn.execute("DELETE FROM scenarios WHERE project_id=?", (project_id,))
                conn.execute("DELETE FROM points WHERE project_id=?", (project_id,))
                conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            conn.execute(
                "INSERT INTO projects "
                "(id, name, description, schema_version, crs, created_at, updated_at, metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    project_id,
                    str(project.get("name") or "未命名工程"),
                    project.get("description"),
                    str(project.get("schema_version") or SCHEMA_VERSION),
                    project.get("crs"),
                    str(project.get("created_at") or now),
                    str(project.get("updated_at") or now),
                    _json_dump(project.get("metadata") or {}),
                ),
            )
            seen_names = set()
            for raw_point in points:
                point = _point_row(raw_point)
                if point["name"] in seen_names:
                    raise ValueError(f"点名重复：{point['name']!r}")
                seen_names.add(point["name"])
                conn.execute(
                    "INSERT INTO points "
                    "(project_id, name, e, n, fixed, sigma_e, sigma_n, elevation_m, "
                    " lon, lat, metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        project_id,
                        point["name"],
                        point["E"],
                        point["N"],
                        1 if point["fixed"] else 0,
                        point["sigma_E"],
                        point["sigma_N"],
                        point["elevation_m"],
                        point["lon"],
                        point["lat"],
                        _json_dump(point["metadata"]),
                    ),
                )
            used_ids: set = set()
            for index, scenario in enumerate(scenarios, start=1):
                _insert_scenario(
                    conn,
                    project_id=project_id,
                    scenario=scenario,
                    fallback_name=f"方案 {index}",
                    used_observation_ids=used_ids,
                )
        return load_project(db_path, project_id=project_id)
    finally:
        conn.close()


def load_project(
    path: Path | str, project_id: Optional[str] = None
) -> Dict[str, Any]:
    """读取工程及其全部方案、观测。"""
    conn = connect(path)
    try:
        conn.execute("BEGIN")
        pid = _resolve_project_id(conn, project_id)
        row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        assert row is not None
        payload = _project_row_to_dict(row)
        payload["points"] = _fetch_points(conn, pid)
        scenario_rows = conn.execute(
            "SELECT * FROM scenarios WHERE project_id=? ORDER BY created_at, rowid",
            (pid,),
        ).fetchall()
        scenarios = []
        for srow in scenario_rows:
            scenario = _fetch_scenario_dict(conn, str(srow["id"]), include_observations=True)
            assert scenario is not None
            scenarios.append(scenario)
        payload["scenarios"] = scenarios
        payload["n_points"] = len(payload["points"])
        payload["n_scenarios"] = len(scenarios)
        payload["n_snapshots"] = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM snapshots WHERE project_id=?", (pid,)
            ).fetchone()["n"]
        )
        payload["n_results"] = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM results WHERE project_id=?", (pid,)
            ).fetchone()["n"]
        )
        return payload
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 方案
# ---------------------------------------------------------------------------
def list_scenarios(
    path: Path | str,
    project_id: Optional[str] = None,
    *,
    include_observations: bool = True,
) -> List[Dict[str, Any]]:
    """列出方案（默认含观测）。"""
    conn = connect(path)
    try:
        conn.execute("BEGIN")
        pid = _resolve_project_id(conn, project_id)
        rows = conn.execute(
            "SELECT id FROM scenarios WHERE project_id=? ORDER BY created_at, rowid",
            (pid,),
        ).fetchall()
        return [
            _fetch_scenario_dict(
                conn, str(row["id"]), include_observations=include_observations
            )
            for row in rows
        ]
    finally:
        conn.close()


def get_scenario(path: Path | str, scenario_id: str) -> Dict[str, Any]:
    conn = connect(path)
    try:
        conn.execute("BEGIN")
        payload = _fetch_scenario_dict(conn, scenario_id, include_observations=True)
        if payload is None:
            raise KeyError(f"方案不存在：{scenario_id!r}")
        return payload
    finally:
        conn.close()


def _normalize_observation_list(
    observations: Sequence[Mapping[str, Any]],
    scenario_id: str,
    used_ids: set,
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for index, item in enumerate(observations):
        data = dict(item)
        kind = _observation_kind(data)
        data["kind"] = kind
        oid = data.get("id")
        if oid is None or str(oid) in used_ids:
            oid = f"{scenario_id}-o{index + 1:03d}"
        oid = str(oid)
        while oid in used_ids:
            oid = f"{oid}-x"
        used_ids.add(oid)
        data["id"] = oid
        output.append(data)
    return output


def create_scenario(
    path: Path | str,
    name: str,
    *,
    project_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    observations: Optional[Sequence[Mapping[str, Any]]] = None,
    scenario_id: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """创建方案；给出 ``parent_id`` 时复制父方案的观测并令 version+1。"""
    conn = connect(path)
    try:
        with _write_transaction(conn):
            pid = _resolve_project_id(conn, project_id)
            parent = None
            if parent_id is not None:
                parent = _fetch_scenario_dict(conn, str(parent_id), include_observations=True)
                if parent is None:
                    raise KeyError(f"父方案不存在：{parent_id!r}")
                if parent["project_id"] != pid:
                    raise ValueError("父方案不属于同一工程")
            sid = str(scenario_id or f"sc-{uuid.uuid4().hex[:12]}")
            if conn.execute("SELECT 1 FROM scenarios WHERE id=?", (sid,)).fetchone():
                raise FileExistsError(f"方案 {sid!r} 已存在")
            version = int(parent["version"]) + 1 if parent is not None else 1
            now = _utcnow()
            conn.execute(
                "INSERT INTO scenarios "
                "(id, project_id, name, version, parent_id, description, created_at, updated_at, metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    pid,
                    str(name),
                    version,
                    parent_id,
                    description,
                    now,
                    now,
                    _json_dump(metadata or {}),
                ),
            )
            if observations is None:
                source = list(parent["observations"]) if parent is not None else []
                # 父方案的观测在子方案中重新分配 id。
                source = [{k: v for k, v in item.items() if k != "id"} for item in source]
            else:
                source = list(observations)
            used: set = set()
            normalised = _normalize_observation_list(source, sid, used)
            for index, item in enumerate(normalised):
                _insert_observation(
                    conn,
                    observation_id=item["id"],
                    project_id=pid,
                    scenario_id=sid,
                    kind=_observation_kind(item),
                    ordinal=index,
                    payload=item,
                )
        result = _fetch_scenario_dict(conn, sid, include_observations=True)
        assert result is not None
        return result
    finally:
        conn.close()


def update_observations(
    path: Path | str,
    scenario_id: str,
    observations: Sequence[Mapping[str, Any]],
    *,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """整体替换某方案的观测（用于“修改观测后哈希变化”的演示/测试）。"""
    conn = connect(path)
    try:
        with _write_transaction(conn):
            row = conn.execute(
                "SELECT project_id, version FROM scenarios WHERE id=?", (scenario_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"方案不存在：{scenario_id!r}")
            if expected_version is not None and row["version"] != expected_version:
                raise VersionConflictError(f"方案 {scenario_id!r} 版本冲突：期望 {expected_version}，实际 {row['version']}")
            from .lifecycle import require_draft
            require_draft(conn, scenario_id)
            pid = str(row["project_id"])
            conn.execute("DELETE FROM observations WHERE scenario_id=?", (scenario_id,))
            used: set = set()
            normalised = _normalize_observation_list(observations, scenario_id, used)
            for index, item in enumerate(normalised):
                _insert_observation(
                    conn,
                    observation_id=item["id"],
                    project_id=pid,
                    scenario_id=scenario_id,
                    kind=_observation_kind(item),
                    ordinal=index,
                    payload=item,
                )
            conn.execute(
                "UPDATE scenarios SET version=version+1, updated_at=? WHERE id=?", (_utcnow(), scenario_id)
            )
            result = _fetch_scenario_dict(conn, scenario_id, include_observations=True)
            assert result is not None
        return result
    finally:
        conn.close()


def add_observation(
    path: Path | str,
    scenario_id: str,
    observation: Mapping[str, Any],
    *,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """向方案追加一条观测。"""
    while True:
        scenario = get_scenario(path, scenario_id)
        if expected_version is not None and scenario["version"] != expected_version:
            raise VersionConflictError(f"方案 {scenario_id!r} 版本冲突")
        observations = list(scenario["observations"]) + [dict(observation)]
        try:
            return update_observations(path, scenario_id, observations,
                                       expected_version=scenario["version"])
        except VersionConflictError:
            if expected_version is not None:
                raise


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------
def _snapshot_payload(
    project: Mapping[str, Any],
    scenario: Mapping[str, Any],
    options: Mapping[str, Any],
) -> Dict[str, Any]:
    all_points = list(scenario.get("metadata", {}).get("editor_points") or project.get("points") or [])
    selected_names = scenario.get("metadata", {}).get("points") or scenario.get(
        "metadata", {}
    ).get("point_names")
    if selected_names:
        order = [str(name) for name in selected_names]
        by_name = {str(item["name"]): item for item in all_points}
        missing = [name for name in order if name not in by_name]
        if missing:
            raise KeyError(f"方案 {scenario.get('id')!r} 引用了不存在的点：{missing}")
        points = [by_name[name] for name in order]
    else:
        points = all_points
    observations = [
        _observation_model_data(item)
        for item in scenario.get("observations", [])
        if bool(item.get("enabled", True))
    ]
    network, enabled = _build_network(points, observations)
    index = build_parameter_index(network)
    fixed = [p.name for p in network.points if p.fixed]
    datum_kind = str(
        scenario.get("metadata", {}).get("datum")
        or project.get("metadata", {}).get("datum")
        or "fixed"
    )
    parameter_order = list(index.names)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "id": project.get("id"),
            "name": project.get("name"),
            "crs": project.get("crs"),
        },
        "network": {
            "id": scenario.get("id"),
            "name": scenario.get("name"),
            "kind": "planar",
            "dimension": 2,
            "version": int(scenario.get("version", 1)),
            "parent_id": scenario.get("parent_id"),
            "crs": project.get("crs"),
            "datum": {
                "kind": datum_kind,
                "fixed_points": fixed,
                "constraints": [
                    {"point": name, "component": "E"}
                    for name in fixed
                ]
                + [{"point": name, "component": "N"} for name in fixed],
            },
        },
        "parameter_order": parameter_order,
        "points": [
            {
                "id": p.name,
                "label": p.name,
                "e": p.E,
                "n": p.N,
                "role": p.role,
                "sigma_e": p.sigma_E,
                "sigma_n": p.sigma_N,
            }
            for p in network.points
        ],
        "observations": observations,
        "stochastic_model": {"kind": "diagonal", "sigma0": 1.0, "groups": []},
        "engine": {
            "name": "ctrlnet.adjustment",
            "version": ENGINE_VERSION,
            "options": dict(options),
        },
    }
    return payload


def snapshot(
    path: Path | str,
    scenario_id: Optional[str] = None,
    *,
    project_id: Optional[str] = None,
    options: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """创建（或复用）方案快照，返回规范化 payload 与 SHA-256 哈希。"""
    conn = connect(path)
    try:
        with _write_transaction(conn):
            if scenario_id is not None:
                selected = _fetch_scenario_dict(conn, str(scenario_id), include_observations=False)
                if selected is None:
                    raise KeyError(f"方案不存在：{scenario_id!r}")
                if project_id is not None and selected["project_id"] != project_id:
                    raise ValueError("方案不属于所选工程")
                project_id = selected["project_id"]
            pid = _resolve_project_id(conn, project_id)
            sid = _resolve_scenario_id(conn, scenario_id, pid)
            project_row = conn.execute(
                "SELECT * FROM projects WHERE id=?", (pid,)
            ).fetchone()
            assert project_row is not None
            project = _project_row_to_dict(project_row)
            project["points"] = _fetch_points(conn, pid)
            scenario = _fetch_scenario_dict(conn, sid, include_observations=True)
            assert scenario is not None
            opts = {"confidence": 0.95}
            opts.update(dict(options or {}))
            payload = _snapshot_payload(project, scenario, opts)
            digest = compute_input_hash(payload)
            snapshot_id = f"snap-{digest[:16]}"
            payload["snapshot_id"] = snapshot_id
            existing = conn.execute(
                "SELECT * FROM snapshots WHERE input_hash=?", (digest,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO snapshots "
                    "(id, project_id, scenario_id, input_hash, schema_version, "
                    " engine_version, payload_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        snapshot_id,
                        pid,
                        sid,
                        digest,
                        SCHEMA_VERSION,
                        ENGINE_VERSION,
                        _json_dump(payload),
                        _utcnow(),
                    ),
                )
                created_at = _utcnow()
            else:
                created_at = existing["created_at"]
            return {
                "id": snapshot_id,
                "snapshot_id": snapshot_id,
                "scenario_id": sid,
                "project_id": pid,
                "input_hash": digest,
                "hash": digest,
                "schema_version": SCHEMA_VERSION,
                "engine_version": ENGINE_VERSION,
                "created_at": created_at,
                "payload": payload,
            }
    finally:
        conn.close()


def get_snapshot(path: Path | str, snapshot_id: str) -> Dict[str, Any]:
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE id=? OR input_hash=?",
            (str(snapshot_id), str(snapshot_id)),
        ).fetchone()
        if row is None:
            raise KeyError(f"快照不存在：{snapshot_id!r}")
        return {
            "id": row["id"],
            "snapshot_id": row["id"],
            "scenario_id": row["scenario_id"],
            "project_id": row["project_id"],
            "input_hash": row["input_hash"],
            "hash": row["input_hash"],
            "schema_version": row["schema_version"],
            "engine_version": row["engine_version"],
            "created_at": row["created_at"],
            "payload": _json_load(row["payload_json"], {}),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 结果计算与缓存
# ---------------------------------------------------------------------------
def _result_from_snapshot(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """由快照 payload 计算精度/可靠性结果（纯 JSON 可序列化）。"""
    from .precision import CHI2_2_95

    options = dict(payload.get("engine", {}).get("options") or {})
    confidence = options.get("confidence", 0.95)
    if confidence is False:
        confidence = None
    points = [
        {
            "name": item["id"],
            "E": float(item["e"]),
            "N": float(item["n"]),
            "fixed": item.get("role") == "fixed",
            "sigma_E": item.get("sigma_e"),
            "sigma_N": item.get("sigma_n"),
        }
        for item in payload["points"]
    ]
    observations = list(payload["observations"])
    network, enabled = _build_network(points, observations)
    datum_kind = str(options.get("datum") or payload.get("network", {}).get("datum", {}).get("kind") or "fixed")
    result = solve(network, datum=datum_kind)
    precision = analyze_precision(result, confidence=confidence)
    reliability = analyze_reliability(result)

    model_ids: Dict[int, str] = {}
    for obs_model, record in zip(network.observations, enabled):
        model_ids[id(obs_model)] = str(record.get("id", ""))

    point_rows = []
    for name in precision.point_order:
        p = precision.points[name]
        ell = p.ellipse
        point_rows.append(
            {
                "name": name,
                "E": float(result.network.point(name).E),
                "N": float(result.network.point(name).N),
                "fixed": bool(p.fixed),
                "role": p.role,
                "sigma_E_m": float(p.sigma_E),
                "sigma_N_m": float(p.sigma_N),
                "mp_m": float(p.mp),
                "sigma_E_mm": float(p.sigma_E_mm),
                "sigma_N_mm": float(p.sigma_N_mm),
                "mp_mm": float(p.mp_mm),
                "is_weakest": bool(p.is_weakest),
                "ellipse": {
                    "a_m": float(ell.a),
                    "b_m": float(ell.b),
                    "azimuth_deg": float(ell.azimuth_deg),
                    "standard_a_m": float(ell.standard_major),
                    "standard_b_m": float(ell.standard_minor),
                    "confidence": None if confidence is None else float(confidence),
                    "scale": float(ell.scale),
                },
            }
        )

    edge_rows = []
    for key in precision.edge_order:
        e = precision.edges[key]
        edge_rows.append(
            {
                "label": e.label,
                "from": e.frm,
                "to": e.to,
                "length_m": float(e.length),
                "sigma_s_m": float(e.sigma_s),
                "sigma_s_mm": float(e.sigma_s_mm),
                "relative": float(e.relative),
                "ratio_denominator": e.ratio_denominator,
                "ratio_text": e.ratio_text,
                "is_weakest": bool(e.is_weakest),
            }
        )

    obs_rows = []
    for record in reliability.records:
        oid = model_ids.get(id(record.observation), record.label)
        row = next((item for item in enabled if str(item.get("id")) == oid), None)
        if row is None:
            row = next(
                (item for item in enabled if item.get("id") == record.label), {}
            )
        kind = str(row.get("kind") or record.kind)
        mdb_display = float(record.mdb_display)
        if not math.isfinite(mdb_display):
            mdb_display = None
        obs_rows.append(
            {
                "id": oid,
                "kind": kind,
                "label": record.label,
                "sigma": float(record.sigma),
                "sigma_unit": record.mdb_unit,
                "r_i": float(record.r_i),
                "mdb": mdb_display,
                "mdb_unit": record.mdb_unit,
                "external_max_mm": float(record.external_max_mm),
                "external_max_norm_mm": float(record.external_max_norm_mm),
                "external_point": record.external_point,
                "undetectable": bool(record.undetectable),
            }
        )

    mdb_arcsec = [
        row["mdb"] for row in obs_rows if row["mdb_unit"] == "arcsec" and row["mdb"] is not None
    ]
    max_external = max(
        (row["external_max_mm"] for row in obs_rows), default=0.0
    )
    min_r = min((row["r_i"] for row in obs_rows), default=None)
    summary = {
        "scenario_id": payload.get("network", {}).get("id"),
        "scenario_name": payload.get("network", {}).get("name"),
        "scenario_version": payload.get("network", {}).get("version"),
        "n_points": len(point_rows),
        "n_fixed": sum(1 for p in point_rows if p["fixed"]),
        "n_observations": int(result.n_observations),
        "n_params": int(result.n_params),
        "n_rows": int(result.n_rows),
        "rank": int(result.rank),
        "redundancy": int(result.redundancy),
        "condition_number": float(result.condition_number),
        "max_mp_mm": float(precision.max_mp * 1000.0),
        "worst_relative": float(precision.worst_relative),
        "min_r": None if min_r is None else float(min_r),
        "max_mdb_arcsec": max(mdb_arcsec) if mdb_arcsec else None,
        "max_external_mm": float(max_external),
        "weakest_points": list(precision.weakest_points),
        "weakest_edges": list(precision.weakest_edges),
        "confidence": None if confidence is None else float(confidence),
        "chi2_2_95": float(CHI2_2_95),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "input_hash": None,
        "snapshot_id": payload.get("snapshot_id"),
        "scenario_id": payload.get("network", {}).get("id"),
        "scenario_version": payload.get("network", {}).get("version"),
        "engine": {
            "name": "ctrlnet.adjustment",
            "version": ENGINE_VERSION,
        },
        "options": options,
        "datum": {
            "kind": result.datum_kind,
            "summary": result.metadata.get("datum_summary", result.datum_kind),
            "fixed_points": [p.name for p in result.network.points if p.fixed],
        },
        "network": {
            "name": result.network.name,
            "n_points": len(result.network.points),
            "n_fixed": len(result.network.fixed_points),
            "n_observations": int(result.n_observations),
            "n_rows": int(result.n_rows),
            "n_params": int(result.n_params),
            "rank": int(result.rank),
            "redundancy": int(result.redundancy),
            "condition_number": float(result.condition_number),
            "parameter_order": list(result.index.names),
        },
        "points": point_rows,
        "edges": edge_rows,
        "observations": obs_rows,
        "reliability": {
            "lambda0": float(reliability.lambda0_value),
            "alpha": float(reliability.alpha),
            "power": float(reliability.power),
            "trace_r": float(reliability.trace_r),
            "expected_redundancy": int(reliability.expected_redundancy),
            "min_r": None if min_r is None else float(min_r),
            "max_mdb_arcsec": max(mdb_arcsec) if mdb_arcsec else None,
            "max_external_mm": float(max_external),
        },
        "summary": summary,
    }


def get_or_compute_result(
    path: Path | str,
    scenario_id: Optional[str] = None,
    *,
    project_id: Optional[str] = None,
    options: Optional[Mapping[str, Any]] = None,
    compute: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """按 ``input_hash`` 返回缓存结果；未命中时计算并写回数据库。

    首次计算也通过数据库 JSON 反序列化后返回，确保与之后的读取逐位一致。
    """
    snap = snapshot(path, scenario_id, project_id=project_id, options=options)
    digest = snap["input_hash"]
    conn = connect(path)
    try:
        with _write_transaction(conn):
            row = conn.execute(
                "SELECT * FROM results WHERE input_hash=?", (digest,)
            ).fetchone()
            if row is None or force:
                if compute is None:
                    result = _result_from_snapshot(snap["payload"])
                else:
                    result = compute(snap["payload"])
                if not isinstance(result, Mapping):
                    raise TypeError("compute 必须返回字典/映射")
                result = dict(result)
                if result.get("input_hash") is None:
                    result["input_hash"] = digest
                if result.get("snapshot_id") is None:
                    result["snapshot_id"] = snap["id"]
                if result.get("scenario_id") is None:
                    result["scenario_id"] = snap["scenario_id"]
                result.setdefault("schema_version", SCHEMA_VERSION)
                text = _json_dump(result)
                if row is None:
                    conn.execute(
                        "INSERT INTO results "
                        "(input_hash, project_id, scenario_id, engine_version, "
                        " options_json, result_json, created_at) VALUES (?,?,?,?,?,?,?)",
                        (
                            digest,
                            snap["project_id"],
                            snap["scenario_id"],
                            ENGINE_VERSION,
                            _json_dump(options or {}),
                            text,
                            _utcnow(),
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE results SET result_json=?, created_at=? WHERE input_hash=?",
                        (text, _utcnow(), digest),
                    )
            stored = conn.execute(
                "SELECT result_json FROM results WHERE input_hash=?", (digest,)
            ).fetchone()
            assert stored is not None
            return json.loads(stored["result_json"])
    finally:
        conn.close()


def result_cached(
    path: Path | str,
    scenario_id: Optional[str] = None,
    *,
    project_id: Optional[str] = None,
    options: Optional[Mapping[str, Any]] = None,
) -> bool:
    """只检查缓存是否存在，不触发计算。"""
    try:
        snap = snapshot(path, scenario_id, project_id=project_id, options=options)
    except Exception:
        return False
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT 1 FROM results WHERE input_hash=?", (snap["input_hash"],)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 面向对象封装
# ---------------------------------------------------------------------------
class ProjectStore:
    """``sqlite3`` 工程库的轻量封装；方法等价于模块级函数。"""

    def __init__(self, path: Path | str) -> None:
        self.path = _resolve_db_path(path)
        connect(self.path).close()

    def save_project(self, project: Mapping[str, Any], *, overwrite: bool = False) -> Dict[str, Any]:
        return save_project(self.path, project, overwrite=overwrite)

    def load_project(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        return load_project(self.path, project_id=project_id)

    def create_scenario(self, name: str, **kwargs: Any) -> Dict[str, Any]:
        return create_scenario(self.path, name, **kwargs)

    def list_scenarios(
        self, project_id: Optional[str] = None, *, include_observations: bool = True
    ) -> List[Dict[str, Any]]:
        return list_scenarios(
            self.path, project_id=project_id, include_observations=include_observations
        )

    def get_scenario(self, scenario_id: str) -> Dict[str, Any]:
        return get_scenario(self.path, scenario_id)

    def snapshot(
        self,
        scenario_id: Optional[str] = None,
        *,
        project_id: Optional[str] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        return snapshot(
            self.path, scenario_id, project_id=project_id, options=options
        )

    def get_or_compute_result(
        self,
        scenario_id: Optional[str] = None,
        *,
        project_id: Optional[str] = None,
        options: Optional[Mapping[str, Any]] = None,
        compute: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        return get_or_compute_result(
            self.path,
            scenario_id,
            project_id=project_id,
            options=options,
            compute=compute,
            force=force,
        )

    def update_observations(
        self, scenario_id: str, observations: Sequence[Mapping[str, Any]], *, expected_version: Optional[int] = None
    ) -> Dict[str, Any]:
        return update_observations(self.path, scenario_id, observations, expected_version=expected_version)

    def add_observation(
        self, scenario_id: str, observation: Mapping[str, Any], *, expected_version: Optional[int] = None
    ) -> Dict[str, Any]:
        return add_observation(self.path, scenario_id, observation, expected_version=expected_version)


Database = ProjectStore
Store = ProjectStore


__all__ = [
    "DATABASE_VERSION",
    "VersionConflictError",
    "SCHEMA_VERSION",
    "ENGINE_VERSION",
    "canonical_json",
    "compute_input_hash",
    "connect",
    "save_project",
    "save_editor_version",
    "load_project",
    "create_scenario",
    "list_scenarios",
    "get_scenario",
    "update_observations",
    "add_observation",
    "snapshot",
    "get_snapshot",
    "get_or_compute_result",
    "result_cached",
    "observation_to_model",
    "ProjectStore",
    "Database",
    "Store",
]


def save_editor_version(
    path: Path | str,
    project: Mapping[str, Any],
    scenario: Mapping[str, Any],
    *,
    parent_snapshot: Optional[str] = None,
    _connection: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """原子保存编辑器版本、完整拓扑与计算快照；旧版本从不覆盖。"""
    conn = _connection or connect(path)
    try:
        with (_write_transaction(conn) if _connection is None else nullcontext()):
            pid = str(project.get("id") or f"prj-{uuid.uuid4().hex[:12]}")
            sid = f"sc-{uuid.uuid4().hex[:12]}"
            now = _utcnow()
            parent = None
            if parent_snapshot:
                row = conn.execute("SELECT * FROM snapshots WHERE id=?", (parent_snapshot,)).fetchone()
                if row is None or row["project_id"] != pid:
                    raise ValueError("父快照不存在或不属于此工程")
                parent = _fetch_scenario_dict(conn, row["scenario_id"], include_observations=True)
                if "thesis_state" not in parent["metadata"]:
                    raise ValueError("父方案不是可编辑论文方案")
            elif conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
                raise ValueError("已有工程必须从明确快照派生")
            else:
                conn.execute("INSERT INTO projects(id,name,created_at,updated_at,metadata_json) VALUES (?,?,?,?,?)",
                             (pid, project["name"], now, now, _json_dump({"status":"saved", "version":1})))
                for raw in project["points"]:
                    pt = _point_row(raw)
                    conn.execute("INSERT INTO points(project_id,name,e,n,fixed) VALUES (?,?,?,?,?)",
                                 (pid, pt["name"], pt["E"], pt["N"], int(pt["fixed"])))
            scenario = dict(scenario, id=sid, parent_id=parent["id"] if parent else None,
                            version=parent["version"]+1 if parent else 1)
            scenario["metadata"] = dict(scenario["metadata"], editor_points=project["points"],
                                        parent_snapshot=parent_snapshot, status="saved",
                                        lifecycle_state="draft", lifecycle_history=[])
            _insert_scenario(conn, project_id=pid, scenario=scenario,
                             fallback_name="编辑方案", used_observation_ids=set())
            saved = _fetch_scenario_dict(conn, sid, include_observations=True)
            payload = _snapshot_payload(dict(project, id=pid), saved, {"confidence":0.95})
            digest = compute_input_hash(payload)
            snapid = f"snap-{digest[:16]}"
            payload["snapshot_id"] = snapid
            conn.execute("INSERT INTO snapshots(id,project_id,scenario_id,input_hash,schema_version,engine_version,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (snapid,pid,sid,digest,SCHEMA_VERSION,ENGINE_VERSION,_json_dump(payload),now))
            count = conn.execute("SELECT COUNT(*) FROM scenarios WHERE project_id=?", (pid,)).fetchone()[0]
            conn.execute("UPDATE projects SET updated_at=?,metadata_json=? WHERE id=?",
                         (now,_json_dump({"status":"saved", "version":count}),pid))
        return {"project_id":pid,"scenario_id":sid,"snapshot_id":snapid,"input_hash":digest,"version":saved["version"]}
    finally:
        if _connection is None:
            conn.close()
