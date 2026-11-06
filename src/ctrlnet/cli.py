"""Installed CLI; optional features are imported only after argument parsing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def adjust_main(argv=None):
    parser = argparse.ArgumentParser(prog="ctrlnet adjust", description="计算 SQLite 工程方案并缓存结果")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--scenario")
    parser.add_argument("--out", type=Path, help="JSON 输出路径；默认标准输出")
    parser.add_argument("--force", action="store_true", help="重新计算缓存")
    args = parser.parse_args(argv)
    if not args.project.is_file():
        parser.error(f"工程文件不存在：{args.project}")
    from .store import get_or_compute_result
    result = get_or_compute_result(args.project, args.scenario, force=args.force)
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


def tiles_main(argv=None):
    parser = argparse.ArgumentParser(prog="ctrlnet tiles", description="检查离线 MBTiles 或导出 XYZ PNG 目录（需要 tiles extra）")
    parser.add_argument("path", type=Path, help="MBTiles 文件")
    parser.add_argument("--out", type=Path, help="可选 XYZ 导出目录")
    args = parser.parse_args(argv)
    from .tiles import MBTiles
    with MBTiles(args.path, readonly=True) as db:
        result = {"metadata": db.metadata, "count": db.connection.execute("SELECT count(*) FROM tiles").fetchone()[0]}
        if args.out:
            result["exported"] = db.export_xyz(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    descriptions = {"adjust": "计算与缓存工程平差结果", "report": "生成设计报告", "package": "导出、检查与导入工程包", "serve": "启动离线网页地图", "tiles": "检查或导出离线瓦片"}
    parser = argparse.ArgumentParser(prog="ctrlnet", description="CTRLNET 控制网设计工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, description in descriptions.items():
        subparsers.add_parser(name, help=description, add_help=False)
    # Dispatch untouched arguments so each existing parser retains its own validation/help.
    args = parser.parse_args(argv[:1])
    if args.command == "adjust":
        return adjust_main(argv[1:])
    if args.command == "tiles":
        return tiles_main(argv[1:])
    if args.command == "report":
        from .report import main as run
    elif args.command == "package":
        from .package import main as run
    else:
        from .webmap.__main__ import main as run
    return run(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
