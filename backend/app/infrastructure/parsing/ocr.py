"""RapidOCR 引擎单例。

扫描件 PDF 的文本抽取兜底：pymupdf4llm 对纯图像页（无文本层）返回空，
此时调 RapidOCR 把页面渲染为 PNG 后做 OCR。

为什么选 RapidOCR（与 PaddleOCR 对比）：
- 模型格式 ONNX Runtime（与已装的 onnxruntime 1.29.0 复用，零额外系统依赖）
- 包小（~200MB 模型 vs PaddleOCR 的 paddlepaddle ~1.5GB）
- 6GB VRAM 友好（ONNX Runtime <500MB vs paddlepaddle 1-2GB）
- 中文印刷体识别率 > 95%
- 短板：表格识别弱，但本项目表格识别仍走 pymupdf4llm（对文字型 PDF 表格准），
  纯图像表格场景后续可单独补 PaddleOCR 的 PP-Structure。
"""

from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_engine = None
_load_attempted = False
_load_error: Exception | None = None


def get_ocr_engine():
    """进程内共享 RapidOCR 引擎。懒加载，首次调用时初始化（~3s 模型加载）。

    导入失败（如 rapidocr-onnxruntime 未装）时返回 None，调用方应做防御。
    """
    global _engine, _load_attempted, _load_error
    if _engine is not None:
        return _engine
    if not _load_attempted:
        _load_attempted = True
        try:
            from rapidocr_onnxruntime import RapidOCR

            logger.info("正在初始化 RapidOCR（首次加载约 3-5 秒）...")
            _engine = RapidOCR()
            logger.info("RapidOCR 初始化完成")
        except Exception as e:  # noqa: BLE001
            _load_error = e
            logger.error("RapidOCR 初始化失败：%s", e)
            _engine = None
    return _engine


def ocr_pixmap_bytes(png_bytes: bytes) -> str:
    """对 PNG 字节做 OCR，返回纯文本（多行用 \\n 连接）。

    RapidOCR 返回 [[bbox, text, conf], ...] 列表，本函数只取 text 并按行拼接。
    返回空串表示 OCR 失败或无识别结果，调用方应降级处理（不把该页加入解析结果）。
    """
    engine = get_ocr_engine()
    if engine is None:
        return ""
    try:
        result, _elapse = engine(png_bytes)
        if not result:
            return ""
        return "\n".join(str(line[1]) for line in result if len(line) >= 2)
    except Exception as e:  # noqa: BLE001  OCR 失败不致命，让上层标记该页缺失
        logger.warning("OCR 调用异常：%s", e)
        return ""


def get_load_error() -> Exception | None:
    """返回首次加载的异常（用于诊断面板/日志）。"""
    return _load_error