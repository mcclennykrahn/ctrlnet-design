第 A 步（小修复）。
1. 包安装：创建 /workspace/ctrlnet-design/.venv（加入 .gitignore），`.venv/bin/pip install -e '.[test]'` 正常可编辑安装；移除 pyproject.toml 里的 pytest `pythonpath = ["src"]` 以及 scripts/run_demo.py、notebook 中把 src 加进 sys.path 的回退代码；确认 `.venv/bin/python -c "import ctrlnet; print(ctrlnet.__file__)"` 指向 src。notebook 的 kernel 改用 .venv（python -m ipykernel install --user --name ctrlnet-venv，或 nbconvert 指定 kernel），需要的话在 .venv 装 ipykernel/nbconvert（放到 extras [demo]）。
2. 图形：网图图例不能遮挡任何点或椭圆（放到坐标轴外部，如右侧或下方，用 bbox_to_anchor 并 tight_layout/bbox_inches='tight'）；观测线要清晰可见（深色、线宽≥1.5，距离和角度用不同颜色/线型区分，角度用测站处小圆弧或从测站发出的两条带箭头短线表示），点名标签不与椭圆重叠。同样检查 scenario_comparison.png、reliability_ri.png、optimizer_steps.png 的标签/图例无遮挡。
3. 重新运行 pytest 与 scripts/run_demo.py、执行 notebooks/demo.ipynb，重新生成 outputs/，更新 README 安装说明。
