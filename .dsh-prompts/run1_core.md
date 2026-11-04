你在目录 /workspace/ctrlnet-design 工作（所有文件都用绝对路径写在这个目录下，不要写到别处）。
这是一个新的 Python 项目，实现 /workspace/ctrlnet-design/docs/redesign_plan.md 中“平面控制网精度估算与优化设计”重设计方案的 MVP 计算核心（不做地图、GUI、API、数据库）。原方案见 docs/original_plan.md，第 13 节是必须通过的黄金算例；重设计 §5.3 基准、§5.4 可靠性、§5.5 精度指标、§5.6 优化、§10.2 回归要求可作参考。

本次任务（第 1 步）：只写包代码，测试、Notebook、README 后续再做。要求：

1. 包名 ctrlnet，src 布局：/workspace/ctrlnet-design/src/ctrlnet/，加 pyproject.toml（setuptools，依赖 numpy>=1.24、matplotlib>=3.6；可选 extra [test]=pytest；python>=3.9）和 requirements.txt。
2. 模块建议：
   - model.py：Point(name, E, N, fixed: bool, 可选 sigma_E/sigma_N 用于加权约束)、观测 Distance(frm,to,a,b_ppm)、Direction(station,target,sigma_arcsec，含测站定向未知数)、Angle(backsight, station, foresight, sigma_arcsec)（角=前视方位角−后视方位角）、GnssBaseline2D(frm,to,sigma_E,sigma_N,可选相关系数)、Network(points, observations) 和 Scenario。距离先验方差 σ² = a² + (b·1e-6·s)²。
   - design.py：参数排列（按待定点出现顺序，[E1,N1,E2,N2,...]，可传入显式顺序；方向观测每个测站附加一个定向参数），设计矩阵 A（距离、方位/方向、角度、GNSS 基线的解析偏导，单位：米与弧度），权阵/白化（每行除以 σ；GNSS 2×2 协方差用 Cholesky 白化）。
   - datum.py：三种基准：固定点（从参数中剔除）、加权约束（对点坐标附加伪观测）、自由网最小约束（内约束/伪逆，S 变换到选定基准点，至少平移+旋转+尺度依据观测类型判断）。
   - adjustment.py：solve(network, datum=...) 返回结果对象：A、Cx（协方差，m²）、rank、条件数、冗余数 n−u；用 SVD 检查秩，秩亏时抛出自定义异常 RankDeficientError，信息中说明秩、参数数、零空间对应的参数/点（例如“缺少基准：平移/旋转未定义”或“点 X 观测不足”），非有限值或 σ≤0 抛 InvalidPrecisionError，两点重合抛 InvalidGeometryError。
   - precision.py：每个待定点 σE、σN、mp=sqrt(σE²+σN²)、误差椭圆（标准半轴 a≥b，长半轴方位角，从北顺时针，度），95% 椭圆系数 k=sqrt(chi2_2(0.95))=sqrt(-2ln0.05)≈2.4477；边的相对精度：σ_s（沿边的距离函数的协方差传播，固定点协方差为 0）以及 1:round(S/σ_s)；最弱点、最弱边。
   - reliability.py：Ql、Qv=Ql−A Cx Aᵀ，多余观测分量 r_i=(Qv P)_ii（白化后 = 1−H_ii），sum r_i 应等于冗余数；MDB_i = σ_i·sqrt(λ0/r_i)，λ0 由 α=0.05 双侧、power=0.80 计算（标准正态分位数，λ0=(z_{1-α/2}+z_{power})² ≈ 7.849，用 math/statistics.NormalDist，不要引入 scipy）；外部可靠性：MDB_i 对坐标的影响 ∇x = Cx Aᵀ P e_i·MDB_i，报告每个点位移最大值（mm）；w 检验函数（给定残差时可用）。
   - compare.py：两个方案的对比表（点 mp、椭圆、边相对精度、冗余数、最弱指标、观测数作为工作量）。
   - optimize.py：贪心观测增补优化器：输入基础网和候选观测列表（带成本，默认 1），目标可选“最小化最大 mp”“最小化 trace(Cx)”（A 最优）“最大化最弱边相对精度”，在预算或目标阈值内逐个加入收益/成本最大的候选，返回每步记录；可选一次简单局部搜索（1 换 1 交换）改进。
   - plot.py：matplotlib 画网图（固定点三角形、待定点圆点、距离/角度观测线、误差椭圆按可调放大倍数画，标准或 95%）。
   - examples.py：section13_base() 与 section13_added() 构造第 13 节两个方案（A(0,0)、B(100,0) 固定，C(0,100)、D(100,100) 待定，参数顺序 [EC,NC,ED,ND]，距离 AC、BC、AD、BD、CD，a=0.002 m、b=2 ppm，角 (C,A,B)、(A,B,D) 1″，增补角 (D,C,A) 1″）。
   - report.py：把结果格式化成文本表格（中文表头），点位保留三位毫米。
   - __init__.py 导出主要 API。
3. 写完后用 python 实际运行验证（可以用 /workspace/venvs/ctrlnet/bin/python，已装 numpy、matplotlib、pytest；用 PYTHONPATH=/workspace/ctrlnet-design/src）：第 13 节结果必须为
   基准 C: σE 0.468 σN 1.651 mp 1.716 半轴 1.652/0.466 mm；D 同；增补 C: 0.464 1.225 1.310 1.231/0.448；D: 0.467 1.199 1.287 1.200/0.465。
   边 σs/相对精度 基准：AC 1.651 1:60565, BC 1.183 1:119522, AD 1.183 1:119522, BD 1.651 1:60565, CD 0.643 1:155427；增补：AC 1.225 1:81608, BC 0.849 1:166638, AD 0.886 1:159530, BD 1.199 1:83407, CD 0.638 1:156844。
   r_i 基准 [AC,BC,AD,BD,CD,∠CAB,∠ABD] = [0.3252,0.6569,0.6569,0.3252,0.8975,0.0692,0.0692]，合计 3；增补再加 ∠DCA 为 [0.6283,0.8235,0.8074,0.6442,0.8994,0.0842,0.0722,0.0408]，合计 4。基准 AC 的 MDB≈9.875 mm。
   如果不一致，找出并修正 bug，不要改期望值。
4. 代码注释和 docstring 可中英文混合，保持简洁、正确、无多余依赖。完成后简要列出写了哪些文件和验证输出。
