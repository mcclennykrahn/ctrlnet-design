你在 /workspace/ctrlnet-design 工作（ctrlnet 包已在上一步写好，位于 src/ctrlnet）。全部在本机完成，不使用 Colab/Google Drive。Python 用 /workspace/venvs/ctrlnet/bin/python（已装 numpy、matplotlib、pytest、nbconvert、ipykernel），先执行 /workspace/venvs/ctrlnet/bin/pip install -e /workspace/ctrlnet-design。

本次任务（第 2 步），请自己反复运行、修复直到全部通过：
1. tests/（pytest）：
   - tests/test_section13.py：第 13 节两方案的点 σE/σN/mp/椭圆半轴（±0.001 mm）、5 条边 σs（±0.001 mm）和相对精度分母（与 1:60565 等完全一致），期望值见 docs/redesign_plan.md §10.2.2；结构断言：rank=4，冗余 3/4，Cx 对称，sum r_i=3/4。
   - 可靠性期望（λ0=7.849 对应 α=0.05、power=0.80；外部可靠性取 MDB 引起的最大单个坐标分量绝对值 mm）：
     基准 r_i [AC,BC,AD,BD,CD,∠CAB,∠ABD]=[0.3252,0.6569,0.6569,0.3252,0.8975,0.0692,0.0692]；MDB AC 9.875 mm、BC 6.982 mm、CD 5.944 mm、∠CAB 10.653″；外部 AC 6.663、BC 3.211、CD 0.305、∠CAB 4.807 mm。
     增补 r_i=[0.6283,0.8235,0.8074,0.6442,0.8994,0.0842,0.0722,0.0408]；MDB AC 7.104 mm、CD 5.938 mm、∠DCA 13.864″；外部 AC 2.640、CD 0.301、∠DCA 3.180 mm。容差 r_i ±1e-3，MDB 相对 1e-3，外部 ±0.002 mm。
   - 偏导中心差分校验（距离、角度、方向）；观测顺序打乱结果不变。
   - tests/test_rank.py：去掉一个固定点（只有距离+角）应抛 RankDeficientError 且信息有意义；某待定点只有一条观测时抛错；自由网最小约束能求解且 rank 处理正确；σ≤0 / NaN / 重合点抛对应异常。
   - tests/test_optimize.py：贪心优化在第 13 节基准网上从候选角/距离中选择能降低最大 mp 的观测，步骤记录单调不增。
2. 演示：scripts/run_demo.py（以及同内容的 notebooks/demo.ipynb，用 jupyter nbconvert --to notebook --execute --inplace 在本机执行，kernel 用 venv 的 python，必要时 python -m ipykernel install --user --name ctrlnet）。运行后在 /workspace/ctrlnet-design/outputs/ 生成：
   - network_ellipses_base.png、network_ellipses_added.png（网图 + 标准椭圆与 95% 椭圆，椭圆放大倍数在图中注明），或一张左右对比图 network_ellipses_compare.png；
   - scenario_comparison.png（基准 vs 增补：各点 mp、各边相对精度分母的柱状对比）；
   - reliability_ri.png（两方案每条观测 r_i 柱状图，标出 0.3/0.5 等常用阈值线）；
   - optimizer_steps.png（优化每步目标值）；
   - tables：points.csv、edges.csv、reliability.csv、optimizer.csv，以及汇总 results.md（中文表格）。
   图中中文如字体缺失就用英文标签，避免方框乱码。打印关键结果。
3. README.md（中文）：项目简介、与 docs 方案的对应关系（实现了 MVP 哪些部分、未实现部分：地图/GUI/API/DEM 通视/水准等）、安装、运行测试、运行演示、输出说明、API 简例、目录结构。另加 .gitignore（venv、__pycache__、*.egg-info、.pytest_cache、.ipynb_checkpoints），outputs/ 要提交。
4. 运行 `/workspace/venvs/ctrlnet/bin/python -m pytest -q` 全部通过、demo 成功后，git 提交（git config user.name "mcclennykrahn"，user.email 用 "mcclennykrahn@users.noreply.github.com"，只在本仓库设置），然后：
   gh repo create mcclennykrahn/ctrlnet-design --private --source /workspace/ctrlnet-design --remote origin --push
   （如果名字已被占用就用 ctrlnet-design-mvp）。不要提交任何密钥或 token，提交前用 git status 检查。.dsh-prompts/ 目录可以提交（里面只有任务说明）。
5. 最后用几行输出：pytest 结果摘要、outputs/ 文件列表、git log -1 --oneline、仓库 URL、gh repo view 的 visibility。
