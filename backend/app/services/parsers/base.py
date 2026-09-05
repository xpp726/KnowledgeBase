"""解析器数据结构与文本清洗规则。

清洗规则来自 2026-09-05 对 test_files 真实招标 PDF 的实测：
PDF 排版会在**中文字符之间、中英数字之间**插入空格（如 "2026 年第四次"、
"评审 工作已经结束"）。这些空格是排版产物，不是语义分隔，
会直接破坏 BGE-M3 的语义匹配与 sparse 词权重，必须清除。
英文单词之间的空格则必须保留。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

# 中日韩字符 + 全角标点
_CJK = r"\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"

# 中文字符之后 / 之前的空格：排版产物，删除
_RE_SPACE_AFTER_CJK = re.compile(rf"(?<=[{_CJK}])[ \t]+")
_RE_SPACE_BEFORE_CJK = re.compile(rf"[ \t]+(?=[{_CJK}])")
# 3 个以上连续换行压缩成 2 个
_RE_MULTI_BLANK = re.compile(r"\n{3,}")
# 行尾空白
_RE_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
# PDF 单元格内的换行会被 pymupdf4llm 转成 <br>。
# 这是同一个词被排版切断（如 "序<br>号" 实为 "序号"、"投标报<br>价" 实为 "投标报价"），
# 必须直接删除而非替换成空格，否则 BGE-M3 会把 "序" 和 "号" 当成两个词。
_RE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)


def clean_text(text: str) -> str:
    """清洗 PDF/Office 提取文本中的排版噪声。

    保留 Markdown 表格语法（| 与 --- 不受影响，因为不含中文）。
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _RE_BR.sub("", text)
    text = _RE_SPACE_AFTER_CJK.sub("", text)
    text = _RE_SPACE_BEFORE_CJK.sub("", text)
    text = _RE_TRAILING_WS.sub("", text)
    text = _RE_MULTI_BLANK.sub("\n\n", text)
    return text.strip()


@dataclass
class PageContent:
    """一页（或一个逻辑单元）的解析结果。page 从 1 开始。"""

    page: int
    text: str


@dataclass
class ParsedDocument:
    """解析器统一输出。pages 为空表示解析失败。"""

    doc_id: str
    file_name: str
    pages: list[PageContent] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.pages) and not self.error

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)


class BaseParser(ABC):
    """解析器基类。"""

    extensions: set[str] = set()

    @abstractmethod
    def parse(self, path: Path, doc_id: str) -> ParsedDocument:
        """解析文件，返回带页码的文档结构。"""
        raise NotImplementedError

    def _make(self, path: Path, doc_id: str, **meta) -> ParsedDocument:
        return ParsedDocument(
            doc_id=doc_id, file_name=path.name, meta=meta
        )
