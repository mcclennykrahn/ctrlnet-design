"""Helmert 小角七参数核心验证。"""

import numpy as np
import pytest

from ctrlnet.helmert import estimate, forward, inverse


PARAMS = np.array([1.2, -2.3, 0.7, 2e-6, -3e-6, 4e-6, 1.5])


def points():
    return np.random.default_rng(42).normal(size=(40, 3)) * 1e5


def test_exact_recovery():
    src = points()
    result = estimate(src, forward(src, PARAMS))
    np.testing.assert_allclose(result.params, PARAMS, atol=1e-10, rtol=1e-9)
    np.testing.assert_allclose(result.residuals, 0, atol=1e-10)
    assert result.sigma0_sq < 1e-20


def test_rotation_convention():
    params = [1, 2, 3, 0, 0, 1e-3, 2]
    np.testing.assert_allclose(forward([[1000, 0, 0]], params), [[1001.002, 3, 3]])


def test_noisy_estimate_and_covariance():
    src = points()
    rng = np.random.default_rng(7)
    sigmas = np.linspace(0.001, 0.01, len(src))
    dst = forward(src, PARAMS) + rng.normal(size=src.shape) * sigmas[:, None]
    result = estimate(src, dst, weights=1 / sigmas**2)
    errors = np.abs(result.params - PARAMS)
    assert np.all(errors < 4 * np.sqrt(np.diag(result.covariance)))
    np.testing.assert_allclose(result.covariance, result.covariance.T, atol=1e-20)
    np.linalg.cholesky(result.covariance)
    assert 0.5 < result.sigma0_sq < 1.5
    np.testing.assert_allclose(result.residuals, dst - forward(src, result.params))
    component = estimate(src, dst, np.repeat((1 / sigmas**2)[:, None], 3, axis=1))
    np.testing.assert_allclose(component.params, result.params)


def test_round_trip():
    src = points()
    np.testing.assert_allclose(inverse(forward(src, PARAMS), PARAMS), src, atol=1e-9)
    np.testing.assert_allclose(forward(inverse(src, PARAMS), PARAMS), src, atol=1e-9)


def test_three_noncollinear_points():
    src = points()[:3]
    np.testing.assert_allclose(estimate(src, forward(src, PARAMS)).params, PARAMS, atol=1e-8)


@pytest.mark.parametrize('n', [0, 1, 2])
def test_insufficient_points(n):
    with pytest.raises(ValueError, match='3'):
        estimate(np.zeros((n, 3)), np.zeros((n, 3)))


def test_degenerate_points():
    src = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]])
    with pytest.raises(ValueError, match='退化'):
        estimate(src, src)


@pytest.mark.parametrize('weights', [[1, -1, 1], [1, np.nan, 1], [1, 2]])
def test_invalid_weights(weights):
    src = points()[:3]
    with pytest.raises(ValueError, match='weights'):
        estimate(src, src, weights)
