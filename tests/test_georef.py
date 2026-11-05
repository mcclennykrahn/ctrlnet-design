import numpy as np
import pytest
from ctrlnet.georef import fit, fit_tps
from ctrlnet.exceptions import RegistrationError


@pytest.mark.parametrize('degree', [2, 3])
def test_polynomial(degree):
    p = np.array([(x,y) for x in range(4) for y in range(4)], dtype=float)
    def truth(p):
        x,y=p.T
        return np.column_stack((100+2*x+.03*y**degree, 200+3*y+.02*x*x))
    check = np.array([[.4,.7], [1.8,2.2]])
    r = fit(np.column_stack((p,truth(p))), np.column_stack((check,truth(check))), degree=degree)
    assert r.rmse < 1e-10
    assert r.check_rmse < 1e-10
    np.testing.assert_allclose(r.inverse(truth(check)), check, atol=1e-7)
    noisy = truth(p); noisy[0,0] += 1
    r = fit(np.column_stack((p,noisy)), degree=degree)
    assert r.rmse > 0
    assert r.rmse == pytest.approx(np.sqrt(np.mean(np.sum(r.residuals**2, axis=1))))


def test_tps_exact_and_checks():
    p = np.array([(x,y) for x in range(3) for y in range(3)], dtype=float)
    q = p + .04*np.column_stack((np.sin(p[:,1]),np.cos(p[:,0])))
    r = fit_tps(np.column_stack((p,q)))
    np.testing.assert_allclose(r.transform(p), q, atol=1e-12)
    assert r.rmse < 1e-12
    check = np.array([[.2,.4],[1.2,1.5]])
    predicted = r.transform(check)
    np.testing.assert_allclose(r.inverse(predicted), check, atol=1e-7)
    r2 = fit_tps(np.column_stack((p,q)), np.column_stack((check,predicted+[.1,.2])))
    assert r2.check_rmse == pytest.approx(np.sqrt(.05))


@pytest.mark.parametrize('model,degree,n', [('polynomial',2,5),('polynomial',3,9),('tps',2,2)])
def test_insufficient(model,degree,n):
    with pytest.raises(RegistrationError):
        fit([(i,i,i,i) for i in range(n)], model=model, degree=degree)


@pytest.mark.parametrize('model', ['polynomial','tps'])
def test_degenerate(model):
    with pytest.raises(RegistrationError):
        fit([(i,i,i,i) for i in range(12)], model=model)
