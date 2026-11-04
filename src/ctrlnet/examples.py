"""文档第 13 节的可复核边角网算例。"""

from __future__ import annotations

from .datum import FixedDatum
from .model import Angle, Distance, Network, Point, Scenario


def section13_base() -> Scenario:
    """第 13 节基准方案：A、B 固定，C、D 待定。"""
    points = [
        Point("A", 0.0, 0.0, fixed=True),
        Point("B", 100.0, 0.0, fixed=True),
        Point("C", 0.0, 100.0),
        Point("D", 100.0, 100.0),
    ]
    observations = [
        Distance("A", "C", a=0.002, b_ppm=2.0),
        Distance("B", "C", a=0.002, b_ppm=2.0),
        Distance("A", "D", a=0.002, b_ppm=2.0),
        Distance("B", "D", a=0.002, b_ppm=2.0),
        Distance("C", "D", a=0.002, b_ppm=2.0),
        Angle("C", "A", "B", sigma_arcsec=1.0),
        Angle("A", "B", "D", sigma_arcsec=1.0),
    ]
    network = Network(points, observations, name="第13节基准方案")
    return Scenario("第13节基准方案", network, datum=FixedDatum())


def section13_added() -> Scenario:
    """第 13 节增补方案：在基准方案上增加角 D-C-A。"""
    base = section13_base()
    extra = Angle("D", "C", "A", sigma_arcsec=1.0)
    network = base.network.with_observations([extra])
    network.name = "第13节增补方案"
    return Scenario("第13节增补方案", network, datum=FixedDatum())


__all__ = ["section13_base", "section13_added"]
