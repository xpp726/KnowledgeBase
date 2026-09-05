"""临时探测：看 pymupdf4llm 解析真实招标 PDF 的实际效果。

目的：确认表格能否转成 Markdown、单元格碎片换行有多严重，
以便设计清洗规则与分块策略。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf4llm

TEST_DIR = Path(__file__).resolve().parent.parent.parent / "test_files"

files = sorted(TEST_DIR.glob("*.pdf"))
if not files:
    print("未找到 PDF")
    sys.exit(1)

pdf = files[0]
print(f"文件: {pdf.name}")
print("=" * 70)

md = pymupdf4llm.to_markdown(str(pdf))

print(f"总字符数: {len(md)}")
print(f"表格分隔行数: {md.count('|---')}")
print(f"总行数: {md.count(chr(10))}")
print("=" * 70)

# 找第一个表格所在位置，打印上下文
idx = md.find("|---")
if idx > 0:
    start = max(0, idx - 1200)
    print("【第一个表格前后 2500 字符】")
    print(md[start : idx + 1300])
