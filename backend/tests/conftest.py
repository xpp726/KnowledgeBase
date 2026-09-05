"""pytest 公共夹具与路径准备。

把 backend 根目录加入 sys.path，保证在任意工作目录执行 pytest 都能 import app；
测试全部使用 tests/fakes.py 的替身，不连接真实 BGE-M3 / Milvus / LLM / DB，离线可重复。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
