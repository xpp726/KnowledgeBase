// 文档管理 store：知识库维度 UI + 列表分页/搜索/筛选 + 多文件上传（前端并发 3）
// + 删除/重试 + 异步进度轮询（3s，存在非终态才轮询）
//
// 上传时序（与后端约定）：
//   upload → POST /documents 登记即返回 → 后端调度器异步解析（信号量=2）
//   → 前端 startPolling 轮询 list 观察状态推进 → 全终态自动停
// 轮询终止条件：当前列表无 pending/ingesting/embedding，或页面切走（组件 unmount）

import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import type {
  DocStatus,
  DocumentItem,
  DocumentUploadResult,
  KnowledgeBase,
} from '../types/api'
import * as docApi from '../api/documents'
import * as kbApi from '../api/kb'

const POLL_INTERVAL_MS = 3_000
const UPLOAD_CONCURRENCY = 3 // 前端同时并发上传的文件数（后端解析并发另有信号量=2）

const IN_PROGRESS: DocStatus[] = ['pending', 'ingesting', 'embedding']

export const useDocumentStore = defineStore('document', () => {
  // ==================== state ====================
  const kbs = ref<KnowledgeBase[]>([])
  const currentKbId = ref<string>('default')

  const documents = ref<DocumentItem[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const statusFilter = ref<DocStatus | ''>('')
  const search = ref('')

  const loading = ref(false)
  const uploading = ref(false)
  const deletingIds = ref<Set<string>>(new Set())
  const reprocessingIds = ref<Set<string>>(new Set())

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let pollRequested = false // 上传/重试后强制轮询直至终态

  // ==================== 知识库 ====================

  async function loadKbs() {
    try {
      kbs.value = await kbApi.list()
      if (!kbs.value.some((k) => k.kb_id === currentKbId.value)) {
        currentKbId.value = kbs.value[0]?.kb_id ?? 'default'
      }
    } catch (e) {
      ElMessage.error((e as Error).message || '知识库列表加载失败')
    }
  }

  async function createKb(name: string, description = '') {
    const kb = await kbApi.create({ name, description })
    await loadKbs()
    currentKbId.value = kb.kb_id
    await reload({ resetPage: true })
    return kb
  }

  async function setCurrentKb(kbId: string) {
    if (kbId === currentKbId.value) return
    currentKbId.value = kbId
    await reload({ resetPage: true })
  }

  // ==================== 列表 ====================

  async function reload(opts: { resetPage?: boolean; silent?: boolean } = {}) {
    if (opts.resetPage) page.value = 1
    loading.value = true
    try {
      const res = await docApi.list({
        kb_id: currentKbId.value,
        status: statusFilter.value,
        search: search.value,
        page: page.value,
        page_size: pageSize.value,
      })
      documents.value = res.items
      total.value = res.total
    } catch (e) {
      if (!opts.silent) ElMessage.error((e as Error).message || '文档列表加载失败')
    } finally {
      loading.value = false
    }
    // 轮询进行中（上传/重试后）：确保定时器存活，不重复创建
    if (pollRequested && !pollTimer) schedulePoll()
  }

  function setStatus(status: DocStatus | '') {
    if (status === statusFilter.value) return
    statusFilter.value = status
    void reload({ resetPage: true })
  }

  function setSearch(keyword: string) {
    search.value = keyword
    void reload({ resetPage: true })
  }

  function setPage(p: number) {
    if (p === page.value) return
    page.value = p
    void reload()
  }

  // ==================== 上传（多文件，前端并发 3） ====================

  function hasAnyInProgress(): boolean {
    return documents.value.some((d) => IN_PROGRESS.includes(d.status))
  }

  function schedulePoll() {
    stopPoll()
    pollTimer = setInterval(() => {
      void (async () => {
        const res = await docApi.list({
          kb_id: currentKbId.value,
          status: statusFilter.value,
          search: search.value,
          page: page.value,
          page_size: pageSize.value,
        })
        documents.value = res.items
        total.value = res.total
        // 全终态 → 停止轮询；当前页全终态但其它页仍有处理中？以当前页判断即可
        if (!documents.value.some((d) => IN_PROGRESS.includes(d.status))) {
          stopPoll()
          pollRequested = false
        }
      })().catch(() => {
        // 轮询单次失败不中断，下一轮重试
      })
    }, POLL_INTERVAL_MS)
  }

  function startPolling() {
    pollRequested = true
    if (!pollTimer) schedulePoll()
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /**
   * 多文件上传：分批并发（每批 3 个），登记即返回；随后刷新列表 + 轮询进度。
   * 同名文件由调用方（页面）先弹确认，这里不做二次判断。
   */
  async function uploadFiles(files: File[]): Promise<DocumentUploadResult[]> {
    uploading.value = true
    const results: DocumentUploadResult[] = []
    try {
      for (let i = 0; i < files.length; i += UPLOAD_CONCURRENCY) {
        const batch = files.slice(i, i + UPLOAD_CONCURRENCY)
        const batchResults = await docApi.upload(batch)
        results.push(...batchResults)
        // 每批后静默刷新，让用户尽快看到新条目
        await reload({ silent: true })
      }
      const rejected = results.filter((r) => r.status === 'rejected')
      const okCount = results.length - rejected.length
      if (rejected.length > 0) {
        ElMessage.warning(
          `已登记 ${okCount} 个文件，${rejected.length} 个失败：${rejected
            .map((r) => r.error || r.file_name)
            .join('；')}`,
        )
      } else if (okCount > 0) {
        ElMessage.success(`已提交 ${okCount} 个文件，解析进行中`)
      }
      startPolling()
    } catch (e) {
      ElMessage.error((e as Error).message || '上传失败')
      throw e
    } finally {
      uploading.value = false
    }
    return results
  }

  // ==================== 删除 / 重试 ====================

  async function removeDoc(docId: string) {
    deletingIds.value.add(docId)
    try {
      await docApi.remove(docId)
      // 当前页可能因删除而空（最后一页），回退页码后刷新
      documents.value = documents.value.filter((d) => d.doc_id !== docId)
      total.value = Math.max(0, total.value - 1)
      if (documents.value.length === 0 && page.value > 1) {
        page.value -= 1
      }
      await reload({ silent: true })
      ElMessage.success('已删除')
    } catch (e) {
      ElMessage.error((e as Error).message || '删除失败')
      throw e
    } finally {
      deletingIds.value.delete(docId)
    }
  }

  async function reprocessDoc(docId: string) {
    reprocessingIds.value.add(docId)
    try {
      await docApi.reprocess(docId)
      ElMessage.success('已调度解析，请稍候')
      startPolling()
      await reload({ silent: true })
    } catch (e) {
      ElMessage.error((e as Error).message || '调度失败')
      throw e
    } finally {
      reprocessingIds.value.delete(docId)
    }
  }

  return {
    kbs,
    currentKbId,
    documents,
    total,
    page,
    pageSize,
    statusFilter,
    search,
    loading,
    uploading,
    deletingIds,
    reprocessingIds,
    hasAnyInProgress,
    loadKbs,
    createKb,
    setCurrentKb,
    reload,
    setStatus,
    setSearch,
    setPage,
    uploadFiles,
    removeDoc,
    reprocessDoc,
    startPolling,
    stopPoll,
  }
})
