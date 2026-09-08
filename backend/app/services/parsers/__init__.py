"""文档解析器工厂：按扩展名选择解析器。"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.parsers.base import BaseParser, PageContent, ParsedDocument, clean_text
from app.services.parsers.docx import DocxParser
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


class UnsupportedFormatParser(BaseParser):
    """返回明确错误：当前格式未支持。

    用于 .doc（老二进制）：用户已确认暂不支持，要求转 docx 后重传。
    不在此处直接拒绝（让 parse_file 走 unsupported_extensions 路径），
    仅当需要定制错误信息时使用。
    """

    extensions: set[str] = set()

    def parse(self, path: Path, doc_id: str) -> ParsedDocument:
        doc = ParsedDocument(doc_id=doc_id, file_name=path.name)
        doc.error = (
            f"暂不支持 {path.suffix} 格式：基于 LibreOffice 未装 / D 盘空间考虑，"
            "请在 Microsoft Word 或 WPS 中另存为 .docx 后重传"
        )
        return doc


_PARSERS: list[BaseParser] = [PDFParser(), DocxParser(), XLSXParser(), TextParser()]

# 扩展名 → 解析器
_REGISTRY: dict[str, BaseParser] = {
    ext: parser for parser in _PARSERS for ext in parser.extensions
}

# 显式拒绝的扩展名（给出明确错误信息，而非"不支持该类型"）
_REJECTED: dict[str, str] = {
    ".doc": (
        "暂不支持 .doc 格式：基于 LibreOffice 未装 / D 盘空间考虑，"
        "请在 Microsoft Word 或 WPS 中另存为 .docx 后重传"
    ),
}


def supported_extensions() -> list[str]:
    return sorted(_REGISTRY)


def rejected_extensions() -> dict[str, str]:
    """返回被显式拒绝的后缀 → 错误信息（用于前端提示）。"""
    return dict(_REJECTED)


def get_parser(path: Path | str) -> BaseParser | None:
    """按扩展名取解析器，不支持的类型返回 None。"""
    suffix = Path(path).suffix.lower()
    return _REGISTRY.get(suffix)


def parse_file(path: Path | str, doc_id: str) -> ParsedDocument:
    """解析单个文件。不支持的类型会返回带 error 的 ParsedDocument。"""
    path = Path(path)
    suffix = path.suffix.lower()
    # 显式拒绝的格式优先：返回定制错误信息
    if suffix in _REJECTED:
        doc = ParsedDocument(doc_id=doc_id, file_name=path.name)
        doc.error = _REJECTED[suffix]
        logger.warning("拒绝上传 %s: %s", path.name, doc.error)
        return doc
    parser = get_parser(path)
    if parser is None:
        doc = ParsedDocument(doc_id=doc_id, file_name=path.name)
        doc.error = f"不支持的文件类型: {path.suffix}（当前支持 {supported_extensions()}）"
        logger.warning(doc.error)
        return doc
    return parser.parse(path, doc_id)
