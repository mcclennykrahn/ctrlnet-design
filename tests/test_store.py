"""SQLite 工程存储、方案版本、快照哈希与结果缓存测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctrlnet.store import (
    add_observation,
    canonical_json,
    compute_input_hash,
    create_scenario,
    get_or_compute_result,
    list_scenarios,
    load_project,
    save_project,
    snapshot,
    update_observations,
)


def _project(name: str = "测试工程") -> dict:
    return {
        "id": "test-project",
        "name": name,
        "crs": "EPSG:32650",
        "metadata": {"datum": "fixed", "default_scenario": "base"},
        "points": [
            {"name": "A", "E": 0.0, "N": 0.0, "fixed": True},
            {"name": "B", "E": 100.0, "N": 0.0, "fixed": True},
            {"name": "C", "E": 0.0, "N": 100.0, "fixed": False},
            {"name": "D", "E": 100.0, "N": 100.0, "fixed": False},
        ],
        "scenarios": [
            {
                "id": "base",
                "name": "基准方案",
                "version": 1,
                "observations": [
                    {"id": "d1", "kind": "distance", "from": "A", "to": "C", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d2", "kind": "distance", "from": "B", "to": "C", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d3", "kind": "distance", "from": "A", "to": "D", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d4", "kind": "distance", "from": "B", "to": "D", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d5", "kind": "distance", "from": "C", "to": "D", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "a1", "kind": "angle", "backsight": "C", "station": "A", "foresight": "B", "sigma_arcsec": 1.0},
                    {"id": "a2", "kind": "angle", "backsight": "A", "station": "B", "foresight": "D", "sigma_arcsec": 1.0},
                ],
            }
        ],
    }


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "project.sqlite"
    save_project(path, _project())
    return path


def test_save_and_load_roundtrip(db_path: Path):
    loaded = load_project(db_path)
    assert loaded["id"] == "test-project"
    assert loaded["name"] == "测试工程"
    assert loaded["crs"] == "EPSG:32650"
    assert [p["name"] for p in loaded["points"]] == ["A", "B", "C", "D"]
    assert loaded["n_scenarios"] == 1
    scenario = loaded["scenarios"][0]
    assert scenario["id"] == "base"
    assert scenario["version"] == 1
    assert scenario["n_observations"] == 7
    assert len(scenario["observations"]) == 7
    assert {row["kind"] for row in scenario["observations"]} == {"distance", "angle"}

    # 再次保存同名工程默认拒绝，overwrite=True 可覆盖。
    with pytest.raises(FileExistsError):
        save_project(db_path, _project())
    replaced = save_project(db_path, _project("覆盖工程"), overwrite=True)
    assert replaced["name"] == "覆盖工程"


def test_metadata_and_observations_survive_reopen(tmp_path: Path):
    path = tmp_path / "nested" / "p.sqlite"
    project = _project()
    project["scenarios"][0]["metadata"] = {"tags": ["demo"], "confidence": 0.95}
    save_project(path, project)
    loaded = load_project(path)
    assert loaded["scenarios"][0]["metadata"]["tags"] == ["demo"]
    assert loaded["scenarios"][0]["observations"][0]["a_m"] == pytest.approx(0.002)


def test_canonical_json_is_stable_and_rejects_nan():
    first = canonical_json({"b": 1.0, "a": [2, 3.0000000000000004]})
    second = canonical_json({"a": [2, 3], "b": 1})
    assert first == second
    with pytest.raises(ValueError):
        canonical_json({"bad": float("nan")})


def test_snapshot_is_deterministic_and_hash_matches_payload(db_path: Path):
    first = snapshot(db_path, "base")
    second = snapshot(db_path, "base")
    assert first["input_hash"] == second["input_hash"]
    assert first["id"] == f"snap-{first['input_hash'][:16]}"
    assert first["payload"]["snapshot_id"] == first["id"]
    assert first["payload"]["parameter_order"] == ["E_C", "N_C", "E_D", "N_D"]
    assert compute_input_hash(first["payload"]) == first["input_hash"]
    assert first["input_hash"] == compute_input_hash(second["payload"])


def test_result_cache_roundtrip_and_reopen(db_path: Path):
    first = get_or_compute_result(db_path, "base")
    third = get_or_compute_result(db_path, "base")
    assert first == third
    assert first["summary"]["n_observations"] == 7
    assert first["summary"]["n_points"] == 4
    assert first["summary"]["max_mp_mm"] == pytest.approx(1.7160837620, rel=1e-9)
    assert first["input_hash"] == snapshot(db_path, "base")["input_hash"]
    assert first["points"][2]["name"] == "C"
    assert first["points"][2]["mp_mm"] == pytest.approx(1.7160837620, rel=1e-9)
    assert first["edges"]
    assert first["reliability"]["min_r"] == pytest.approx(0.06916450099, rel=1e-8)

    # 重新打开数据库（新的连接/新对象）结果仍逐位一致。
    reopened = load_project(db_path)
    assert reopened["n_results"] == 1
    assert get_or_compute_result(db_path, "base") == first


def test_custom_compute_is_cached(db_path: Path):
    calls = {"n": 0}

    def compute(payload):
        calls["n"] += 1
        return {"input_hash": payload["snapshot_id"], "value": 42}

    first = get_or_compute_result(db_path, "base", compute=compute)
    second = get_or_compute_result(db_path, "base", compute=compute)
    assert first == second
    assert calls["n"] == 1
    assert first["value"] == 42


def test_scenario_version_parent_and_observation_change(db_path: Path):
    base_snap = snapshot(db_path, "base")
    child = create_scenario(
        db_path,
        "增补方案",
        parent_id="base",
        scenario_id="added",
        metadata={"datum": "fixed"},
    )
    assert child["version"] == 2
    assert child["parent_id"] == "base"
    assert child["n_observations"] == 7
    assert len(list_scenarios(db_path)) == 2

    child_snap = snapshot(db_path, "added")
    assert child_snap["input_hash"] != base_snap["input_hash"]

    observations = child["observations"] + [
        {"kind": "angle", "backsight": "D", "station": "C", "foresight": "A", "sigma_arcsec": 1.0}
    ]
    updated = update_observations(db_path, "added", observations)
    assert updated["n_observations"] == 8
    modified_snap = snapshot(db_path, "added")
    assert modified_snap["input_hash"] != child_snap["input_hash"]
    result = get_or_compute_result(db_path, "added")
    assert result["summary"]["n_observations"] == 8
    assert result["summary"]["max_mp_mm"] == pytest.approx(1.3102600010, rel=1e-8)

    # 再追加一条观测也必须改变哈希。
    add_observation(
        db_path,
        "added",
        {"kind": "distance", "from": "C", "to": "D", "a_m": 0.002, "b_ppm": 2.0},
    )
    assert snapshot(db_path, "added")["input_hash"] not in {
        base_snap["input_hash"],
        child_snap["input_hash"],
        modified_snap["input_hash"],
    }


def test_scenario_list_contains_observations_and_counts(db_path: Path):
    create_scenario(db_path, "方案二", parent_id="base", scenario_id="two")
    rows = list_scenarios(db_path)
    assert [row["id"] for row in rows] == ["base", "two"]
    assert rows[1]["n_observations"] == 7
    assert len(rows[1]["observations"]) == 7


def test_unknown_scenario_and_project_errors(db_path: Path):
    with pytest.raises(KeyError):
        snapshot(db_path, "missing")
    with pytest.raises(KeyError):
        load_project(db_path, project_id="missing")
    with pytest.raises(KeyError):
        get_or_compute_result(db_path, "missing")
