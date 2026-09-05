"""文档解析器工厂：按扩展名选择解析器。"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.parsers.base import BaseParser, PageContent, ParsedDocument, clean_text
from app.services.parsers.pdf import PDFParser
from app.services.parsers.xlsx import XLSXParser

logger = logging.getLogger(__name__)


class TextParser(BaseParser):
    """纯文本 / Markdown 解析器。"""

    extensions = {".txt", ".md", ".markdown"}

    def parse(self, path: Path, doc_id: str) -> ParsedDocument:
        doc = self._make(path, doc_id, parser="text")
        try:
            text = clean_text(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:  # noqa: BLE001
            doc.error = f"{type(e).__name__}: {e}"
            return doc
        if text:
            doc.pages.append(PageContent(page=1, text=text))
            doc.meta["page_count"] = 1
        return doc


_PARSERS: list[BaseParser] = [PDFParser(), XLSXParser(), TextParser()]

# 扩展名 → 解析器
_REGISTRY: dict[str, BaseParser] = {
    ext: parser for parser in _PARSERS for ext in parser.extensions
}


def supported_extensions() -> list[str]:
    return sorted(_REGISTRY)


def get_parser(path: Path | str) -> BaseParser | None:
    """按扩展名取解析器，不支持的类型返回 None。"""
    suffix = Path(path).suffix.lower()
    return _REGISTRY.get(suffix)


def parse_file(path: Path | str, doc_id: str) -> ParsedDocument:
    """解析单个文件。不支持的类型会返回带 error 的 ParsedDocument。"""
    path = Path(path)
    parser = get_parser(path)
    if parser is None:
        doc = ParsedDocument(doc_id=doc_id, file_name=path.name)
        doc.error = f"不支持的文件类型: {path.suffix}（当前支持 {supported_extensions()}）"
        logger.warning(doc.error)
        return doc
    return parser.parse(path, doc_id)
