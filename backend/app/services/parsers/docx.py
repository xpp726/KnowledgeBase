"""DOCX 解析器（python-docx → Markdown）。

抽取范围（2026-09-08 用户确认）：
- 段落（含 Normal 文本、列表）
- 标题层级（Heading 1/2/3）→ Markdown `# ## ###` 语法，
  让现有 chunker 的 _RE_HEADING_MD 直接识别，自动注入 heading_path
- 表格 → Markdown 表格语法（与 xlsx 解析器一致，chunker 表格优先路径生效）
- 内嵌图片 → RapidOCR 兜底（与 PDF 扫描件路径一致）

DOCX 无物理页概念：所有内容合并到 page=1 的 PageContent（chunk_document 不依赖物理页），
但 chunks 仍会带 page=1 标签便于统一日志/溯源。

不在范围：
- 页眉页脚（招标文件一般无关）
- 脚注/尾注
- 文本框（textbox）/形状（shape）内的非图片内容
"""

from __future__ import annotations

import logging
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from app.config import get_settings
from app.services.ocr import get_load_error, ocr_pixmap_bytes
from app.services.parsers.base import BaseParser, PageContent, ParsedDocument, clean_text

logger = logging.getLogger(__name__)
settings = get_settings()


# Heading 1/2/3 → Markdown 标题层级映射
# python-docx 用 style.name 标识，ppt 用户常用别名
_HEADING_ALIASES = {
    "Heading 1": 1, "heading 1": 1, "标题 1": 1, "标题1": 1,
    "Heading 2": 2, "heading 2": 2, "标题 2": 2, "标题2": 2,
    "Heading 3": 3, "heading 3": 3, "标题 3": 3, "标题3": 3,
}


def _is_heading_style(style_name: str) -> int | None:
    """返回标题层级（1/2/3），非标题返回 None。"""
    return _HEADING_ALIASES.get(style_name)


def _heading_markdown(level: int, text: str) -> str:
    """Heading 1 → '# text'，让 chunker._RE_HEADING_MD 识别。"""
    return f"{'#' * level} {text}"


def _table_to_markdown(table) -> str:
    """python-docx Table → Markdown 表格语法（与 xlsx 解析器一致）。

    单元格内换行转空格，竖线转义，避免破坏 Markdown 表格结构。
    """
    rows_data: list[list[str]] = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            text = cell.text or ""
            # 单元格内换行会截断 Markdown 表格行 → 用空格合并
            text = " ".join(text.split())
            text = text.replace("|", "\\|")
            cells.append(text)
        rows_data.append(cells)

    # 跳全空行
    rows_data = [r for r in rows_data if any(c for c in r)]
    if not rows_data:
        return ""

    # 统一列数
    width = max(len(r) for r in rows_data)
    for r in rows_data:
        r.extend([""] * (width - len(r)))

    header = rows_data[0]
    lines = ["|" + "|".join(header) + "|", "|" + "|".join(["---"] * width) + "|"]
    for r in rows_data[1:]:
        lines.append("|" + "|".join(r) + "|")
    return "\n".join(lines)


def _list_paragraphs(body) -> str:
    """渲染列表块为 Markdown 短行，便于 chunker 识别。

    python-docx 不暴露列表 API，需要看段落 style.name 是否以 'List' 开头，
    或 numId 属性。我们这里简单按 List Paragraph / List Bullet / List Number 判定。
    """
    return ""  # 当前实现里列表被 _emit_block 单独处理，这里只是占位


class DocxParser(BaseParser):
    extensions = {".docx"}

    def parse(self, path: Path, doc_id: str) -> ParsedDocument:
        doc = self._make(path, doc_id, parser="python-docx")
        try:
            document = Document(str(path))
        except Exception as e:  # noqa: BLE001
            doc.error = f"{type(e).__name__}: {e}"
            logger.error("DOCX 解析失败 %s: %s", path.name, e)
            return doc

        # 顶层 body 顺序遍历：document.paragraphs 只含 body，document.tables 只含 body 顶层表格。
        # 真实顺序需要从 document.element.body 走 XML。
        body_children = list(document.element.body.iterchildren())
        lines: list[str] = []
        image_count = 0

        for child in body_children:
            tag = child.tag
            if tag == qn("w:p"):
                # 段落：找到对应的 docx.text.Paragraph 对象
                p = next((p for p in document.paragraphs if p._element is child), None)
                if p is None:
                    continue
                style_name = p.style.name if p.style else ""
                text = p.text
                if not text and not p.runs:
                    # 空行：用于段落分隔
                    lines.append("")
                    continue
                level = _is_heading_style(style_name)
                if level:
                    lines.append(_heading_markdown(level, text))
                else:
                    lines.append(text)
                # 段落里可能含图片
                if settings.pdf_ocr_enabled and _paragraph_has_image(p):
                    ocr_text = _ocr_paragraph_images(p)
                    if ocr_text:
                        lines.append(f"\n[图片OCR]\n{ocr_text}")
                        image_count += 1
            elif tag == qn("w:tbl"):
                # 顶层表格：找到 docx.table.Table 对象
                tbl = next((t for t in document.tables if t._element is child), None)
                if tbl is None:
                    continue
                md = _table_to_markdown(tbl)
                if md:
                    lines.append("")
                    lines.append(md)
                    lines.append("")

        merged_text = clean_text("\n".join(lines))
        if merged_text:
            doc.pages.append(PageContent(page=1, text=merged_text))
        doc.meta["page_count"] = len(doc.pages)
        doc.meta["image_count"] = image_count
        logger.info(
            "DOCX 解析完成 %s：%d 段 + %d 顶层表（图片 OCR %d）",
            path.name, len(document.paragraphs), len(document.tables), image_count,
        )
        return doc


def _paragraph_has_image(p) -> bool:
    """段落里是否有内嵌图片（drawing/blip 引用）。"""
    return bool(p._element.findall(".//" + qn("w:drawing")))


def _ocr_paragraph_images(p) -> str:
    """抽取段落里的所有图片，跑 OCR，返回拼接文本。失败返回空串。"""
    if get_load_error() is not None:
        return ""
    drawings = p._element.findall(".//" + qn("w:drawing"))
    if not drawings:
        return ""
    parts: list[str] = []
    for drawing in drawings:
        # 找 blip 引用关系
        blips = drawing.findall(".//" + "{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
        for blip in blips:
            rId = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
            if not rId:
                continue
            try:
                from docx.opc.constants import RELATIONSHIP_TYPE as RT

                rel = p.part.rels[rId]
                if rel.reltype != RT.IMAGE:
                    continue
                blob = rel.target_part.blob
                text = ocr_pixmap_bytes(blob)
                if text:
                    parts.append(text)
            except Exception as e:  # noqa: BLE001
                logger.warning("DOCX 内嵌图片读取失败：%s", e)
                continue
    return "\n\n".join(parts)