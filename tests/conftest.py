"""隔离旧网页集成测试的示例缓存写入：每个 pytest 进程使用独立副本。"""
import atexit
import os
from pathlib import Path
import shutil
import tempfile
from ctrlnet import store

_root = Path(__file__).resolve().parents[1]
_sample = _root / 'data/sample/demo_project.sqlite'
_temp = tempfile.TemporaryDirectory(prefix='ctrlnet-pytest-')
atexit.register(_temp.cleanup)
_copy = Path(_temp.name) / 'demo_project.sqlite'
shutil.copy2(_sample, _copy)
os.environ['CTRLNET_DB'] = str(_copy)
# 旧用例显式传入样例绝对路径；在唯一 SQLite 连接入口重定向写入。
_original_resolve = store._resolve_db_path

def _isolated_path(path):
    resolved = Path(path).expanduser().resolve()
    return _copy if resolved == _sample else _original_resolve(path)

store._resolve_db_path = _isolated_path
