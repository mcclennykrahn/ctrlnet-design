第 C2 步（下一阶段：精确优化器）。先阅读 docs/redesign_plan.md §5.6 与现有 src/ctrlnet/optimize.py。
1. 在贪心优化器中支持 A 最优（trace Cx）、D 最优（log det Cx）、E 最优（λmax Cx）以及最大 mp、最弱边相对精度准则，接口统一（criterion="A"/"D"/"E"/"max_mp"/"worst_rel"）。
2. 精确求解：小网（候选 ≤ ~20）用分支定界或穷举（利用预算剪枝、单调性下界，加观测不会使 Cx 变差）求预算约束下的全局最优；另外提供基于 scipy.optimize.milp 或 PuLP（能装则装，放 extras [opt]）的 MICP/线性化近似形式（例如 A 最优的 SDP/线性化不可行时，用基于“每个候选对各点 mp 的贡献”的线性代理模型作为 MILP，并用精确评价校正），要说明是精确还是近似。成本模型：每条观测成本 + 新设站固定成本（测站首次使用时额外成本）。
3. 测试 tests/test_exact_optimizer.py：小例子穷举结果 = 分支定界结果；精确解目标值 ≤ 贪心；预算约束满足；设站成本计入正确；五种准则都能运行。
4. 演示 scripts/run_optimizer_compare.py：第 13 节网及 DEM 演示网（只用通视的候选）在多个预算下对比贪心/局部搜索/精确的目标值与耗时，输出 outputs/optimizer_comparison.png、outputs/optimizer_comparison.csv、outputs/optimizer_comparison.md。
