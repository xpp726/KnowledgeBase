// logs store 测试：文件加载、倒序游标分页、筛选、自动刷新合并（去重）、暂停
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useLogStore } from '../logs'
import type { LogEntry, LogFile } from '../../types/api'

vi.mock('../../api/logs', () => ({
  listFiles: vi.fn(),
  entries: vi.fn(),
  downloadUrl: vi.fn(() => '/api/logs/download?file=app.log'),
}))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

import * as logApi from '../../api/logs'

const FILES: LogFile[] = [
  { name: 'app.log', size_bytes: 100, mtime: 1, is_rotated: false },
  { name: 'access.log', size_bytes: 200, mtime: 2, is_rotated: false },
  { name: 'app.log.2026-09-05', size_bytes: 50, mtime: 3, is_rotated: true },
]

function entry(line_no: number, message = `msg-${line_no}`): LogEntry {
  return {
    line_no,
    ts: `2026-09-06 10:00:${line_no}.000`,
    level: 'INFO',
    source: 'app.services.x:1',
    message,
  }
}

describe('logs store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.clearAllMocks()
    vi.mocked(logApi.listFiles).mockResolvedValue(FILES)
    vi.mocked(logApi.entries).mockResolvedValue({
      items: [entry(3), entry(2), entry(1)],
      next_end_line: null,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loadFiles 设置列表并保持默认 app.log', async () => {
    const store = useLogStore()
    await store.loadFiles()
    expect(store.files).toHaveLength(3)
    expect(store.currentFile).toBe('app.log')
  })

  it('reload 拉最新一页并设置游标', async () => {
    const store = useLogStore()
    vi.mocked(logApi.entries).mockResolvedValue({
      items: [entry(10), entry(9)],
      next_end_line: 8,
    })
    await store.reload()
    expect(logApi.entries).toHaveBeenCalledWith({
      file: 'app.log',
      level: '',
      search: '',
      limit: 100,
    })
    expect(store.entries.map((e) => e.line_no)).toEqual([10, 9])
    expect(store.nextEndLine).toBe(8)
  })

  it('loadMore 追加更早数据并更新游标', async () => {
    const store = useLogStore()
    vi.mocked(logApi.entries)
      .mockResolvedValueOnce({ items: [entry(5)], next_end_line: 4 })
      .mockResolvedValueOnce({ items: [entry(4), entry(3)], next_end_line: null })
    await store.reload()
    await store.loadMore()
    expect(store.entries.map((e) => e.line_no)).toEqual([5, 4, 3])
    expect(store.nextEndLine).toBeNull()
  })

  it('筛选条件变化时重拉（reload 传参）', async () => {
    const store = useLogStore()
    store.setLevel('ERROR')
    store.applySearch('删除补偿')
    expect(logApi.entries).toHaveBeenLastCalledWith(
      expect.objectContaining({ level: 'ERROR', search: '删除补偿' }),
    )
  })

  it('自动刷新 tick 合并新行并保留更早记录（line_no 去重）', async () => {
    const store = useLogStore()
    await store.reload() // 初始 [3,2,1]
    vi.mocked(logApi.entries).mockResolvedValue({
      items: [entry(6), entry(5), entry(3)], // 新行 6、5；3 重复
      next_end_line: 4,
    })
    store.startAutoRefresh()
    await vi.advanceTimersByTimeAsync(5_000)
    expect(store.entries.map((e) => e.line_no)).toEqual([6, 5, 3, 2, 1])
    store.stopAutoRefresh()
  })

  it('setFile 重置级别与搜索筛选（独立浏览上下文）', async () => {
    const store = useLogStore()
    store.setLevel('ERROR')
    store.applySearch('删除')
    expect(store.levelFilter).toBe('ERROR')
    expect(store.search).toBe('删除')
    store.setFile('access.log')
    expect(store.currentFile).toBe('access.log')
    expect(store.levelFilter).toBe('')
    expect(store.search).toBe('')
    expect(logApi.entries).toHaveBeenLastCalledWith(
      expect.objectContaining({ file: 'access.log', level: '', search: '' }),
    )
  })

  it('toggleAutoRefresh 关闭后不再轮询', async () => {
    const store = useLogStore()
    await store.reload()
    store.toggleAutoRefresh(false)
    const before = vi.mocked(logApi.entries).mock.calls.length
    await vi.advanceTimersByTimeAsync(15_000)
    expect(vi.mocked(logApi.entries).mock.calls.length).toBe(before)
  })
})
