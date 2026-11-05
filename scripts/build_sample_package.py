#!/usr/bin/env python3
"""生成并回读校验可提交的样例工程包 ``data/sample/demo_project.ctrlnet.zip``。

包内含 SQLite 工程、``manifest.json``、裁剪后的 303 KB DEM 小样与
``terrain_project.json``；不打包 ``data/cache/`` 中的原始大 DEM。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

from ctrlnet.package import export_project_package, import_project_package, read_manifest
from ctrlnet.store import get_or_compute_result, load_project, snapshot

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sample" / "demo_project.sqlite"
OUT_PATH = ROOT / "data" / "sample" / "demo_project.ctrlnet.zip"
MAX_SIZE = 2 * 1024 * 1024


def _verify_roundtrip() -> Dict[str, Any]:
    # 在临时副本上做快照/结果校验，避免在提交的源工程库里追加缓存记录。
    with tempfile.TemporaryDirectory(prefix="ctrlnet-sample-source-") as source_dir:
        source_db = Path(source_dir) / "source.sqlite"
        shutil.copy2(DB_PATH, source_db)
        source = load_project(source_db)
        scenario_ids = [str(item["id"]) for item in source["scenarios"]]
        source_snapshots = {
            sid: snapshot(source_db, sid)["input_hash"] for sid in scenario_ids
        }
        source_results = {
            sid: get_or_compute_result(source_db, sid) for sid in scenario_ids
        }
        with tempfile.TemporaryDirectory(prefix="ctrlnet-sample-verify-") as tmpdir:
            imported = import_project_package(OUT_PATH, Path(tmpdir) / "project")
            loaded = imported["project"]
            if loaded != source:
                raise SystemExit("样例包回读工程与源工程不一致")
            for sid in scenario_ids:
                if snapshot(imported["project_path"], sid)["input_hash"] != source_snapshots[sid]:
                    raise SystemExit(f"快照哈希不一致：{sid}")
                if get_or_compute_result(imported["project_path"], sid) != source_results[sid]:
                    raise SystemExit(f"精度结果不一致：{sid}")
            resources = [
                path
                for path in (
                    Path(imported["project_path"]).parent / "data" / "sample" / "dem_sample.tif",
                    Path(imported["project_path"]).parent
                    / "data"
                    / "sample"
                    / "terrain_project.json",
                )
                if path.is_file()
            ]
            if len(resources) != 2:
                raise SystemExit("样例包资源未完整恢复")
    return {
        "scenarios": len(scenario_ids),
        "snapshot_hashes": source_snapshots,
        "results": source_results,
    }


def main() -> int:
    result = export_project_package(DB_PATH, OUT_PATH, overwrite=True)
    OUT_PATH.chmod(0o644)
    size = int(result["size_bytes"])
    if size > MAX_SIZE:
        raise SystemExit(f"样例包 {size} B 超过 2 MiB 上限")
    checked = _verify_roundtrip()
    manifest = read_manifest(OUT_PATH)
    print(f"样例包：{OUT_PATH.relative_to(ROOT)}")
    print(f"体积：{size} B（{size / 1024:.1f} KiB，上限 2 MiB）")
    print(f"工程：{manifest['project']['id']} / {manifest['project']['n_points']} 点 / "
          f"{manifest['project']['n_scenarios']} 方案")
    print("文件：" + ", ".join(item["path"] for item in manifest["files"]))
    print(f"回读校验：{checked['scenarios']} 个方案的快照哈希与精度结果一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
