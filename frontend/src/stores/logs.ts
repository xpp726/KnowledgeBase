// 运行日志 store：文件切换 / 倒序游标分页 / 级别与关键词筛选 / 自动刷新（可暂停）
//
// 分页语义（与后端约定）：最新在前，line_no 作游标。
//   - reload()：重置游标拉最新一页
//   - loadMore()：按 next_end_line 拉更早数据追加到尾部
//   - 自动刷新（默认开，5s）：只拉最新一页，与现有列表按 line_no 去重合并
//     （新行插前、保留已加载的更早历史），合并后超过 MAX_KEEP 截断尾部
//
// 注意：与 document store 不同，这里刷新是"合并"而非"替换"，
// 避免用户加载更早记录后刷新丢失上下文。

import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import type { LogEntry, LogFile } from '../types/api'
import * as logApi from '../api/logs'

const AUTO_REFRESH_MS = 5_000
const PAGE_LIMIT = 100
const MAX_KEEP = 500 // 合并后保留的最大条目数（更早的截断）

export const useLogStore = defineStore('logs', () => {
  // ==================== state ====================
  const files = ref<LogFile[]>([])
  const currentFile = ref('app.log')
  const entries = ref<LogEntry[]>([])
  const nextEndLine = ref<number | null>(null)
  const levelFilter = ref<string>('')
  const search = ref('')
  const autoRefresh = ref(true)
  const loading = ref(false)
  const loadingMore = ref(false)

  let refreshTimer: ReturnType<typeof setInterval> | null = null

  // ==================== 文件 ====================

  async function loadFiles() {
    try {
      files.value = await logApi.listFiles()
      if (!files.value.some((f) => f.name === currentFile.value)) {
        const preferred = files.value.find((f) => f.name === 'app.log')
        currentFile.value = preferred?.name ?? files.value[0]?.name ?? 'app.log'
      }
    } catch (e) {
      ElMessage.error((e as Error).message || '日志文件列表加载失败')
    }
  }

  // ==================== 列表 ====================

  function mergeLatest(latest: LogEntry[]) {
    const known = new Set(entries.value.map((e) => e.line_no))
    const fresh = latest.filter((e) => !known.has(e.line_no))
    entries.value = [...fresh, ...entries.value].slice(0, MAX_KEEP)
  }

  async function reload(opts: { silent?: boolean } = {}) {
    if (!opts.silent) loading.value = true
    try {
      const res = await logApi.entries({
        file: currentFile.value,
        level: levelFilter.value,
        search: search.value,
        limit: PAGE_LIMIT,
      })
      entries.value = res.items
      nextEndLine.value = res.next_end_line
    } catch (e) {
      if (!opts.silent) ElMessage.error((e as Error).message || '日志加载失败')
    } finally {
      if (!opts.silent) loading.value = false
    }
  }

  /** 自动刷新 tick：静默拉最新一页并去重合并 */
  async function refreshLatest() {
    if (loading.value || loadingMore.value) return
    try {
      const res = await logApi.entries({
        file: currentFile.value,
        level: levelFilter.value,
        search: search.value,
        limit: PAGE_LIMIT,
      })
      if (res.items.length > 0) {
        mergeLatest(res.items)
      }
      nextEndLine.value = res.next_end_line
    } catch {
      // 单次刷新失败静默，下一轮重试
    }
  }

  async function loadMore() {
    if (nextEndLine.value == null || loadingMore.value) return
    loadingMore.value = true
    try {
      const res = await logApi.entries({
        file: currentFile.value,
        level: levelFilter.value,
        search: search.value,
        end_line: nextEndLine.value,
        limit: PAGE_LIMIT,
      })
      entries.value.push(...res.items)
      // 过滤场景下更早的物理行可能无更多命中：本次为空则直接置底，避免空加载
      nextEndLine.value = res.items.length > 0 ? res.next_end_line : null
    } catch (e) {
      ElMessage.error((e as Error).message || '加载更早日志失败')
    } finally {
      loadingMore.value = false
    }
  }

  function setFile(name: string) {
    if (name === currentFile.value) return
    currentFile.value = name
    // 切换文件即切换浏览上下文：重置级别与搜索筛选
    levelFilter.value = ''
    search.value = ''
    void reload()
  }

  function setLevel(level: string) {
    if (level === levelFilter.value) return
    levelFilter.value = level
    void reload()
  }

  function applySearch(keyword: string) {
    const kw = keyword.trim()
    if (kw === search.value) return
    search.value = kw
    void reload()
  }

  // ==================== 自动刷新 ====================

  function startAutoRefresh() {
    if (refreshTimer) return
    refreshTimer = setInterval(() => void refreshLatest(), AUTO_REFRESH_MS)
  }

  function stopAutoRefresh() {
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
  }

  function toggleAutoRefresh(on: boolean) {
    autoRefresh.value = on
    if (on) startAutoRefresh()
    else stopAutoRefresh()
  }

  return {
    files,
    currentFile,
    entries,
    nextEndLine,
    levelFilter,
    search,
    autoRefresh,
    loading,
    loadingMore,
    loadFiles,
    reload,
    loadMore,
    setFile,
    setLevel,
    applySearch,
    startAutoRefresh,
    stopAutoRefresh,
    toggleAutoRefresh,
  }
})
