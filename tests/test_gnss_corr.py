import numpy as np
import pytest
from ctrlnet import GnssCovarianceBlock, solve_gnss
from ctrlnet.exceptions import InvalidPrecisionError
from test_gnss import _two_baseline_network


def correlated_network(frame='ECEF'):
    net, q1, q2 = _two_baseline_network()
    for b in net.baselines:
        b.frame = frame
    q = np.zeros((6, 6))
    q[:3, :3], q[3:, 3:] = q1, q2
    q[:3, 3:] = np.eye(3) * 1e-4
    q[3:, :3] = q[:3, 3:].T
    net.covariance_blocks = [GnssCovarianceBlock([0, 1], q, 'epoch1')]
    return net, q


@pytest.mark.parametrize('frame', ['ECEF', 'ENU'])
def test_full_covariance_analytic(frame):
    from ctrlnet import ecef_to_enu_matrix
    net, q = correlated_network(frame)
    t = np.eye(6)
    if frame == 'ENU':
        for j, b in enumerate(net.baselines):
            p = net.point(b.reference)
            t[j*3:j*3+3, j*3:j*3+3] = ecef_to_enu_matrix(p.lat, p.lon).T
    q = t @ q @ t.T
    result = solve_gnss(net)
    a = result.design.A
    np.testing.assert_allclose(result.design.Ql, q, atol=1e-18)
    np.testing.assert_allclose(result.Cx, np.linalg.inv(a.T @ np.linalg.solve(q, a)), atol=1e-17)


def test_zero_cross_terms_exact_compatibility():
    net, q1, q2 = _two_baseline_network()
    old = solve_gnss(net)
    q = old.design.Ql.copy()
    net.covariance_blocks = [GnssCovarianceBlock([0, 1], q)]
    new = solve_gnss(net)
    np.testing.assert_array_equal(old.Cx, new.Cx)
    np.testing.assert_array_equal(old.design.Ql, new.design.Ql)
    assert net.with_geoid(object()).covariance_blocks == net.covariance_blocks


@pytest.mark.parametrize('q', [np.eye(5), np.zeros((6, 6)), np.eye(6)*np.nan,
                               np.eye(6)+np.triu(np.ones((6, 6)), 1)])
def test_invalid_covariance(q):
    with pytest.raises(InvalidPrecisionError):
        GnssCovarianceBlock([0, 1], q)


def test_invalid_indices_and_diagonals():
    net, q = correlated_network()
    for indices in ([0, 0], [-1], []):
        with pytest.raises(ValueError):
            GnssCovarianceBlock(indices, q)
    net.covariance_blocks *= 2
    with pytest.raises(ValueError):
        solve_gnss(net)
    net.covariance_blocks = [GnssCovarianceBlock([0, 2], q)]
    with pytest.raises(ValueError):
        solve_gnss(net)
    net.covariance_blocks = [GnssCovarianceBlock([0, 1], q*2)]
    with pytest.raises(InvalidPrecisionError):
        solve_gnss(net)


def test_redundant_joint_block_weight():
    from ctrlnet import GnssBaseline, Distance
    net, q = correlated_network()
    a, b, c = net.points
    net.baselines.append(GnssBaseline('A', 'C', c.ecef-a.ecef, np.eye(3)*.0002))
    net.distances.append(Distance('A', 'B'))
    result = solve_gnss(net)
    design = result.design
    expected = np.linalg.inv(design.A.T @ np.linalg.solve(design.Ql, design.A))
    np.testing.assert_allclose(result.Cx, expected, rtol=1e-12, atol=1e-17)
    assert np.count_nonzero(design.Ql[:6, 6:]) == 0
    net.covariance_blocks = []
    assert not np.allclose(result.Cx, solve_gnss(net).Cx, rtol=1e-6, atol=1e-12)
