"""非线性像素→平面配准；沿用 registration.ControlPoint 格式和异常。"""
from dataclasses import dataclass
import numpy as np
from .registration import ControlPoint, register_affine, _coerce_points
from .exceptions import RegistrationError


def _xy(values):
    a = np.asarray(values, dtype=float)
    if a.shape[-1:] != (2,) or not np.isfinite(a).all():
        raise RegistrationError('坐标须为有限的 (..., 2) 数组')
    return a


def _terms(p, degree):
    x, y = p.T
    return np.column_stack([x**(d-j)*y**j for d in range(degree+1) for j in range(d+1)])


def _kernel(p, centers):
    r2 = np.sum((p[:, None, :] - centers[None, :, :])**2, axis=2)
    return r2 * np.log(np.maximum(r2, np.finfo(float).tiny))


@dataclass
class GeorefResult:
    model: str
    degree: int
    origin: np.ndarray
    scale: float
    centers: np.ndarray
    coefficients: np.ndarray
    source: np.ndarray
    target: np.ndarray
    residuals: np.ndarray
    rmse: float
    check_errors: np.ndarray
    check_rmse: object

    def transform(self, points):
        a = _xy(points)
        p = (a.reshape(-1, 2)-self.origin)/self.scale
        design = _terms(p, self.degree) if self.model == 'polynomial' else np.column_stack((_kernel(p, self.centers), _terms(p, 1)))
        return (design @ self.coefficients).reshape(a.shape)

    def inverse(self, points, *, tolerance=1e-8, max_iterations=80):
        """局部 Newton 逆解；折叠映射可能多解，不保证全局唯一。"""
        a = _xy(points)
        targets = a.reshape(-1, 2)
        guess = np.column_stack((self.target, np.ones(len(self.target))))
        seed = np.linalg.lstsq(guess, self.source, rcond=None)[0]
        out = np.column_stack((targets, np.ones(len(targets)))) @ seed
        h = self.scale * 1e-5
        for i, target in enumerate(targets):
            for _ in range(max_iterations):
                error = self.transform(out[i])-target
                if np.linalg.norm(error) <= tolerance:
                    break
                jac = np.column_stack([(self.transform(out[i]+np.eye(2)[j]*h)-self.transform(out[i]-np.eye(2)[j]*h))/(2*h) for j in range(2)])
                try:
                    out[i] -= np.linalg.solve(jac, error)
                except np.linalg.LinAlgError as exc:
                    raise RegistrationError('逆变换 Jacobian 奇异') from exc
            else:
                raise RegistrationError('逆变换未收敛')
        return out.reshape(a.shape)


def fit(control_points, check_points=(), *, model='polynomial', degree=2):
    """二/三次多项式或精确 TPS；残差为预测减观测，RMSE 为二维距离 RMS。"""
    points = _coerce_points(control_points, name='控制点')
    checks = _coerce_points(check_points, name='检查点')
    if model not in ('polynomial', 'tps') or (model == 'polynomial' and degree not in (2, 3)):
        raise RegistrationError('仅支持二/三次 polynomial 或 tps')
    minimum = (degree+1)*(degree+2)//2 if model == 'polynomial' else 3
    if len(points) < minimum:
        raise RegistrationError(f'至少需要 {minimum} 个控制点')
    source = np.array([[p.col, p.row] for p in points])
    target = np.array([[p.E, p.N] for p in points])
    origin = source.mean(axis=0)
    scale = max(float(np.ptp(source, axis=0).max()), 1.)
    p = (source-origin)/scale
    if model == 'polynomial':
        design = _terms(p, degree)
        if np.linalg.matrix_rank(design) < minimum:
            raise RegistrationError('控制点布局退化')
        coefficients = np.linalg.lstsq(design, target, rcond=None)[0]
    else:
        poly = _terms(p, 1)
        system = np.block([[_kernel(p, p), poly], [poly.T, np.zeros((3, 3))]])
        if np.linalg.matrix_rank(system) < len(system):
            raise RegistrationError('TPS 控制点重复或共线')
        coefficients = np.linalg.solve(system, np.vstack((target, np.zeros((3, 2)))))
    result = GeorefResult(model, degree, origin, scale, p, coefficients, source, target, np.empty((0, 2)), 0., np.empty((0, 2)), None)
    result.residuals = result.transform(source)-target
    result.rmse = float(np.sqrt(np.mean(np.sum(result.residuals**2, axis=1))))
    if checks:
        result.check_errors = result.transform([[c.col, c.row] for c in checks])-np.array([[c.E, c.N] for c in checks])
        result.check_rmse = float(np.sqrt(np.mean(np.sum(result.check_errors**2, axis=1))))
    return result


def fit_polynomial(control_points, check_points=(), *, degree=2):
    return fit(control_points, check_points, degree=degree)


def fit_tps(control_points, check_points=()):
    return fit(control_points, check_points, model='tps')
