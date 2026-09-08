"""PDF 解析器单元测试：用 monkeypatch 替身 pymupdf4llm / pymupdf / OCR，离线可跑。

覆盖场景：
- 文字型 PDF（pymupdf4llm 有文本）→ 走主路径
- 扫描件 PDF（pymupdf4llm 空 + pymupdf 直抽空）→ 走 OCR 兜底
- 混合文档（部分页文字、部分扫描）→ 双轨
- OCR 关闭时扫描件仍报"0 页"（行为保留，便于排障）
- pymupdf4llm 异常 → 返回带 error 的 ParsedDocument，不抛
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---- 替身 ----


class _FakePixmap:
    def __init__(self, png_bytes: bytes = b"\\x89PNG\\r\\n\\x1a\\n") -> None:
        self._b = png_bytes

    def tobytes(self, fmt: str = "png") -> bytes:
        return self._b


class _FakePage:
    def __init__(self, text: str = "", png: bytes | None = None) -> None:
        self._text = text
        # 默认每页都有 pixmap（扫描件场景必须，否则 get_pixmap 抛断言）
        self._pixmap = _FakePixmap(png) if png is not None else _FakePixmap()

    def get_text(self) -> str:
        return self._text

    def get_pixmap(self, dpi: int = 200) -> _FakePixmap:
        assert self._pixmap is not None
        return self._pixmap


class _FakePdfDoc:
    def __init__(self, pages: list[_FakePage]) -> None:
        self._pages = pages
        self.page_count = len(pages)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def __getitem__(self, idx):
        return self._pages[idx]


def _patch_pymupdf4llm(monkeypatch, chunks: list[dict]):
    """替身 pymupdf4llm.to_markdown。"""
    monkeypatch.setattr(
        "app.services.parsers.pdf.pymupdf4llm.to_markdown",
        lambda *a, **kw: chunks,
    )


def _patch_pymupdf_open(monkeypatch, pdf_doc: _FakePdfDoc):
    """替身 pymupdf.open。"""
    monkeypatch.setattr(
        "app.services.parsers.pdf.pymupdf.open",
        lambda *a, **kw: pdf_doc,
    )


def _patch_ocr(monkeypatch, texts_by_call: list[str]):
    """替身 ocr_pixmap_bytes：每次调用返回 texts_by_call 的下一项；耗尽返回空串。
    返回 calls 列表用于断言调用次数。
    """
    queue = list(texts_by_call)
    calls = []

    def _fake(png_bytes: bytes) -> str:
        calls.append(png_bytes)
        if not queue:
            return ""  # 不抛错，避免被 except 吞掉时掩盖真实失败
        return queue.pop(0)

    monkeypatch.setattr("app.services.parsers.pdf.ocr_pixmap_bytes", _fake)
    return calls


def _patch_ocr_disabled(monkeypatch):
    """OCR 关闭场景：修改 settings.pdf_ocr_enabled 为 False。
    注意：必须直接修改 pdf 模块引用的 settings 实例属性，而非 monkeypatch 字符串路径，
    因为 `app.config.settings` 不是合法子模块（app.config 是 module 不是 package）。
    """
    import app.services.parsers.pdf as pdf_mod

    monkeypatch.setattr(pdf_mod.settings, "pdf_ocr_enabled", False)


# ============ 场景 ============


def test_text_pdf_skips_ocr(monkeypatch):
    """文字型 PDF：pymupdf4llm 有文本 → 不调 OCR，不调 pymupdf 直抽。"""
    from app.services.parsers.pdf import PDFParser

    _patch_pymupdf4llm(monkeypatch, [
        {"text": "第一页正文", "metadata": {"page": 0}},
        {"text": "第二页正文", "metadata": {"page": 1}},
    ])
    _patch_pymupdf_open(monkeypatch, _FakePdfDoc([_FakePage(text="ignored"), _FakePage()]))
    calls = _patch_ocr(monkeypatch, [])

    parsed = PDFParser().parse(Path("dummy.pdf"), doc_id="d1")
    assert parsed.ok
    assert parsed.page_count == 2
    assert parsed.pages[0].page == 1
    assert parsed.pages[1].page == 2
    assert calls == []  # OCR 完全没被调


def test_scanned_pdf_uses_ocr(monkeypatch):
    """扫描件：pymupdf4llm 全空 + pymupdf 直抽空 → 全部走 OCR。

    注：PDFParser 会对 OCR 结果跑 clean_text，清掉"中文-数字"之间的空格
    （PDF 排版噪声，详见 base.clean_text）。测试期望值需与之对齐。
    """
    from app.services.parsers.pdf import PDFParser

    _patch_pymupdf4llm(monkeypatch, [
        {"text": "", "metadata": {"page": 0}},
        {"text": "", "metadata": {"page": 1}},
        {"text": "", "metadata": {"page": 2}},
    ])
    pdf = _FakePdfDoc([
        _FakePage(text=""),  # 第 1 页
        _FakePage(text=""),  # 第 2 页
        _FakePage(text=""),  # 第 3 页
    ])
    _patch_pymupdf_open(monkeypatch, pdf)
    calls = _patch_ocr(monkeypatch, [
        "第一页OCR内容",
        "第二页OCR内容",
        "第三页OCR内容",
    ])

    parsed = PDFParser().parse(Path("dummy.pdf"), doc_id="d1")
    assert parsed.ok
    assert parsed.page_count == 3
    assert [p.text for p in parsed.pages] == [
        "第一页OCR内容",
        "第二页OCR内容",
        "第三页OCR内容",
    ]
    assert len(calls) == 3


def test_mixed_pdf_uses_both(monkeypatch):
    """混合文档：第 1 页文字型（pymupdf4llm 拿到），第 2 页扫描件（OCR）。"""
    from app.services.parsers.pdf import PDFParser

    _patch_pymupdf4llm(monkeypatch, [
        {"text": "第一页文字", "metadata": {"page": 0}},
        {"text": "", "metadata": {"page": 1}},  # 扫描件，pymupdf4llm 拿不到
    ])
    pdf = _FakePdfDoc([
        _FakePage(text="ignored by main path"),  # 第 1 页（已通过 pymupdf4llm 拿到，不再重抽）
        _FakePage(text=""),  # 第 2 页（pymupdf 直抽也空）
    ])
    _patch_pymupdf_open(monkeypatch, pdf)
    calls = _patch_ocr(monkeypatch, [
        "第二页OCR内容",
    ])

    parsed = PDFParser().parse(Path("dummy.pdf"), doc_id="d1")
    assert parsed.ok
    assert parsed.page_count == 2
    assert parsed.pages[0].text == "第一页文字"
    assert parsed.pages[1].text == "第二页OCR内容"
    assert len(calls) == 1


def test_pymupdf_text_recovers_when_pymupdf4llm_misses(monkeypatch):
    """pymupdf4llm 没抽到的页，但 pymupdf 直抽能拿到（不调 OCR）。"""
    from app.services.parsers.pdf import PDFParser

    _patch_pymupdf4llm(monkeypatch, [
        {"text": "", "metadata": {"page": 0}},  # pymupdf4llm 漏掉
    ])
    pdf = _FakePdfDoc([
        _FakePage(text="纯中文文本pymupdf能拿到"),  # 故意混入英文字符，验证不被 clean_text 清掉
    ])
    _patch_pymupdf_open(monkeypatch, pdf)
    calls = _patch_ocr(monkeypatch, [])

    parsed = PDFParser().parse(Path("dummy.pdf"), doc_id="d1")
    assert parsed.ok
    assert parsed.page_count == 1
    assert parsed.pages[0].text == "纯中文文本pymupdf能拿到"
    assert calls == []  # OCR 没被调


def test_ocr_disabled_still_fails_for_scanned(monkeypatch):
    """OCR 关闭时，扫描件仍报"0 页"——保留旧行为供排障。"""
    from app.services.parsers.pdf import PDFParser

    _patch_ocr_disabled(monkeypatch)
    _patch_pymupdf4llm(monkeypatch, [
        {"text": "", "metadata": {"page": 0}},
    ])
    pdf = _FakePdfDoc([_FakePage(text="")])
    _patch_pymupdf_open(monkeypatch, pdf)
    calls = _patch_ocr(monkeypatch, [])  # 即使有 OCR 结果，关闭时也不会被调

    parsed = PDFParser().parse(Path("dummy.pdf"), doc_id="d1")
    assert not parsed.ok
    assert parsed.page_count == 0
    assert calls == []


def test_pymupdf4llm_exception_returns_error(monkeypatch):
    """pymupdf4llm 抛异常 → 返回带 error 的 ParsedDocument，不抛。"""

    def _boom(*a, **kw):
        raise RuntimeError("simulated parse failure")

    monkeypatch.setattr("app.services.parsers.pdf.pymupdf4llm.to_markdown", _boom)
    _patch_pymupdf_open(monkeypatch, _FakePdfDoc([]))

    from app.services.parsers.pdf import PDFParser

    parsed = PDFParser().parse(Path("dummy.pdf"), doc_id="d1")
    assert not parsed.ok
    assert "RuntimeError" in parsed.error
    assert "simulated parse failure" in parsed.error


def test_pages_sorted_by_page_number(monkeypatch):
    """OCR 兜底补页后必须按页码排序，否则下游 chunker 会乱序。"""
    from app.services.parsers.pdf import PDFParser

    # 故意让 metadata.page 与 chunk 索引不一致，验证排序逻辑
    _patch_pymupdf4llm(monkeypatch, [
        {"text": "页3内容", "metadata": {"page": 2}},  # 标 page=2 (0-based) = 第 3 页
        {"text": "", "metadata": {"page": 0}},
    ])
    pdf = _FakePdfDoc([_FakePage(), _FakePage(), _FakePage(text="")])
    _patch_pymupdf_open(monkeypatch, pdf)
    _patch_ocr(monkeypatch, ["页1OCR", "页2OCR"])

    parsed = PDFParser().parse(Path("dummy.pdf"), doc_id="d1")
    assert parsed.ok
    page_nos = [p.page for p in parsed.pages]
    assert page_nos == sorted(page_nos)
    assert page_nos == [1, 2, 3]