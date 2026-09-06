"""运行日志：行解析 / 倒序分页 / 级别与关键词筛选 / 文件列表 / 路径穿越防护。

用临时目录写假日志文件，monkeypatch settings.log_dir 后离线测试，不触真实日志。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import log_reader

APP_LINES = [
    "2026-09-06 10:00:00.001 | INFO     | app.services.ingestion:193 |   已写入 1/1\n",
    "2026-09-06 10:00:01.002 | ERROR    | app.services.ingestion:146 | 解析失败 demo.pdf: 不支持的类型\n",
    "2026-09-06 10:00:02.003 | WARNING  | app.services.parsers:58 | 不支持的文件类型: .docx\n",
    "2026-09-06 10:00:03.004 | INFO     | app.services.document_service:280 | 删除补偿完成 abc123：向量 1 条、文件 True、DB 已删\n",
    "Traceback (most recent call last):\n",  # 脏行（堆栈片段）
    "2026-09-06 10:00:04.005 | INFO     | app.services.retrieval:191 | 检索无命中（kb_id=default）\n",
]

ACCESS_LINES = [
    '2026-09-06 10:00:00.001 | INFO     | 127.0.0.1:55072 - "GET /api/kbs HTTP/1.1" 200 OK\n',
    '2026-09-06 10:00:01.002 | INFO     | 127.0.0.1:55073 - "GET /api/documents?page=1 HTTP/1.1" 200 OK\n',
]


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    (tmp_path / "app.log").write_text("".join(APP_LINES), encoding="utf-8")
    (tmp_path / "access.log").write_text("".join(ACCESS_LINES), encoding="utf-8")
    (tmp_path / "app.log.2026-09-05").write_text("old line\n", encoding="utf-8")
    # 非日志文件不应出现在列表
    (tmp_path / "readme.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(log_reader.settings, "log_dir", tmp_path)
    return tmp_path


# ==================== 文件列表 ====================

def test_list_log_files(log_dir):
    files = log_reader.list_log_files()
    names = [f["name"] for f in files]
    assert names == ["access.log", "app.log", "app.log.2026-09-05"]  # 排除 readme.txt
    by_name = {f["name"]: f for f in files}
    assert by_name["app.log"]["is_rotated"] is False
    assert by_name["app.log.2026-09-05"]["is_rotated"] is True
    assert by_name["app.log"]["size_bytes"] > 0


# ==================== 行解析 ====================

def test_parse_app_line():
    e = log_reader._parse_line(APP_LINES[0], "app")
    assert e.ts == "2026-09-06 10:00:00.001"
    assert e.level == "INFO"
    assert e.source == "app.services.ingestion:193"
    assert e.message == "已写入 1/1"


def test_parse_access_line():
    e = log_reader._parse_line(ACCESS_LINES[0], "access")
    assert e.level == "INFO"
    assert "127.0.0.1:55072" in e.source
    assert 'GET /api/kbs' in e.message


def test_parse_ansi_escapes_stripped():
    raw = '2026-09-06 10:00:00.001 | INFO     | 127.0.0.1:1 - "\x1b[1mGET /api/health HTTP/1.1\x1b[0m" \x1b[32m200 OK\x1b[0m\n'
    e = log_reader._parse_line(raw, "access")
    assert "\x1b" not in e.message
    assert 'GET /api/health HTTP/1.1" 200 OK' in e.message


def test_parse_dirty_line_kept():
    e = log_reader._parse_line("Traceback (most recent call last):\n", "app")
    assert e is not None
    assert e.level == "OTHER"
    assert e.message == "Traceback (most recent call last):"


def test_parse_blank_line():
    assert log_reader._parse_line("\n", "app") is None


# ==================== 倒序分页 ====================

def test_read_entries_newest_first(log_dir):
    items, next_end = log_reader.read_entries("app.log", limit=100)
    assert next_end is None  # 已到底
    # 最新在前：最后一行（检索无命中）在最前
    assert items[0]["message"] == "检索无命中（kb_id=default）"
    assert items[-1]["message"] == "已写入 1/1"
    # 脏行保留
    assert any(i["level"] == "OTHER" for i in items)


def test_read_entries_pagination(log_dir):
    # 第一页 limit=3 → 最新 3 条（文件共 6 行，剩 3 行但 end_line 排除最老游标行）
    items, next_end = log_reader.read_entries("app.log", limit=3)
    assert len(items) == 3
    assert next_end == items[-1]["line_no"] - 1
    # 第二页：从 next_end 继续 → 剩 2 条（行 1、2）
    items2, next_end2 = log_reader.read_entries("app.log", end_line=next_end, limit=3)
    assert len(items2) == 2
    assert next_end2 is None
    # 两页行号无重叠
    page1 = {i["line_no"] for i in items}
    page2 = {i["line_no"] for i in items2}
    assert not (page1 & page2)


def test_read_entries_level_filter(log_dir):
    items, _ = log_reader.read_entries("app.log", level="ERROR", limit=100)
    assert len(items) == 1
    assert items[0]["message"].startswith("解析失败")


def test_read_entries_search_filter(log_dir):
    items, _ = log_reader.read_entries("app.log", search="删除补偿", limit=100)
    assert len(items) == 1
    assert items[0]["source"].startswith("app.services.document_service")


def test_read_entries_file_not_found(log_dir):
    with pytest.raises(FileNotFoundError):
        log_reader.read_entries("nope.log")


# ==================== 路径穿越防护 ====================

def test_resolve_path_traversal_blocked(log_dir):
    assert log_reader.resolve_path("../kb.db") is None
    assert log_reader.resolve_path("a/b/app.log") is None
    assert log_reader.resolve_path("app.log") is not None
