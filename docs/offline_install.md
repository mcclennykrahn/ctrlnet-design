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
  '/workspace/ctrlnet-design/dist/ctrlnet-0.8.0-py3-none-any.whl[webmap,tiles]'
```

将整个 `dist/` 和本文复制到离线机器。`wheelhouse` 包含应用 wheel 和全部运行依赖；只复制 sdist 不足以离线安装。若仅使用核心功能，可以省去 `[webmap,tiles]`。开发测试和构建依赖不属于运行时 wheelhouse。

## 离线目标机

目标目录示例仍为 `/workspace/ctrlnet-design`。若已有开发环境，请在另一台目标机验证，勿覆盖已有 `.venv`。

```bash
python3 -m venv /workspace/ctrlnet-design/.venv
/workspace/ctrlnet-design/.venv/bin/pip install --no-index \
  --find-links=/workspace/ctrlnet-design/dist/wheelhouse 'ctrlnet[webmap,tiles]==0.8.0'
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

## 未打标签的候选分发验证

在构建环境安装 `.[build]` 后执行（输出目录必须为空，防止混入旧版本）：

```bash
.venv/bin/python scripts/build_release.py --out dist/candidate-0.8.0
.venv/bin/python scripts/test_release_install.py dist/candidate-0.8.0
(cd dist/candidate-0.8.0 && sha256sum -c SHA256SUMS)
```

构建使用隔离的构建依赖，并从 sdist 构建 wheel。目录包含 wheel、sdist、
`SHA256SUMS` 和 `release.json`（源码提交、工作区是否有改动、文件摘要）。
构建成功不代表验证成功；第二条命令在源码目录外新建 venv，联网安装 wheel
及 webmap 依赖，检查依赖、三个命令入口、样例副本平差，以及实际 HTTP 服务与
随包 Leaflet 资源。不会写入原始样例数据库。测试临时环境自动删除。
候选包版本仍为 0.8.0；未打 tag、未上传包索引，摘要不是签名。

这只是本地安装与分发准备流程，不能据此声称生产环境已认证。
离线 wheelhouse 必须在目标平台单独准备并验收；跨平台安装、签名、自动发布、
部署运维与回滚仍需另外验证。升级前备份用户工程，保留上一个已验证 wheel
和运行依赖，在独立 venv 中验证后再切换启动命令；不要覆盖唯一的用户数据。
