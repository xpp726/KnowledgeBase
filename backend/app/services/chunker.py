"""分块策略：标题路径保留 + 表格保护。

针对 test_files 实测（48 页 / 37 个表格）的两条核心规则：

1. **表格优先**：表格是招标文档的核心信息载体（中标候选人、报价、排名）。
   短表格整体保留；长表格按行分组切分，**每组重复表头**，
   这样"包15的成交候选人是谁"能精确命中那一行，而不是返回整张大表。

2. **标题路径注入**：每个 chunk 带上所属标题路径（如 "一、成交候选人 > 包1"），
   弥补切分后丢失的上下文，显著提升 sparse 检索命中率。

普通文本走递归切分：段落 → 行 → 句号 → 硬切，带重叠。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.config import get_settings
from app.services.parsers.base import ParsedDocument

settings = get_settings()

# Markdown 表格行
_RE_TABLE_ROW = re.compile(r"^\s*\|")
# 标题：# 语法，或 "一、" "1." "第X章" 这类中文编号
_RE_HEADING_MD = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_RE_HEADING_CN = re.compile(
    r"^\s*(?:[一二三四五六七八九十]+[、.]|第[一二三四五六七八九十]+[章节条]|\d+(?:\.\d+)*[、.]?\s)"
)


@dataclass
class Chunk:
    """一个检索单元。"""

    chunk_id: str
    doc_id: str
    doc_name: str
    text: str
    page: int
    index: int
    heading_path: str = ""
    is_table: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        """带标题前缀的完整文本，实际送进 Embedding 与 LLM 的内容。"""
        if self.heading_path:
            return f"【{self.heading_path}】\n{self.text}"
        return self.text


def _is_table_line(line: str) -> bool:
    return bool(_RE_TABLE_ROW.match(line))


def _heading_level(line: str) -> tuple[int, str] | None:
    """识别标题，返回 (层级, 标题文本)。非标题返回 None。"""
    m = _RE_HEADING_MD.match(line)
    if m:
        hashes = line.strip().split(" ")[0]
        return len(hashes), m.group(1).strip()
    stripped = line.strip()
    # 中文编号标题：较短且不以标点结尾
    if _RE_HEADING_CN.match(stripped) and len(stripped) <= 40:
        if stripped and stripped[-1] not in "。；;，,：:":
            return 3, stripped
    return None


def _split_table(lines: list[str], max_chars: int) -> list[str]:
    """表格切块。

    按**字符预算**而非行数切分：实测同样 12 行，短表格只有 300 字符，
    而江西招标那种含报价/工期/资格能力的多列表格能到 1600+ 字符。
    长表格分组切分并重复表头，保证每组都能独立理解。
    """
    if len(lines) < 3:
        return ["\n".join(lines)] if lines else []

    header = lines[:2]  # 表头 + 分隔行
    body = lines[2:]
    header_len = sum(len(line) + 1 for line in header)

    if header_len + sum(len(line) + 1 for line in body) <= max_chars:
        return ["\n".join(lines)]

    groups: list[str] = []
    buf: list[str] = []
    buf_len = header_len
    for line in body:
        line_len = len(line) + 1
        if buf and buf_len + line_len > max_chars:
            groups.append("\n".join(header + buf))
            buf = []
            buf_len = header_len
        buf.append(line)
        buf_len += line_len
    if buf:
        groups.append("\n".join(header + buf))
    return groups


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    """普通文本递归切分：段落 → 行 → 句号 → 硬切。"""
    if len(text) <= size:
        return [text] if text.strip() else []

    # 先按段落
    parts = [p for p in text.split("\n\n") if p.strip()]
    if len(parts) > 1:
        return _merge_parts(parts, size, overlap, sep="\n\n")

    # 再按行
    parts = [p for p in text.split("\n") if p.strip()]
    if len(parts) > 1:
        return _merge_parts(parts, size, overlap, sep="\n")

    # 再按句末标点
    parts = re.split(r"(?<=[。！？；])", text)
    parts = [p for p in parts if p.strip()]
    if len(parts) > 1:
        return _merge_parts(parts, size, overlap, sep="")

    # 最后硬切
    out = []
    step = max(1, size - overlap)
    for i in range(0, len(text), step):
        out.append(text[i : i + size])
        if i + size >= len(text):
            break
    return [p for p in out if p.strip()]


def _merge_parts(parts: list[str], size: int, overlap: int, sep: str) -> list[str]:
    """把小片段组装成不超过 size 的块，相邻块之间保留 overlap 字符重叠。"""
    out: list[str] = []
    buf = ""
    for part in parts:
        candidate = f"{buf}{sep}{part}" if buf else part
        if len(candidate) <= size:
            buf = candidate
            continue
        if buf:
            out.append(buf)
            # 重叠：把上一块尾部 overlap 个字符带到下一块开头
            tail = buf[-overlap:] if overlap > 0 else ""
            buf = f"{tail}{sep}{part}" if tail else part
        else:
            # 单个片段就超长，交给下一级递归处理
            out.extend(_split_text(part, size, overlap))
            buf = ""
    if buf:
        out.append(buf)
    return [p for p in out if p.strip()]


def _make_chunk_id(doc_id: str, index: int, text: str) -> str:
    """稳定 chunk id：同一文档同一位置重复入库时 id 不变，支持幂等写入。"""
    digest = hashlib.md5(f"{doc_id}:{index}:{text[:200]}".encode("utf-8")).hexdigest()[:12]
    return f"{doc_id}-{index:04d}-{digest}"


def chunk_document(
    doc: ParsedDocument,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    min_chunk_chars: int = 20,
) -> list[Chunk]:
    """把解析后的文档切成检索单元。

    min_chunk_chars：丢弃过短碎片（实测会出现长度 1 的块，
    如只有表头分隔线的残留），这类块向量化后是噪声。
    """
    size = chunk_size or settings.chunk_size
    overlap = chunk_overlap or settings.chunk_overlap

    chunks: list[Chunk] = []
    # 标题栈跨页保持：标题在上一页、内容在下一页的情况很常见
    headings: list[tuple[int, str]] = []
    index = 0

    for page in doc.pages:
        lines = page.text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]

            # ---- 标题行 ----
            h = _heading_level(line)
            if h and not _is_table_line(line):
                level, title = h
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, title))
                i += 1
                continue

            # ---- 表格块 ----
            if _is_table_line(line):
                j = i
                while j < len(lines) and _is_table_line(lines[j]):
                    j += 1
                table_lines = lines[i:j]
                for piece in _split_table(table_lines, size):
                    chunks.append(
                        Chunk(
                            chunk_id="",
                            doc_id=doc.doc_id,
                            doc_name=doc.file_name,
                            text=piece,
                            page=page.page,
                            index=index,
                            heading_path=" > ".join(t for _, t in headings),
                            is_table=True,
                        )
                    )
                    index += 1
                i = j
                continue

            # ---- 普通文本块：累积到下一个空行或表格 ----
            j = i
            buf: list[str] = []
            while j < len(lines):
                cur = lines[j]
                if _is_table_line(cur):
                    break
                if _heading_level(cur):
                    break
                buf.append(cur)
                j += 1
            if j == i:  # 保险：避免死循环
                buf.append(lines[i])
                j = i + 1

            block = "\n".join(buf).strip()
            for piece in _split_text(block, size, overlap):
                chunks.append(
                    Chunk(
                        chunk_id="",
                        doc_id=doc.doc_id,
                        doc_name=doc.file_name,
                        text=piece,
                        page=page.page,
                        index=index,
                        heading_path=" > ".join(t for _, t in headings),
                        is_table=False,
                    )
                )
                index += 1
            i = j

    # 丢弃过短碎片：实测会产生长度 1 的空块（表头分隔线残留等），
    # 向量化后纯属噪声，且会稀释检索结果
    chunks = [c for c in chunks if len(c.text.strip()) >= min_chunk_chars]

    # 过滤后重新编号，保证 index 连续、chunk_id 稳定
    for i, c in enumerate(chunks):
        c.index = i
        c.chunk_id = _make_chunk_id(c.doc_id, c.index, c.text)

    return chunks
