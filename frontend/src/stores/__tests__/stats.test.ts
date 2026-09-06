// stats store 测试：默认口径/时间范围、reload 拉取、筛选切换重拉
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useStatsStore } from '../stats'
import type { StatsSummary } from '../../types/api'

vi.mock('../../api/stats', () => ({
  summary: vi.fn(),
}))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

import * as statsApi from '../../api/stats'

const SUMMARY: StatsSummary = {
  cards: {
    total: 19,
    hit_count: 10,
    hit_rate: 52.6,
    avg_retrieval_ms: 323.2,
    avg_llm_ms: 969.1,
    avg_total_ms: 1354.9,
    no_hit_count: 9,
  },
  trend: [{ date: '2026-09-06', count: 13, hit_rate: 38.5, avg_total_ms: 1249.5 }],
  top_questions: [{ question: '徐州采购', count: 4 }],
  top_docs: [{ doc_name: '公示.pdf', count: 8 }],
  kb_dist: [{ kb_id: 'default', count: 19 }],
}

describe('stats store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(statsApi.summary).mockResolvedValue(SUMMARY)
  })

  it('默认 days=30、mode=kb', () => {
    const store = useStatsStore()
    expect(store.days).toBe(30)
    expect(store.mode).toBe('kb')
  })

  it('reload 拉取并写入 summary（默认参数）', async () => {
    const store = useStatsStore()
    await store.reload()
    expect(statsApi.summary).toHaveBeenCalledWith({ days: 30, mode: 'kb' })
    expect(store.summary?.cards.total).toBe(19)
  })

  it('setDays 变化时重拉（null=全部）', async () => {
    const store = useStatsStore()
    await store.reload()
    store.setDays(null)
    expect(statsApi.summary).toHaveBeenLastCalledWith({ days: null, mode: 'kb' })
    expect(store.days).toBeNull()
  })

  it('setMode 变化时重拉', async () => {
    const store = useStatsStore()
    await store.reload()
    store.setMode('general')
    expect(statsApi.summary).toHaveBeenLastCalledWith({ days: 30, mode: 'general' })
    expect(store.mode).toBe('general')
  })

  it('相同值不重复请求', async () => {
    const store = useStatsStore()
    await store.reload()
    const before = vi.mocked(statsApi.summary).mock.calls.length
    store.setDays(30)
    store.setMode('kb')
    expect(vi.mocked(statsApi.summary).mock.calls.length).toBe(before)
  })
})
