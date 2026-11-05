"""工程包导出/导入、manifest/哈希校验与样例包体积测试。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

import pytest

from ctrlnet.exceptions import PackageError
from ctrlnet.package import (
    MANIFEST_NAME,
    export_project_package,
    import_project_package,
    inspect_project_package,
    read_manifest,
)
from ctrlnet.store import (
    get_or_compute_result,
    load_project,
    save_project,
    snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PACKAGE = ROOT / "data" / "sample" / "demo_project.ctrlnet.zip"


def _project(project_id: str = "pkg-project") -> Dict[str, Any]:
    return {
        "id": project_id,
        "name": "工程包测试",
        "description": "导出/导入往返",
        "crs": "EPSG:32650",
        "metadata": {
            "datum": "fixed",
            "default_scenario": "base",
            "resource_path": "assets/note.json",
        },
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


def _make_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "source"
    project_dir.mkdir()
    assets = project_dir / "assets"
    assets.mkdir()
    (assets / "note.json").write_text('{"note":"small resource"}\n', encoding="utf-8")
    db = project_dir / "project.sqlite"
    save_project(db, _project())
    return db


def _rewrite_zip(
    source: Path,
    target: Path,
    *,
    mutate: Optional[Callable[[Dict[str, Any]], None]] = None,
    drop: Sequence[str] = (),
) -> None:
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            if info.filename in drop:
                continue
            data = zin.read(info.filename)
            if info.filename == MANIFEST_NAME and mutate is not None:
                manifest = json.loads(data.decode("utf-8"))
                mutate(manifest)
                data = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            zout.writestr(info.filename, data)


@pytest.fixture()
def exported(tmp_path: Path) -> Dict[str, Any]:
    db = _make_project(tmp_path)
    result = export_project_package(db, tmp_path / "project.ctrlnet.zip")
    return {
        "db": db,
        "zip": Path(result["zip_path"]),
        "manifest": result["manifest"],
        "size_bytes": result["size_bytes"],
    }


def test_export_manifest_files_and_resources(exported: Dict[str, Any]) -> None:
    manifest = exported["manifest"]
    assert manifest["format_version"] == "1.0"
    assert manifest["entrypoint"] == "project.sqlite"
    assert manifest["input_hash"] is None  # 未生成快照时允许为空
    assert manifest["project"]["id"] == "pkg-project"
    paths = {item["path"] for item in manifest["files"]}
    assert "project.sqlite" in paths
    assert "assets/note.json" in paths
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
    assert manifest["files"][0]["role"] == "database"
    assert any(
        item["path"] == "assets/note.json" and item["packaged"]
        for item in manifest["dependencies"]
    )
    # manifest 与 zip 内实际文件都可读。
    read = read_manifest(exported["zip"])
    assert read["package_id"] == manifest["package_id"]
    inspect = inspect_project_package(exported["zip"])
    assert inspect["size_bytes"] == exported["size_bytes"]
    with zipfile.ZipFile(exported["zip"]) as archive:
        assert MANIFEST_NAME in archive.namelist()


def test_roundtrip_project_snapshot_result_and_resource(
    exported: Dict[str, Any], tmp_path: Path
) -> None:
    db = exported["db"]
    source_project = load_project(db)
    source_snapshot = snapshot(db, "base")
    source_result = get_or_compute_result(db, "base")

    imported = import_project_package(exported["zip"], tmp_path / "imported")
    loaded = imported["project"]
    assert loaded == source_project
    imported_db = Path(imported["project_path"])
    assert imported_db.is_file()
    assert (tmp_path / "imported" / "assets" / "note.json").is_file()
    assert imported["resources"] == ["assets/note.json"]
    assert imported["manifest"]["package_id"] == exported["manifest"]["package_id"]

    imported_snapshot = snapshot(imported_db, "base")
    imported_result = get_or_compute_result(imported_db, "base")
    assert imported_snapshot["input_hash"] == source_snapshot["input_hash"]
    assert imported_snapshot["payload"] == source_snapshot["payload"]
    assert imported_result == source_result


def test_export_import_then_compute_fresh_project(tmp_path: Path) -> None:
    db = tmp_path / "fresh" / "fresh.sqlite"
    save_project(db, _project("fresh-project"))
    exported = export_project_package(db, tmp_path / "fresh.zip")
    assert exported["manifest"]["input_hash"] is None
    imported = import_project_package(exported["zip_path"], tmp_path / "fresh-imported")
    source_snap = snapshot(db, "base")
    imported_snap = snapshot(imported["project_path"], "base")
    assert source_snap["input_hash"] == imported_snap["input_hash"]
    source_result = get_or_compute_result(db, "base")
    imported_result = get_or_compute_result(imported["project_path"], "base")
    assert imported_result == source_result
    assert imported_result["summary"]["max_mp_mm"] == pytest.approx(
        1.7160837620, rel=1e-9
    )


def test_export_refuses_overwrite(exported: Dict[str, Any]) -> None:
    with pytest.raises(FileExistsError):
        export_project_package(exported["db"], exported["zip"])
    replaced = export_project_package(exported["db"], exported["zip"], overwrite=True)
    assert replaced["manifest"]["project"]["id"] == "pkg-project"


def test_missing_or_bad_manifest_is_rejected(tmp_path: Path) -> None:
    db = _make_project(tmp_path)
    no_manifest = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(no_manifest, "w") as archive:
        archive.write(db, "project.sqlite")
    with pytest.raises(PackageError, match="manifest"):
        import_project_package(no_manifest, tmp_path / "x1")

    bad_json = tmp_path / "bad-json.zip"
    with zipfile.ZipFile(bad_json, "w") as archive:
        archive.writestr(MANIFEST_NAME, b"{not-json")
    with pytest.raises(PackageError):
        read_manifest(bad_json)

    exported = export_project_package(db, tmp_path / "base.zip")
    unsupported = tmp_path / "unsupported.zip"
    _rewrite_zip(
        Path(exported["zip_path"]),
        unsupported,
        mutate=lambda m: m.__setitem__("format_version", "2.0"),
    )
    with pytest.raises(PackageError, match="格式版本"):
        import_project_package(unsupported, tmp_path / "x2")


def test_missing_file_and_hash_mismatch_are_rejected(
    exported: Dict[str, Any], tmp_path: Path
) -> None:
    missing = tmp_path / "missing.zip"
    _rewrite_zip(exported["zip"], missing, drop=("project.sqlite",))
    with pytest.raises(PackageError, match="缺少文件"):
        import_project_package(missing, tmp_path / "missing-import")

    bad_hash = tmp_path / "bad-hash.zip"
    _rewrite_zip(
        exported["zip"],
        bad_hash,
        mutate=lambda m: m["files"][0].__setitem__("sha256", "0" * 64),
    )
    with pytest.raises(PackageError, match="SHA-256"):
        import_project_package(bad_hash, tmp_path / "hash-import")

    bad_size = tmp_path / "bad-size.zip"
    _rewrite_zip(
        exported["zip"],
        bad_size,
        mutate=lambda m: m["files"][0].__setitem__("bytes", m["files"][0]["bytes"] + 1),
    )
    with pytest.raises(PackageError, match="字节数"):
        import_project_package(bad_size, tmp_path / "size-import")


def test_unsafe_paths_and_duplicate_entries_are_rejected(
    exported: Dict[str, Any], tmp_path: Path
) -> None:
    unsafe = tmp_path / "unsafe.zip"
    _rewrite_zip(
        exported["zip"],
        unsafe,
        mutate=lambda m: m["files"].append(
            {"path": "../evil.sqlite", "role": "resource", "bytes": 0, "sha256": "0" * 64}
        ),
    )
    with pytest.raises(PackageError, match="非法"):
        import_project_package(unsafe, tmp_path / "unsafe-import")

    duplicate = tmp_path / "duplicate.zip"
    _rewrite_zip(
        exported["zip"],
        duplicate,
        mutate=lambda m: m["files"].append(dict(m["files"][0])),
    )
    with pytest.raises(PackageError, match="重复"):
        import_project_package(duplicate, tmp_path / "duplicate-import")


def test_import_refuses_nonempty_destination(exported: Dict[str, Any], tmp_path: Path) -> None:
    destination = tmp_path / "occupied"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        import_project_package(exported["zip"], destination)
    imported = import_project_package(exported["zip"], destination, overwrite=True)
    assert Path(imported["project_path"]).is_file()
    assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_sample_package_is_small_and_importable(tmp_path: Path) -> None:
    assert SAMPLE_PACKAGE.is_file(), "应提交 data/sample/demo_project.ctrlnet.zip"
    assert SAMPLE_PACKAGE.stat().st_size <= 2 * 1024 * 1024
    manifest = read_manifest(SAMPLE_PACKAGE)
    assert manifest["project"]["id"] == "demo-project"
    assert manifest["entrypoint"] == "project.sqlite"
    assert manifest["input_hash"]
    assert len(manifest["snapshot_hashes"]) == 4
    assert any(item["packaged"] for item in manifest["dependencies"])
    assert all(not item["path"].startswith("/") for item in manifest["files"])
    imported = import_project_package(SAMPLE_PACKAGE, tmp_path / "sample")
    assert imported["project"]["id"] == "demo-project"
    assert imported["project"]["n_points"] == 11
    assert imported["project"]["n_scenarios"] == 4
    assert (tmp_path / "sample" / "data" / "sample" / "dem_sample.tif").is_file()
