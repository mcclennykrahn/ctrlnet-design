"""``ctrlnet-web`` / ``python -m ctrlnet.webmap`` 本地服务入口。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctrlnet-web",
        description="启动仅绑定本机回环地址的 CTRLNET 离线网页地图",
    )
    parser.add_argument("--host", default="127.0.0.1", help="仅允许回环地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    parser.add_argument("--project", type=Path, default=None, help="SQLite 工程路径（data/sample/demo_project.sqlite）")
    parser.add_argument("--log-level", default="info", help="uvicorn 日志级别")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host not in LOOPBACK_HOSTS:
        print(
            f"拒绝绑定 {args.host!r}：本地网页地图只允许回环地址 {sorted(LOOPBACK_HOSTS)}",
            file=sys.stderr,
        )
        return 2
    if not (0 < args.port < 65536):
        print(f"端口非法：{args.port}", file=sys.stderr)
        return 2
    if args.project is not None:
        os.environ["CTRLNET_PROJECT"] = str(Path(args.project).expanduser().resolve())

    try:
        import uvicorn
    except ImportError:
        print(
            "缺少 uvicorn：请安装 .[webmap]\n"
            "  .venv/bin/pip install -e '.[webmap,terrain]'",
            file=sys.stderr,
        )
        return 1

    from .app import create_app

    application = create_app(args.project)
    print(f"CTRLNET webmap: http://{args.host}:{args.port}/  (Ctrl+C 停止)")
    uvicorn.run(application, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
