"""E7：同一时段相关 GNSS 基线与 LandXML 往返。"""
from pathlib import Path
import numpy as np
from ctrlnet import GnssPoint, GnssBaseline, GnssNetwork, GnssCovarianceBlock, solve_gnss
from ctrlnet.landxml import export_landxml, import_landxml


def main():
    out = Path(__file__).resolve().parents[1] / 'outputs'
    out.mkdir(exist_ok=True)
    a = GnssPoint('A', 39.9, 116, 100, fixed=True)
    b = GnssPoint('B', 39.901, 116.002, 110)
    c = GnssPoint('C', 39.902, 116.001, 120)
    pairs = [(a, b), (a, c), (b, c)]
    cov = np.eye(3)*.0001
    baselines = [GnssBaseline(p.name, q.name, q.ecef-p.ecef, cov) for p, q in pairs]
    q = np.kron(np.array([[1, .3, .1], [.3, 1, .2], [.1, .2, 1]]), cov)
    net = GnssNetwork([a, b, c], baselines, name='E7 GPS')
    independent = solve_gnss(net)
    net.covariance_blocks = [GnssCovarianceBlock([0, 1, 2], q, 'epoch-1')]
    correlated = solve_gnss(net)
    xml = export_landxml(net, out/'gnss_corr_landxml.xml')
    restored = solve_gnss(import_landxml(xml))
    np.testing.assert_allclose(restored.Cx, correlated.Cx, atol=1e-17)
    report = out/'gnss_corr_landxml_results.md'
    report.write_text('# E7 相关基线与 LandXML\n\n'
                      '3 条基线、9×9 VCV；固定 A；ECEF 米制；冗余 3。\n\n'
                      f'独立 VCV 参数协方差迹：{np.trace(independent.Cx):.12g} m²\n\n'
                      f'相关 VCV 参数协方差迹：{np.trace(correlated.Cx):.12g} m²\n\n'
                      f'LandXML 往返 Cx 最大误差：{np.max(np.abs(restored.Cx-correlated.Cx)):.3g} m²\n', encoding='utf-8')
    print(report.read_text())


if __name__ == '__main__':
    main()
