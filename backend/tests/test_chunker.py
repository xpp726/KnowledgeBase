"""chunker 分块策略单测（纯计算，不解析真实文件）。"""

from __future__ import annotations

from app.services.chunker import Chunk, chunk_document
from app.services.parsers.base import PageContent, ParsedDocument


def _doc(text: str, *, pages: int = 1, doc_id: str = "doc1", name: str = "a.txt") -> ParsedDocument:
    return ParsedDocument(
        doc_id=doc_id,
        file_name=name,
        pages=[PageContent(page=i + 1, text=text) for i in range(pages)],
    )


def test_short_text_single_chunk():
    text = "这是一段用于测试的普通正文内容，长度足够，不会被当作碎片丢弃。"
    chunks = chunk_document(_doc(text))
    assert len(chunks) == 1
    c = chunks[0]
    assert c.index == 0 and c.doc_id == "doc1" and c.doc_name == "a.txt"
    assert c.page == 1 and not c.is_table
    assert c.chunk_id and c.text in c.full_text


def test_long_text_hard_split_with_overlap():
    # 无标点、无换行的连续长串，走最后的硬切分支：size=100 overlap=20 -> step=80
    text = "字" * 500
    chunks = chunk_document(_doc(text), chunk_size=100, chunk_overlap=20, min_chunk_chars=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.text) <= 100
    # 相邻块必须有 overlap 个字符重叠衔接，保证上下文不丢
    assert chunks[0].text[-20:] == chunks[1].text[:20]
    # 去掉每块开头的重叠区后可无损还原原文（硬切无遗漏、无重复）
    reconstructed = chunks[0].text
    for c in chunks[1:]:
        reconstructed += c.text[20:]
    assert reconstructed == text


def test_table_kept_intact_when_short():
    table = "\n".join(
        [
            "| 包号 | 成交候选人 | 报价(万元) |",
            "|---|---|---|",
            "| 包1 | 甲公司 | 120.50 |",
            "| 包2 | 乙公司 | 98.00 |",
        ]
    )
    chunks = chunk_document(_doc(table), chunk_size=500)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.is_table
    assert "甲公司" in c.text and "乙公司" in c.text  # 短表格整体保留，不拆行


def test_long_table_repeats_header():
    header = ["| 包号 | 成交候选人及报价等详细信息 |", "|---|---|"]
    rows = [f"| 包{i:02d} | 第{i:02d}个候选单位的名称与成交金额内容 |" for i in range(12)]
    table = "\n".join(header + rows)
    chunks = chunk_document(_doc(table), chunk_size=120, chunk_overlap=20)
    table_chunks = [c for c in chunks if c.is_table]
    assert len(table_chunks) >= 2  # 超长表格被分组
    for c in table_chunks:
        first_line = c.text.splitlines()[0]
        assert first_line == header[0]  # 每组都重复表头，可独立理解


def test_short_fragment_dropped():
    # 短于 min_chunk_chars 的碎片被丢弃（向量化后只是噪声）
    chunks = chunk_document(_doc("短句"), min_chunk_chars=20)
    assert chunks == []


def test_heading_path_injected():
    text = "# 第一章 概述\n" + "这是第一章下的正文内容，需要带上所属标题路径用于检索。"
    chunks = chunk_document(_doc(text))
    assert len(chunks) == 1
    assert "第一章 概述" in chunks[0].heading_path
    assert chunks[0].full_text.startswith("【第一章 概述】")


def test_index_contiguous_and_stable_id():
    text = "字" * 400
    c1 = chunk_document(_doc(text), chunk_size=100, chunk_overlap=20)
    c2 = chunk_document(_doc(text), chunk_size=100, chunk_overlap=20)
    assert [c.index for c in c1] == list(range(len(c1)))  # index 连续
    assert [c.chunk_id for c in c1] == [c.chunk_id for c in c2]  # 同输入 id 稳定（幂等基础）
    assert len({c.chunk_id for c in c1}) == len(c1)  # id 互不重复


def test_empty_document():
    assert chunk_document(ParsedDocument(doc_id="x", file_name="x.txt")) == []
    assert chunk_document(_doc("   \n  ")) == []


def test_metadata_propagated_across_pages():
    doc = ParsedDocument(
        doc_id="d9",
        file_name="multi.txt",
        pages=[
            PageContent(page=1, text="这是第一页的正文内容，长度足够，不会被当作碎片给过滤掉。"),
            PageContent(page=2, text="这是第二页的正文内容，长度足够，不会被当作碎片给过滤掉。"),
        ],
    )
    chunks = chunk_document(doc)
    pages = sorted({c.page for c in chunks})
    assert pages == [1, 2]
    assert all(c.doc_id == "d9" and c.doc_name == "multi.txt" for c in chunks)
    assert all(isinstance(c, Chunk) for c in chunks)
