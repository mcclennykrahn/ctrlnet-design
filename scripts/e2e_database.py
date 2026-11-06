"""Chromium 回归使用进程独立 SQLite 与只读样例资源链接。"""
import atexit
import os
from pathlib import Path
import shutil
import tempfile


def isolated_environment():
    root = Path(__file__).resolve().parents[1]
    temp = tempfile.TemporaryDirectory(prefix='ctrlnet-e2e-')
    atexit.register(temp.cleanup)
    folder = Path(temp.name)
    shutil.copy2(root/'data/sample/demo_project.sqlite', folder/'demo_project.sqlite')
    for resource in (root/'data/sample').iterdir():
        if resource.suffix not in ('.sqlite', '.db'):
            (folder/resource.name).symlink_to(resource)
    return dict(os.environ, CTRLNET_DB=str(folder/'demo_project.sqlite'),
                CTRLNET_THESIS_DB=str(folder/'engineering.sqlite'))
