# 离线安装

联网构建机与离线目标机须使用相同操作系统、CPU 架构和 Python 版本。以下命令在仓库根目录执行；Python 环境统一使用仓库内 `.venv`。

## 联网准备

```bash
python3 -m venv /workspace/ctrlnet-design/.venv
/workspace/ctrlnet-design/.venv/bin/pip install -e '/workspace/ctrlnet-design[test,build]'
/workspace/ctrlnet-design/scripts/build_dist.sh
mkdir -p /workspace/ctrlnet-design/dist/wheelhouse
/workspace/ctrlnet-design/.venv/bin/pip download --only-binary=:all: \
  --dest /workspace/ctrlnet-design/dist/wheelhouse \
  '/workspace/ctrlnet-design/dist/ctrlnet-0.1.0-py3-none-any.whl[webmap,tiles]'
```

将整个 `dist/` 和本文复制到离线机器。`wheelhouse` 包含应用 wheel 和全部运行依赖；只复制 sdist 不足以离线安装。若仅使用核心功能，可以省去 `[webmap,tiles]`。开发测试和构建依赖不属于运行时 wheelhouse。

## 离线目标机

目标目录示例仍为 `/workspace/ctrlnet-design`。若已有开发环境，请在另一台目标机验证，勿覆盖已有 `.venv`。

```bash
python3 -m venv /workspace/ctrlnet-design/.venv
/workspace/ctrlnet-design/.venv/bin/pip install --no-index \
  --find-links=/workspace/ctrlnet-design/dist/wheelhouse 'ctrlnet[webmap,tiles]==0.1.0'
/workspace/ctrlnet-design/.venv/bin/ctrlnet --help
/workspace/ctrlnet-design/.venv/bin/ctrlnet serve --help
```

安装后无需源码目录，HTML、CSS、JavaScript、Leaflet 和图标均随包提供。工程 SQLite、DEM、MBTiles 是独立用户数据，须另外复制并通过显式路径指定：

```bash
/workspace/ctrlnet-design/.venv/bin/ctrlnet adjust --project /workspace/ctrlnet-design/data/sample/demo_project.sqlite --out /workspace/ctrlnet-design/outputs/adjust.json
/workspace/ctrlnet-design/.venv/bin/ctrlnet report --project /workspace/ctrlnet-design/data/sample/demo_project.sqlite --out /workspace/ctrlnet-design/outputs/report --no-docx
/workspace/ctrlnet-design/.venv/bin/ctrlnet serve --project /workspace/ctrlnet-design/data/sample/demo_project.sqlite
/workspace/ctrlnet-design/.venv/bin/ctrlnet tiles /workspace/ctrlnet-design/data/sample/demo_tiles.mbtiles
```

网页服务仅监听本地回环地址。DOCX 报告另需本机 pandoc；Markdown/HTML 不需要。此交付不包含签名与 Windows 安装器。
