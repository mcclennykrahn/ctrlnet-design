"""单工程 SQLite 的可移植 zip 工程包（manifest + 数据库 + 小资源）。

对应 ``docs/redesign_plan.md`` §4 与 C4/E1：把 ``store.py`` 的单工程数据库
导出为可回读的 zip。包内布局示例::

    manifest.json                  # 版本、文件哈希、快照哈希、依赖说明
    project.sqlite                 # SQLite 单工程（六表）
    data/sample/dem_sample.tif     # 可选的小资源（保留工程内相对路径）
    data/sample/terrain_project.json

设计约束
--------
- ``manifest.json`` 用 UTF-8 JSON 保存 ``format_version``、``created_at``、
  ``engine_version``、``input_hash``、``files``（路径/字节数/SHA-256）与
  ``dependencies``；
- 导出时用 SQLite backup API 复制一致的数据库快照，不锁源库；
- 默认只打包 **≤1 MiB** 的被引用资源；更大的 DEM/瓦片只在 ``dependencies``
  中记录路径、大小与哈希，导入后仍按原相对路径引用；
- 导入前校验 manifest、格式版本、每个文件的 SHA-256 与字节数、路径安全
  （拒绝绝对路径/``..``/符号链接），再调用 :func:`ctrlnet.store.load_project`
  验证数据库可读；
- 导入先解压到目标目录旁的临时目录，全部校验通过后才落盘，避免半成品。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from . import __version__
from .exceptions import PackageError
from .store import SCHEMA_VERSION, load_project

PACKAGE_FORMAT_VERSION = "1.0"
"""当前工程包格式版本（主版本不兼容时拒绝导入）。"""

MANIFEST_NAME = "manifest.json"
DATABASE_NAME = "project.sqlite"
MAX_RESOURCE_BYTES = 1024 * 1024
"""默认打包资源上限 1 MiB；大 DEM 只记录依赖。"""

MAX_MANIFEST_BYTES = 5 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
"""导入时允许的最大解压总量，防止 zip bomb。"""

_SUPPORTED_MAJOR = 1
_SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
_RESOURCE_SUFFIXES = {
    ".tif",
    ".tiff",
    ".png",
    ".jpg",
    ".jpeg",
    ".json",
    ".geojson",
    ".csv",
    ".txt",
    ".pgw",
    ".tfw",
}
_PATH_KEYS = {
    "path",
    "file",
    "file_path",
    "filename",
    "terrain_project",
    "dem_path",
    "image_path",
    "tile_path",
    "resource_path",
}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path | str, *, chunk_size: int = 1024 * 1024) -> str:
    """流式计算文件 SHA-256（小写十六进制）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_stream(stream: Any, target: Any) -> Tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
        target.write(chunk)
    return digest.hexdigest(), size


def _safe_path(value: Any, *, field_name: str = "path") -> str:
    text = str(value).replace("\\", "/")
    if not text or text.startswith("/"):
        raise PackageError(f"{field_name} 非法：{value!r}（不能为空或绝对路径）")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise PackageError(f"{field_name} 非法：{value!r}（不能包含 . 或 ..）")
    if ":" in path.parts[0]:
        raise PackageError(f"{field_name} 非法：{value!r}（不能含盘符）")
    return path.as_posix()


def _is_url(value: str) -> bool:
    text = value.strip().lower()
    return "://" in text or text.startswith("data:") or text.startswith("http:")


def _looks_like_file(value: str) -> bool:
    if _is_url(value):
        return False
    suffix = PurePosixPath(value.replace("\\", "/")).suffix.lower()
    return suffix in _RESOURCE_SUFFIXES


def _iter_resource_strings(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            if isinstance(item, str):
                if key_text in _PATH_KEYS or _looks_like_file(item):
                    yield item
            elif isinstance(item, (Mapping, list, tuple)):
                yield from _iter_resource_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_resource_strings(item)


def _repo_root(project_path: Path) -> Path:
    for parent in [project_path.parent, *project_path.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
    return project_path.parent


def _relative_reference(value: str) -> Optional[str]:
    """把工程内相对路径规范化；绝对路径/``..`` 返回 None（只能作为外部依赖）。"""
    text = value.strip().replace("\\", "/")
    if not text or _is_url(text):
        return None
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        return None
    if ":" in path.parts[0]:
        return None
    return path.as_posix()


def _resolve_reference(value: str, project_path: Path) -> Optional[Path]:
    text = value.strip()
    raw = Path(text)
    candidates: List[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend(
            [
                project_path.parent / raw,
                _repo_root(project_path) / raw,
                Path.cwd() / raw,
            ]
        )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------
def _file_entry(path: Path, archive_path: str, role: str) -> Dict[str, Any]:
    return {
        "path": archive_path,
        "role": role,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "media_type": _media_type(path),
    }


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".sqlite": "application/vnd.sqlite3",
        ".sqlite3": "application/vnd.sqlite3",
        ".db": "application/vnd.sqlite3",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".json": "application/json",
        ".geojson": "application/geo+json",
        ".csv": "text/csv",
        ".txt": "text/plain",
        ".pgw": "text/plain",
        ".tfw": "text/plain",
    }.get(suffix, "application/octet-stream")


def _snapshot_records(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT scenario_id, input_hash, engine_version, created_at "
        "FROM snapshots ORDER BY scenario_id, created_at DESC, rowid DESC"
    ).fetchall()
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        scenario_id = str(row["scenario_id"])
        if scenario_id in latest:
            continue
        latest[scenario_id] = {
            "scenario_id": scenario_id,
            "input_hash": str(row["input_hash"]),
            "engine_version": str(row["engine_version"]),
            "created_at": row["created_at"],
        }
    return [latest[key] for key in sorted(latest)]


def _backup_database(source: Path, target: Path) -> None:
    try:
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise PackageError(f"无法打开 SQLite 工程 {source}：{exc}") from exc
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    except sqlite3.Error as exc:
        raise PackageError(f"复制 SQLite 工程失败：{exc}") from exc
    finally:
        src.close()


def _collect_dependencies(
    project: Mapping[str, Any],
    project_path: Path,
    *,
    include_resources: bool,
    max_resource_bytes: int,
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, Path]]]:
    """返回 (manifest.dependencies, [(archive_path, source_path)...])。"""
    references: List[str] = []
    seen: set = set()
    for value in _iter_resource_strings(project.get("metadata") or {}):
        text = value.strip()
        if text and text not in seen:
            seen.add(text)
            references.append(text)

    dependencies: List[Dict[str, Any]] = []
    packaged: List[Tuple[str, Path]] = []
    used_paths: set = {DATABASE_NAME, MANIFEST_NAME}
    for reference in references:
        resolved = _resolve_reference(reference, project_path)
        relative = _relative_reference(reference)
        size = None
        digest = None
        reason = None
        is_packaged = False
        if resolved is None:
            reason = "引用文件不存在（导入后需按原路径补齐）"
        else:
            size = resolved.stat().st_size
            digest = sha256_file(resolved)
            if relative is None:
                reason = "绝对路径或越界路径，不写入可移植包"
            elif resolved.suffix.lower() in _SQLITE_SUFFIXES:
                reason = "数据库文件不作为资源重复打包"
            elif not include_resources:
                reason = "调用方关闭了资源打包"
            elif max_resource_bytes >= 0 and size > max_resource_bytes:
                reason = f"文件 {size} B 超过资源打包上限 {max_resource_bytes} B，只引用路径"
            elif relative in used_paths:
                reason = "同一路径已打包"
            else:
                is_packaged = True
                used_paths.add(relative)
                packaged.append((relative, resolved))
        entry = {
            "path": relative if relative is not None else reference,
            "packaged": is_packaged,
            "bytes": size,
            "sha256": digest,
            "required": False,
            "reason": reason,
        }
        dependencies.append(entry)
    return dependencies, packaged


def _manifest(
    project: Mapping[str, Any],
    db_copy: Path,
    snapshots: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
    resource_files: Sequence[Tuple[str, Path]],
) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = [_file_entry(db_copy, DATABASE_NAME, "database")]
    for archive_path, source in resource_files:
        files.append(_file_entry(source, archive_path, "resource"))

    digest = hashlib.sha256()
    digest.update(str(project.get("id", "")).encode("utf-8"))
    for entry in files:
        digest.update(entry["path"].encode("utf-8"))
        digest.update(entry["sha256"].encode("ascii"))
    package_id = f"pkg-{digest.hexdigest()[:16]}"

    default_scenario = str((project.get("metadata") or {}).get("default_scenario") or "")
    input_hash = None
    for record in snapshots:
        if record["scenario_id"] == default_scenario:
            input_hash = record["input_hash"]
            break
    if input_hash is None and snapshots:
        input_hash = str(snapshots[0]["input_hash"])

    return {
        "format_version": PACKAGE_FORMAT_VERSION,
        "package_id": package_id,
        "created_at": _utcnow(),
        "engine_version": __version__,
        "generator": "ctrlnet.package/1.0",
        "schema_version": str(project.get("schema_version") or SCHEMA_VERSION),
        "entrypoint": DATABASE_NAME,
        "project": {
            "id": str(project.get("id", "")),
            "name": str(project.get("name", "")),
            "crs": project.get("crs"),
            "n_points": int(project.get("n_points") or len(project.get("points") or [])),
            "n_scenarios": int(
                project.get("n_scenarios") or len(project.get("scenarios") or [])
            ),
            "default_scenario": default_scenario or None,
        },
        "input_hash": input_hash,
        "snapshot_hashes": [dict(item) for item in snapshots],
        "files": files,
        "dependencies": [dict(item) for item in dependencies],
        "dependencies_note": (
            "大资源（如 DEM）默认不写入包，只记录路径/大小/SHA-256；"
            "导入后保持原相对路径即可继续使用。"
        ),
    }


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------
def export_project_package(
    project_path_or_db: Path | str,
    out_zip: Path | str,
    *,
    include_resources: bool = True,
    max_resource_bytes: int = MAX_RESOURCE_BYTES,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """导出单工程 zip 包。

    参数
    ----
    project_path_or_db:
        现有 SQLite 工程路径（``.sqlite/.sqlite3/.db``）。
    out_zip:
        输出 zip；默认拒绝覆盖已有文件。
    include_resources, max_resource_bytes:
        是否打包工程元数据中引用的小资源，以及单文件上限（默认 1 MiB）。

    返回 ``{"zip_path", "size_bytes", "manifest"}``。
    """
    source = Path(project_path_or_db).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"工程数据库不存在：{source}")
    if source.suffix.lower() not in _SQLITE_SUFFIXES:
        raise PackageError(f"工程包只接受 SQLite 工程，收到 {source.suffix!r}")
    destination = Path(out_zip).expanduser().resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(f"输出包已存在：{destination}（如需覆盖请传 overwrite=True）")
    if destination == source:
        raise PackageError("输出 zip 不能覆盖源工程数据库")
    if destination.exists() and destination.is_dir():
        raise IsADirectoryError(f"输出路径是目录：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        max_bytes = int(max_resource_bytes)
    except (TypeError, ValueError):
        raise ValueError("max_resource_bytes 必须是整数") from None
    if max_bytes < 0:
        raise ValueError("max_resource_bytes 不能为负")

    with tempfile.TemporaryDirectory(prefix="ctrlnet-package-") as tmpdir:
        tmp = Path(tmpdir)
        db_copy = tmp / DATABASE_NAME
        _backup_database(source, db_copy)
        project = load_project(db_copy)
        conn = sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True)
        try:
            snapshots = _snapshot_records(conn)
        finally:
            conn.close()
        dependencies, resources = _collect_dependencies(
            project,
            source,
            include_resources=include_resources,
            max_resource_bytes=max_bytes,
        )
        manifest = _manifest(project, db_copy, snapshots, dependencies, resources)

        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
            ) as archive:
                archive.writestr(
                    MANIFEST_NAME,
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                )
                archive.write(db_copy, DATABASE_NAME)
                for archive_path, resource in resources:
                    archive.write(resource, archive_path)
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    size = destination.stat().st_size
    return {"zip_path": str(destination), "size_bytes": size, "manifest": manifest}


# ---------------------------------------------------------------------------
# 读取 / 校验 / 导入
# ---------------------------------------------------------------------------
def _load_manifest(archive: zipfile.ZipFile) -> Dict[str, Any]:
    try:
        info = archive.getinfo(MANIFEST_NAME)
    except KeyError:
        raise PackageError(f"工程包缺少 {MANIFEST_NAME}") from None
    if info.file_size > MAX_MANIFEST_BYTES:
        raise PackageError("manifest.json 过大")
    try:
        raw = archive.read(info)
    except (KeyError, OSError, RuntimeError) as exc:
        raise PackageError(f"读取 manifest.json 失败：{exc}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"manifest.json 不是合法 UTF-8 JSON：{exc}") from exc
    _validate_manifest(manifest)
    return manifest


def _version_major(value: Any) -> int:
    text = str(value).strip()
    try:
        return int(text.split(".")[0])
    except (ValueError, IndexError):
        raise PackageError(f"format_version 非法：{value!r}") from None


def _validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, Mapping):
        raise PackageError("manifest.json 顶层必须是对象")
    for key in ("format_version", "created_at", "engine_version", "entrypoint", "files"):
        if key not in manifest:
            raise PackageError(f"manifest 缺少字段 {key!r}")
    major = _version_major(manifest["format_version"])
    if major != _SUPPORTED_MAJOR:
        raise PackageError(
            f"不支持的工程包格式版本 {manifest['format_version']!r}；"
            f"当前支持 {_SUPPORTED_MAJOR}.x"
        )
    entrypoint = _safe_path(manifest["entrypoint"], field_name="entrypoint")
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise PackageError("manifest.files 必须是非空数组")
    total = 0
    seen: set = set()
    roles = set()
    for index, entry in enumerate(files):
        if not isinstance(entry, Mapping):
            raise PackageError(f"manifest.files[{index}] 必须是对象")
        for key in ("path", "sha256", "bytes"):
            if key not in entry:
                raise PackageError(f"manifest.files[{index}] 缺少 {key!r}")
        path = _safe_path(entry["path"], field_name=f"files[{index}].path")
        if path in seen:
            raise PackageError(f"manifest 文件路径重复：{path}")
        seen.add(path)
        digest = str(entry["sha256"]).strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise PackageError(f"manifest.files[{index}].sha256 非法")
        size = entry["bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise PackageError(f"manifest.files[{index}].bytes 非法")
        total += size
        roles.add(str(entry.get("role", "")))
    if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise PackageError("工程包解压总量超过安全上限")
    if entrypoint not in seen:
        raise PackageError("manifest.entrypoint 未出现在 files 清单中")
    database_entry = next(
        (item for item in files if _safe_path(item["path"]) == entrypoint), None
    )
    if database_entry is None or str(database_entry.get("role", "")) != "database":
        raise PackageError("entrypoint 必须是 role=database 的文件")
    project = manifest.get("project", {})
    if project is not None and not isinstance(project, Mapping):
        raise PackageError("manifest.project 必须是对象")
    snapshots = manifest.get("snapshot_hashes", [])
    if snapshots is not None:
        if not isinstance(snapshots, list):
            raise PackageError("manifest.snapshot_hashes 必须是数组")
        for index, item in enumerate(snapshots):
            if not isinstance(item, Mapping) or "input_hash" not in item:
                raise PackageError(
                    f"manifest.snapshot_hashes[{index}] 必须是含 input_hash 的对象"
                )
    dependencies = manifest.get("dependencies", [])
    if dependencies is not None:
        if not isinstance(dependencies, list):
            raise PackageError("manifest.dependencies 必须是数组")
        for index, item in enumerate(dependencies):
            if not isinstance(item, Mapping):
                raise PackageError(f"manifest.dependencies[{index}] 必须是对象")


def read_manifest(zip_path: Path | str) -> Dict[str, Any]:
    """读取并校验 zip 包 manifest（不校验文件内容哈希）。"""
    path = Path(zip_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"工程包不存在：{path}")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            return _load_manifest(archive)
    except zipfile.BadZipFile as exc:
        raise PackageError(f"不是合法 zip 工程包：{path}") from exc


def inspect_project_package(zip_path: Path | str) -> Dict[str, Any]:
    """返回包 manifest 与包文件大小，供 CLI/网页展示。"""
    path = Path(zip_path).expanduser().resolve()
    manifest = read_manifest(path)
    return {"zip_path": str(path), "size_bytes": path.stat().st_size, "manifest": manifest}


def _verify_archive_entry(
    archive: zipfile.ZipFile,
    entry: Mapping[str, Any],
    target: Path,
) -> str:
    path = _safe_path(entry["path"])
    try:
        info = archive.getinfo(path)
    except KeyError:
        raise PackageError(f"工程包缺少文件：{path}") from None
    if info.is_dir():
        raise PackageError(f"manifest 文件是目录：{path}")
    mode = (info.external_attr >> 16) & 0o170000
    if mode == 0o120000:
        raise PackageError(f"工程包不允许符号链接：{path}")
    expected_size = int(entry["bytes"])
    expected_hash = str(entry["sha256"]).lower()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with archive.open(info, "r") as source, open(target, "wb") as sink:
            digest, size = _sha256_stream(source, sink)
    except (KeyError, OSError, RuntimeError) as exc:
        raise PackageError(f"解压 {path} 失败：{exc}") from exc
    if size != expected_size:
        raise PackageError(
            f"文件 {path} 字节数不一致：manifest {expected_size}，实际 {size}"
        )
    if digest != expected_hash:
        raise PackageError(f"文件 {path} SHA-256 不一致，拒绝导入")
    return path


def import_project_package(
    zip_path: Path | str,
    dest_dir: Path | str,
    *,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """校验并导入工程包到 ``dest_dir``，返回可 ``load_project`` 的结果。

    目标目录已有非空内容时默认拒绝；``overwrite=True`` 只覆盖 manifest 中列出
    的文件，不删除目标目录中的其他文件。全部哈希与数据库校验通过后才落盘。
    """
    source = Path(zip_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"工程包不存在：{source}")
    destination = Path(dest_dir).expanduser().resolve()
    if destination.exists() and not destination.is_dir():
        raise NotADirectoryError(f"导入目标不是目录：{destination}")
    if destination.exists() and any(destination.iterdir()) and not overwrite:
        raise FileExistsError(
            f"目标目录非空：{destination}（如需覆盖包内文件请传 overwrite=True）"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    staging = Path(
        tempfile.mkdtemp(prefix=".ctrlnet-import-", dir=str(destination.parent))
    )
    try:
        try:
            archive = zipfile.ZipFile(source, "r")
        except zipfile.BadZipFile as exc:
            raise PackageError(f"不是合法 zip 工程包：{source}") from exc
        with archive:
            manifest = _load_manifest(archive)
            entries = {str(item["path"]): dict(item) for item in manifest["files"]}
            names = archive.namelist()
            for name in entries:
                if names.count(name) > 1:
                    raise PackageError(f"工程包内文件重复：{name}")
            for name, entry in entries.items():
                _verify_archive_entry(archive, entry, staging / _safe_path(name))

        db_path = staging / _safe_path(str(manifest["entrypoint"]))
        if not db_path.is_file():
            raise PackageError("entrypoint 数据库未解压成功")
        try:
            project = load_project(db_path)
        except Exception as exc:
            raise PackageError(f"工程包内数据库无法读取：{exc}") from exc
        expected_project = manifest.get("project") or {}
        expected_id = str(expected_project.get("id", "") or "")
        if expected_id and str(project.get("id", "")) != expected_id:
            raise PackageError(
                f"工程 id 与 manifest 不一致：{project.get('id')!r} != {expected_id!r}"
            )

        # 快照哈希必须出现在包内数据库中（文件哈希之外的第二层一致性检查）。
        expected_snapshots = manifest.get("snapshot_hashes") or []
        if expected_snapshots:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                present = {
                    str(row[0])
                    for row in conn.execute("SELECT input_hash FROM snapshots")
                }
            finally:
                conn.close()
            missing = [
                item.get("input_hash")
                for item in expected_snapshots
                if str(item.get("input_hash")) not in present
            ]
            if missing:
                raise PackageError(f"工程包缺少 manifest 声明的快照：{missing[:3]}")

        if destination.exists():
            for name, entry in entries.items():
                relative = _safe_path(name)
                source_file = staging / relative
                target_file = destination / relative
                target_file.parent.mkdir(parents=True, exist_ok=True)
                if target_file.is_symlink():
                    raise PackageError(f"导入目标路径是符号链接：{target_file}")
                if target_file.exists() and target_file.is_dir():
                    raise PackageError(f"导入目标路径是目录：{target_file}")
                shutil.copy2(source_file, target_file)
        else:
            os.replace(staging, destination)
            staging = None
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    project_path = destination / _safe_path(str(manifest["entrypoint"]))
    if not project_path.is_file():
        raise PackageError("导入完成后找不到工程数据库")
    loaded = load_project(project_path)
    resources = [
        str(item.get("path"))
        for item in manifest.get("dependencies", [])
        if item.get("packaged")
    ]
    return {
        "project_path": str(project_path),
        "dest_dir": str(destination),
        "project": loaded,
        "manifest": manifest,
        "resources": resources,
        "size_bytes": source.stat().st_size,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli_export(args: Any) -> int:
    result = export_project_package(
        args.project,
        args.out,
        include_resources=not args.no_resources,
        max_resource_bytes=args.max_resource_bytes,
        overwrite=args.overwrite,
    )
    manifest = result["manifest"]
    summary = {
        "zip_path": result["zip_path"],
        "size_bytes": result["size_bytes"],
        "format_version": manifest["format_version"],
        "project": manifest["project"],
        "input_hash": manifest["input_hash"],
        "files": [item["path"] for item in manifest["files"]],
        "packaged_resources": [
            item["path"] for item in manifest["dependencies"] if item["packaged"]
        ],
        "external_dependencies": [
            item["path"] for item in manifest["dependencies"] if not item["packaged"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cli_import(args: Any) -> int:
    result = import_project_package(args.package, args.dest, overwrite=args.overwrite)
    summary = {
        "project_path": result["project_path"],
        "project_id": result["project"]["id"],
        "name": result["project"]["name"],
        "n_points": result["project"]["n_points"],
        "n_scenarios": result["project"]["n_scenarios"],
        "resources": result["resources"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cli_inspect(args: Any) -> int:
    print(json.dumps(inspect_project_package(args.package), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        prog="ctrlnet-package",
        description="导出/校验/导入 CTRLNET 单工程 zip 包（离线）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="导出 SQLite 工程为 zip 包")
    export.add_argument("project", help="SQLite 工程路径")
    export.add_argument("out", help="输出 zip 路径")
    export.add_argument("--no-resources", action="store_true", help="只打包数据库")
    export.add_argument(
        "--max-resource-bytes", type=int, default=MAX_RESOURCE_BYTES, help="单个资源上限"
    )
    export.add_argument("--overwrite", action="store_true", help="覆盖已有 zip")
    export.set_defaults(func=_cli_export)

    import_cmd = sub.add_parser("import", help="校验并导入 zip 包")
    import_cmd.add_argument("package", help="zip 工程包路径")
    import_cmd.add_argument("dest", help="目标目录")
    import_cmd.add_argument("--overwrite", action="store_true", help="覆盖目标目录中的同名包内文件")
    import_cmd.set_defaults(func=_cli_import)

    inspect = sub.add_parser("inspect", help="读取并校验 manifest")
    inspect.add_argument("package", help="zip 工程包路径")
    inspect.set_defaults(func=_cli_inspect)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (PackageError, FileNotFoundError, FileExistsError, NotADirectoryError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


__all__ = [
    "PACKAGE_FORMAT_VERSION",
    "MANIFEST_NAME",
    "DATABASE_NAME",
    "MAX_RESOURCE_BYTES",
    "export_project_package",
    "import_project_package",
    "read_manifest",
    "inspect_project_package",
    "sha256_file",
    "main",
    "build_parser",
]


if __name__ == "__main__":
    raise SystemExit(main())
