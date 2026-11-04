第 B1 步（下一阶段：高程网）。先阅读 docs/redesign_plan.md 的 §5.9 高程/水准网、§9 路线图（P1 相关）和 §10 测试要求。
实现 src/ctrlnet/leveling.py（并在 __init__ 导出）：
1. 水准网：点高程 H（固定/待定/加权约束），观测高差 dH(frm,to, length_km, sigma_per_km_mm，σ=σ_km·sqrt(L))，也支持按测站数 σ=σ_station·sqrt(n)；最小二乘设计态精度：Cx、每点高程中误差、相对高差中误差、r_i、MDB、外部可靠性（复用已有 reliability 思路），秩亏（无高程基准）时抛 RankDeficientError，自由网最小约束可选。
2. 三角高程：TrigHeight(frm,to, 斜距或平距、天顶距、仪器高 i、目标高 v、k=0.13、R=6371000)，高差 h = S·cos(z)+(1−k)·S²sin²z/(2R)+i−v（平距形式同理），按误差传播（σ_z 角秒、σ_S、σ_i、σ_v、可选 σ_k）得到高差 σ；可作为观测加入高程网。注明正常高/大地高仅作为属性字段（MVP 不做高程异常模型）。
3. 测试 tests/test_leveling.py：手算可核对的小网（如闭合水准环、附合水准路线）精度与解析解一致；单条路线中误差 = σ_km·sqrt(L) 验证；r_i 之和 = 冗余数；无基准秩亏；三角高程公式与独立数值计算一致、球气差项数值（例如 S=1000 m 时约 0.0683 m 量级，用 k=0.13 精确计算核对）。
4. 演示 scripts/run_leveling_demo.py：一个 5~6 点水准网 + 两条三角高程观测，输出 outputs/leveling_points.csv、outputs/leveling_results.md、outputs/leveling_network.png（点高程中误差标注、线宽按观测权重）。
