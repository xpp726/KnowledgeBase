"""PDF 解析器（pymupdf4llm → Markdown，保留表格结构）。

选型理由：test_files 里 7 个招标 PDF 共 48 页、37 个表格，
中标候选人、报价、排名全在表格里。pymupdf4llm 能把表格直接转成
Markdown 表格语法，实测无需 OCR（全部为文字版 PDF）。

用 `page_chunks=True` 逐页返回，以便保留页码做引用溯源。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf4llm

from app.services.parsers.base import BaseParser, PageContent, ParsedDocument, clean_text

logger = logging.getLogger(__name__)


class PDFParser(BaseParser):
    extensions = {".pdf"}

    def parse(self, path: Path, doc_id: str) -> ParsedDocument:
        doc = self._make(path, doc_id, parser="pymupdf4llm")
        try:
            chunks = pymupdf4llm.to_markdown(str(path), page_chunks=True)
        except Exception as e:  # noqa: BLE001
            doc.error = f"{type(e).__name__}: {e}"
            logger.error("PDF 解析失败 %s: %s", path.name, e)
            return doc

        for i, chunk in enumerate(chunks):
            text = clean_text(chunk.get("text", ""))
            if not text:
                continue
            # metadata.page 是 0-based，转成从 1 开始的页码
            page_no = int(chunk.get("metadata", {}).get("page", i)) + 1
            doc.pages.append(PageContent(page=page_no, text=text))

        doc.meta["page_count"] = len(doc.pages)
        logger.info("PDF 解析完成 %s：%d 页", path.name, len(doc.pages))
        return doc
