"""文档解析、OCR 与文本分块基础设施。"""

from .chunker import Chunk, chunk_document
from .parsers import parse_file, supported_extensions

__all__ = ["Chunk", "chunk_document", "parse_file", "supported_extensions"]
