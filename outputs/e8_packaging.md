# E8 安装包验证

- wheel 与 sdist 构建成功，包含全部 14 个离线静态资源。
- wheel 以 --no-index --no-deps 安装到仓库 .venv 成功（依赖已预装）。
- 已安装 wheel 从 .tmp 运行全部五个子命令 --help 成功，无需示例数据库。
- adjust、tiles 实际演示：e8_adjust.json、e8_tiles.json。
- 完整离线依赖 wheelhouse 准备步骤见 docs/offline_install.md。
- 最终全量测试：287 passed, 1 skipped, 2 xfailed, 1 warning（11.98s）。
