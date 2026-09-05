"""临时探测：对 test_files 全部文档跑解析 + 分块，检查实际效果。"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.chunker import chunk_document  # noqa: E402
from app.services.parsers import parse_file  # noqa: E402

TEST_DIR = Path(__file__).resolve().parent.parent.parent / "test_files"

total_chunks = 0
total_tables = 0
kinds: Counter = Counter()
lengths: list[int] = []

for path in sorted(TEST_DIR.iterdir()):
    if path.suffix.lower() not in {".pdf", ".xlsx"}:
        continue
    doc = parse_file(path, doc_id=path.stem[:20])
    if not doc.ok:
        print(f"[FAIL] {path.name}: {doc.error}")
        continue
    chunks = chunk_document(doc)
    tables = [c for c in chunks if c.is_table]
    total_chunks += len(chunks)
    total_tables += len(tables)
    kinds[path.suffix] += 1
    lengths.extend(len(c.text) for c in chunks)
    print(f"\n=== {path.name}")
    print(f"  页数 {doc.page_count}，chunk {len(chunks)} 个（表格 {len(tables)} 个）")
    for c in chunks[:2]:
        flag = "表" if c.is_table else "文"
        head = f"[{c.heading_path}]" if c.heading_path else ""
        print(f"  ({flag}p{c.page}){head} {c.text[:80]}...")

print("\n" + "=" * 60)
print(f"文档 {sum(kinds.values())} 个，chunk 总数 {total_chunks}，其中表格块 {total_tables}")
if lengths:
    lengths.sort()
    print(f"chunk 长度：min {lengths[0]} / 中位 {lengths[len(lengths)//2]} / max {lengths[-1]}")
    print(f"超 512 字符的块：{sum(1 for n in lengths if n > 512)} 个")
