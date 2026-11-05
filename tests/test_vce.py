import numpy as np
import pytest

from ctrlnet.vce import estimate, VCEError, VCEConvergenceError


def sample():
    rng = np.random.default_rng(317)
    groups = {}
    for name, variance in [('gnss', 1.), ('ground', 9.)]:
        a = rng.normal(size=(2000, 3))
        groups[name] = (a, np.ones(2000), a @ np.array([2., -1., 3.]) + rng.normal(size=2000) * np.sqrt(variance))
    return groups


def test_variance_ratio():
    result = estimate(sample())
    assert result.variance_factors['ground'] / result.variance_factors['gnss'] == pytest.approx(9, rel=.12)
    assert result.precision_summary['sigma0_sq'] == pytest.approx(1, abs=1e-7)
    assert result.history[-1]['relative_change'] <= 1e-7
    assert np.all(np.linalg.eigvalsh(result.covariance) > 0)


def test_single_group():
    a, p, l = sample()['gnss']
    x = np.linalg.lstsq(a, l, rcond=None)[0]
    expected = np.sum((l - a @ x)**2) / (len(l) - a.shape[1])
    result = estimate({'only': (a, p, l)})
    assert result.variance_factors['only'] == pytest.approx(expected)
    np.testing.assert_allclose(result.covariance, expected * np.linalg.inv(a.T @ a))


def test_singular_and_nonconvergence():
    with pytest.raises(VCEError, match='奇异'):
        estimate({'a': (np.ones((8, 2)), np.ones(8), np.arange(8))})
    with pytest.raises(VCEError, match='奇异'):
        estimate({'a': (np.eye(2), np.ones(2), np.ones(2))})
    with pytest.raises(VCEConvergenceError, match='未收敛'):
        estimate(sample(), max_iterations=1)


def test_correlated_weights_and_bridge():
    from types import SimpleNamespace
    from ctrlnet.vce import estimate_gnss_ground
    rng = np.random.default_rng(18)
    a = rng.normal(size=(80, 2))
    c = np.eye(40) + .2 * np.ones((40, 40))
    covariance = np.zeros((80, 80))
    covariance[:40, :40] = c
    covariance[40:, 40:] = c
    l = np.concatenate([np.linalg.cholesky(c) @ rng.normal(size=40),
                        3 * np.linalg.cholesky(c) @ rng.normal(size=40)])
    blocks = [SimpleNamespace(kind=k, rows=list(range(start, start+40)))
              for k, start in [('gnss', 0), ('distance', 40)]]
    adjustment = SimpleNamespace(design=SimpleNamespace(A=a, Ql=covariance, blocks=blocks))
    result = estimate_gnss_ground(adjustment, l)
    for name, start in [('gnss', 0), ('ground', 40)]:
        sl = slice(start, start+40)
        np.testing.assert_allclose(result.updated_weights[name], np.linalg.inv(c) / result.variance_factors[name])
        np.testing.assert_allclose(result.residuals[name], l[sl] - a[sl] @ result.parameters)
    assert result.precision_summary['sigma0_sq'] == pytest.approx(1, abs=1e-7)
    blocks[1].kind = 'angle'
    with pytest.raises(ValueError, match='仅支持'):
        estimate_gnss_ground(adjustment, l)


@pytest.mark.parametrize('weight', [np.array([1., -1., 1.]), np.array([1., np.nan, 1.])])
def test_invalid_weights(weight):
    with pytest.raises(ValueError):
        estimate({'bad': (np.ones((3, 1)), weight, np.arange(3.))})
