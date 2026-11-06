"""E9：独立求积、短边公式、反向边与可选观测归算。"""
import math
from dataclasses import replace

import numpy as np
import pytest
from geographiclib.geodesic import Geodesic
from scipy.integrate import quad

from ctrlnet.projection import (
    ProjectionSpec, ProjectionReductionOptions, edge_reduction,
    local_curvature_radius, reduce_observation_dataset,
)
from ctrlnet.model import Point, Network, Distance, Direction, Angle, GnssBaseline2D
from ctrlnet.robust import simulate_observations, estimate_network


@pytest.mark.parametrize('k0,lat,lon', [(1, 40, 117.8), (.9996, -35, 116), (1, 60, 118)])
def test_simpson_against_quad_and_projected_endpoints(k0, lat, lon):
    spec = ProjectionSpec(central_meridian=117, scale_factor=k0)
    end = (lat + .4, lon + .3)
    result = edge_reduction(lat, lon, *end, spec=spec, height1_m=200, height2_m=800)
    ell = spec.ellipsoid_model
    line = Geodesic(ell.a, ell.f).InverseLine(lat, lon, *end)
    def scale(s):
        p = line.Position(s)
        return spec.scale(p['lat2'], p['lon2'])
    arc = quad(scale, 0, line.s13, epsabs=1e-7)[0]
    def ground(s):
        p = line.Position(s)
        return 1 + (200 + 600 * s / line.s13) / local_curvature_radius(p['lat2'], ell)
    assert result.grid_arc_m == pytest.approx(arc, abs=1e-7)
    assert result.ground_distance_m == pytest.approx(quad(ground, 0, line.s13)[0], abs=1e-7)
    e1, n1 = spec.forward(lat, lon)
    e2, n2 = spec.forward(*end)
    chord = math.hypot(e2-e1, n2-n1)
    assert result.grid_chord_m == pytest.approx(chord, abs=2e-7)
    tangent = math.radians(line.azi1) - spec.convergence(lat, lon, unit='rad')
    delta = (math.atan2(e2-e1, n2-n1) - tangent + math.pi) % (2*math.pi) - math.pi
    assert result.delta_rad == pytest.approx(delta, abs=2e-11)
    reverse = edge_reduction(*end, lat, lon, spec=spec, height1_m=800, height2_m=200)
    assert reverse.combined_scale == pytest.approx(result.combined_scale, abs=1e-13)
    assert reverse.delta_rad * result.delta_rad < 0
    assert result.grid_arc_m > result.grid_chord_m


def test_known_short_edge_formula_and_central_meridian():
    spec = ProjectionSpec(central_meridian=117)
    r = edge_reduction(40, 117.5, 40.01, 117.51, spec=spec)
    e1,n1 = spec.forward(40,117.5)
    e2,n2 = spec.forward(40.01,117.51)
    y1,y2 = e1-500000,e2-500000
    radius = local_curvature_radius(40.005)
    # 高斯短边：δ12 ≈ −ΔN(2y1+y2)/(6R²)，m ≈ 1+(y1²+y1y2+y2²)/(6R²)。
    assert r.delta_rad == pytest.approx(-(n2-n1)*(2*y1+y2)/(6*radius**2), rel=2e-5)
    assert r.projection_scale == pytest.approx(1+(y1*y1+y1*y2+y2*y2)/(6*radius**2), abs=2e-9)
    central = edge_reduction(39,117,40,117,spec=spec,height1_m=500,height2_m=500)
    assert central.projection_scale == pytest.approx(1, abs=1e-14)
    assert central.delta_rad == pytest.approx(0, abs=1e-14)
    assert central.combined_scale < 1
    assert central.distance_correction(1000) == pytest.approx(1000*(central.combined_scale-1))


@pytest.mark.parametrize('kwargs', [{'intervals':1}, {'intervals':3}, {'intervals':2.0},
    {'intervals':True}, {'height1_m':float('nan')}, {'height1_m':-1e8}])
def test_validation(kwargs):
    with pytest.raises(ValueError):
        edge_reduction(40,117,40.1,117.1,spec=ProjectionSpec(central_meridian=117),**kwargs)


def test_invalid_geometry():
    with pytest.raises(ValueError, match='central_meridian'):
        edge_reduction(40,117,40.1,117.1,spec=ProjectionSpec())
    with pytest.raises(ValueError, match='重合'):
        edge_reduction(40,117,40,117,spec=ProjectionSpec(central_meridian=117))


def test_estimation_opt_in_and_covariance():
    spec = ProjectionSpec(central_meridian=117)
    coords = [(40,117.5),(40.02,117.5),(40.01,117.52)]
    points = [Point(name,*spec.forward(*ll),fixed=name!='C') for name,ll in zip('ABC',coords)]
    obs = [Distance('A','C'),Distance('B','C'),Direction('A','B'),Direction('A','C'),Angle('A','C','B'),
           GnssBaseline2D('A','C',sigma_E=.01,sigma_N=.01)]
    net = Network(points,obs)
    grid = simulate_observations(net,noise=False)
    options = ProjectionReductionOptions(spec, dict.fromkeys('ABC',500))
    # 用独立的端点投影/测地线公式构造地面观测，不依赖待测预处理的逆变换。
    ell = spec.ellipsoid_model
    geo = Geodesic(ell.a,ell.f)
    def az(a,b):
        return math.radians(geo.Inverse(*coords['ABC'.index(a)],*coords['ABC'.index(b)])['azi1'])
    records = []
    for rec in grid.records:
        o = rec.observation
        if isinstance(o,Distance):
            r = edge_reduction(*coords['ABC'.index(o.frm)],*coords['ABC'.index(o.to)],spec=spec,height1_m=500,height2_m=500)
            value = r.ground_distance_m
        elif isinstance(o,Direction):
            value = az(o.station,o.target)
        elif isinstance(o,Angle):
            value = az(o.station,o.foresight)-az(o.station,o.backsight)
        else:
            records.append(rec)
            continue
        records.append(replace(rec,values=np.array([value]),truth=np.array([value])))
    raw = replace(grid,records=records)
    reduced = reduce_observation_dataset(raw,options)
    for a,b in zip(reduced.records,grid.records):
        np.testing.assert_allclose(a.values % (2*math.pi) if a.kind in ('direction','angle') else a.values,
                                   b.values, atol=2e-7,rtol=0)
    baseline = estimate_network(grid)
    default = estimate_network(grid,projection_reduction=None)
    np.testing.assert_array_equal(default.Cx,baseline.Cx)
    result = estimate_network(raw,projection_reduction=options)
    assert result.converged
    np.testing.assert_allclose(result.coordinate('C'),(points[2].E,points[2].N),atol=2e-7,rtol=0)
    assert result.dataset.metadata['projection_reduced']
    assert result.Ql[0,0] == pytest.approx(reduced.records[0].sigma[0]**2)
    assert raw.metadata == grid.metadata
    with pytest.raises(ValueError,match='重复'):
        reduce_observation_dataset(reduced,options)
    with pytest.raises(KeyError):
        reduce_observation_dataset(raw,ProjectionReductionOptions(spec,{}))


def test_simpson_fourth_order_convergence_and_false_origin_invariance():
    spec = ProjectionSpec(central_meridian=117)
    args = (30,119,35,121)
    reference = edge_reduction(*args,spec=spec,intervals=128)
    coarse = edge_reduction(*args,spec=spec,intervals=2)
    fine = edge_reduction(*args,spec=spec,intervals=4)
    assert abs(fine.grid_arc_m-reference.grid_arc_m) < abs(coarse.grid_arc_m-reference.grid_arc_m)/15
    assert abs(fine.grid_chord_m-reference.grid_chord_m) < abs(coarse.grid_chord_m-reference.grid_chord_m)/15
    shifted = edge_reduction(*args,spec=replace(spec,false_easting=39_500_000,false_northing=10_000_000),intervals=128)
    assert shifted == reference
