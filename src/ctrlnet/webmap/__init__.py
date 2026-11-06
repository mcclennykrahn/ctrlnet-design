"""本地离线网页地图（FastAPI + Leaflet）与影像配准演示。"""

from __future__ import annotations

def __getattr__(name):
    # CLI help must work before optional dependencies and user data are available.
    from importlib import import_module
    if name in {"app", "build_profile", "create_app", "parse_endpoint"}:
        return getattr(import_module(".app", __name__), name)
    if name in {"ProjectStore", "default_project_path"}:
        return getattr(import_module(".state", __name__), name)
    raise AttributeError(name)

__all__ = [
    "app",
    "build_profile",
    "create_app",
    "parse_endpoint",
    "ProjectStore",
    "default_project_path",
]
