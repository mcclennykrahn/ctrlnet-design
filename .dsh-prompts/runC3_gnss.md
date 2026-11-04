第 C3 步（下一阶段：GNSS 基线网与高程异常近似）。先阅读 docs/redesign_plan.md §5.8、§5.9、§5.2。
1. src/ctrlnet/gnss.py：大地坐标(φ,λ,h) ↔ ECEF ↔ 局部 ENU（WGS84，自己实现公式，不必依赖 pyproj）；3D 基线向量观测 (ΔX,ΔY,ΔZ) 带完整 3×3 协方差（可来自 ECEF 或 ENU，正确旋转），设计矩阵，Cholesky 白化；3D 网参数（各待定点 E,N,U 或 X,Y,Z），基准：固定点/最小约束；与地面观测联合：把 3D 结果的水平部分与平面网（距离、角度）以及水准高差联合平差（在局部 ENU 平面近似下，说明假设）。输出点位 3D 精度、水平误差椭圆、垂直中误差、基线相对精度、r_i/MDB（复用现有可靠性）。
2. 高程异常近似：给定若干同时有大地高 h 和正常高 H 的点，拟合常数或平面（a+bE+cN）高程异常 ζ=h−H 模型，返回参数精度与残差，用于把 GNSS 高转换成正常高；结果明确标注“近似，仅适用于小范围”。如能在无需登录的情况下获取小型公开 EGM2008/EGM96 格网（例如 PROJ-data 的 us_nga_egm96_15.tif 通过 https://cdn.proj.org/ ），可选实现插值并与平面拟合比较；拿不到就跳过并在 README 说明。
3. 测试 tests/test_gnss.py：坐标转换往返精度（<1e-6 m）、已知点 ENU 数值、协方差旋转正确（迹不变）、纯 GNSS 网精度与解析一致、联合平差中加入地面观测后精度不变差、高程异常平面拟合恢复已知参数。
4. 演示 scripts/run_gnss_demo.py：在 DEM 演示区用 terrain_project.json 的点构造 GNSS 基线网 + 地面边 + 水准，输出 outputs/gnss_network.png（基线、水平椭圆、垂直精度标注）、outputs/geoid_fit.png（ζ 拟合残差）、outputs/gnss_results.md/.csv。
