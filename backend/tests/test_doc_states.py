"""doc_states 状态机单测（纯函数，无外部依赖）。"""

from __future__ import annotations

import pytest

from app.services import doc_states as st


def test_main_chain_legal():
    # 正常主链：首次登记/直接处理 → … → done
    assert st.can_transition(None, st.PENDING)
    assert st.can_transition(None, st.INGESTING)
    chain = [st.PENDING, st.INGESTING, st.EMBEDDING, st.DONE]
    for old, new in zip(chain, chain[1:]):
        st.assert_transition(old, new)  # 不抛即通过


@pytest.mark.parametrize(
    "old,new",
    [
        (st.PENDING, st.FAILED),
        (st.INGESTING, st.FAILED),
        (st.EMBEDDING, st.FAILED),
        (st.DONE, st.FAILED),
    ],
)
def test_any_stage_can_fail(old, new):
    st.assert_transition(old, new)


@pytest.mark.parametrize(
    "old,new",
    [
        (st.FAILED, st.INGESTING),  # 失败重试
        (st.FAILED, st.PENDING),
        (st.DONE, st.INGESTING),    # force 重新入库
        (st.DONE, st.PENDING),      # 同名文件重新上传
    ],
)
def test_retry_and_reingest_legal(old, new):
    assert st.can_transition(old, new)


@pytest.mark.parametrize(
    "old,new",
    [
        (st.PENDING, st.DONE),        # 不能跳过处理直接完成
        (st.PENDING, st.EMBEDDING),   # 不能越过 ingesting
        (st.INGESTING, st.DONE),      # 不能越过 embedding
        (st.INGESTING, st.PENDING),
        (st.EMBEDDING, st.INGESTING), # 不允许回退
        (st.DONE, st.EMBEDDING),
        (st.FAILED, st.DONE),         # 失败必须重跑，不能直接标 done
        (st.FAILED, st.EMBEDDING),
    ],
)
def test_illegal_transitions_blocked(old, new):
    assert not st.can_transition(old, new)
    with pytest.raises(st.IllegalTransitionError):
        st.assert_transition(old, new)


def test_every_state_has_transition_rule():
    for state in st.ALL_STATES:
        assert state in st.ALLOWED_TRANSITIONS


def test_state_string_values_stable():
    # 这些字符串落库到 documents.status，改名会造成历史数据不兼容
    assert st.ALL_STATES == {"pending", "ingesting", "embedding", "done", "failed"}
    assert st.TERMINAL == {"done", "failed"}
    assert st.IN_PROGRESS == {"pending", "ingesting", "embedding"}


def test_is_stuck():
    now = 1000.0
    # 处理态且超时 -> 卡住
    assert st.is_stuck(st.INGESTING, now - 100, now, timeout_seconds=50)
    assert st.is_stuck(st.EMBEDDING, now - 100, now, timeout_seconds=50)
    # 处理态但未超时 -> 不算
    assert not st.is_stuck(st.INGESTING, now - 10, now, timeout_seconds=50)
    # 终态永远不算卡住
    assert not st.is_stuck(st.DONE, now - 99999, now, timeout_seconds=50)
    assert not st.is_stuck(st.FAILED, now - 99999, now, timeout_seconds=50)
