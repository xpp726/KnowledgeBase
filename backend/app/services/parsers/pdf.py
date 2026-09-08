"""PDF 解析器（pymupdf4llm → Markdown，保留表格结构 + OCR 兜底扫描件）。

选型理由：test_files 里 7 个招标 PDF 共 48 页、37 个表格，
中标候选人、报价、排名全在表格里。pymupdf4llm 能把表格直接转成
Markdown 表格语法。

扫描件兜底（2026-09-08）：
- 早期假设"实测无需 OCR"——7 个文字型 PDF 没问题；
- 遇到 `专项成本科技项目任务书（监控机器人）.pdf`（19 页扫描件）崩溃：
  pymupdf.get_text() 空、pymupdf4llm 返回空文本 → 报"0 页"。
- 解法：pymupdf4llm 跑完后，再用 pymupdf 直开逐页检查，
  该页仍空且含图像时调 RapidOCR（ONNX Runtime 后端）抽文本。
- 这是"双轨 + 兜底"模式，混合文档（部分文字部分扫描）也能正确处理。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf
import pymupdf4llm

from app.config import get_settings
from app.services.ocr import get_load_error, ocr_pixmap_bytes
from app.services.parsers.base import BaseParser, PageContent, ParsedDocument, clean_text

logger = logging.getLogger(__name__)
settings = get_settings()


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

        # 1) pymupdf4llm 主路径：文字型 PDF 保留表格
        for i, chunk in enumerate(chunks):
            text = clean_text(chunk.get("text", ""))
            if not text:
                continue
            # metadata.page 字段名不固定，page_chunks 模式下实测不可靠，
            # 用 chunk 在列表中的索引 + 1 兜底（顺序与页码对齐）
            page_no = int(chunk.get("metadata", {}).get("page", i)) + 1
            doc.pages.append(PageContent(page=page_no, text=text))

        # 2) OCR 兜底：对 pymupdf4llm 没抽到文本的页补 OCR
        # pymupdf 直开逐页判断，比 page_chunks 模式更可靠
        if settings.pdf_ocr_enabled and len(doc.pages) < self._expected_page_count(path):
            self._fill_missing_with_ocr(path, doc)

        # 3) 按页码排序，确保下游 chunker 按页顺序处理
        doc.pages.sort(key=lambda p: p.page)
        doc.meta["page_count"] = len(doc.pages)
        logger.info("PDF 解析完成 %s：%d 页", path.name, len(doc.pages))
        return doc

    @staticmethod
    def _expected_page_count(path: Path) -> int:
        """从 pymupdf 读真实页数。pymupdf4llm page_chunks 在扫描件上可能返回 0。"""
        try:
            with pymupdf.open(str(path)) as pdf:
                return pdf.page_count
        except Exception:
            return 0

    def _fill_missing_with_ocr(self, path: Path, doc: ParsedDocument) -> None:
        """对 pymupdf4llm 没覆盖的页（扫描件/混合文档）尝试 pymupdf 抽文本，仍空则调 OCR。"""
        have_pages = {p.page for p in doc.pages}
        ocr_used = False
        try:
            with pymupdf.open(str(path)) as pdf:
                for i in range(pdf.page_count):
                    page_no = i + 1
                    if page_no in have_pages:
                        continue
                    page = pdf[i]
                    # 先试 pymupdf 直抽（覆盖 pymupdf4llm 没识别的文字页）
                    text = clean_text(page.get_text())
                    if text:
                        doc.pages.append(PageContent(page=page_no, text=text))
                        have_pages.add(page_no)
                        continue
                    # 仍空 → OCR
                    text = self._ocr_page(page, page_no)
                    if text:
                        doc.pages.append(PageContent(page=page_no, text=text))
                        have_pages.add(page_no)
                        ocr_used = True
        except Exception as e:  # noqa: BLE001  OCR 兜底阶段异常不影响主路径已抽到的页
            logger.warning("OCR 兜底阶段异常 %s：%s", path.name, e)
        if ocr_used:
            logger.info(
                "PDF %s 走 OCR 兜底补页：最终 %d 页",
                path.name, len(doc.pages),
            )

    @staticmethod
    def _ocr_page(page, page_no: int) -> str:
        """单页 OCR：渲染为 PNG 后调用 RapidOCR。失败返回空串。"""
        load_err = get_load_error()
        if load_err is not None:
            # 启动期就加载失败 → 跳过所有 OCR，避免每页重复报错
            return ""
        try:
            pix = page.get_pixmap(dpi=settings.pdf_ocr_dpi)
            png_bytes = pix.tobytes("png")
        except Exception as e:  # noqa: BLE001
            logger.warning("page %d 渲染失败：%s", page_no, e)
            return ""
        text = ocr_pixmap_bytes(png_bytes)
        return clean_text(text)