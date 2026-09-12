// 文档管理 store：知识库维度 UI + folder 树状组织 + 按 folder 懒加载 + 搜索/筛选走后端
// + 多文件上传（前端并发 3）+ folder CRUD + 删除/重试 + 异步进度轮询（3s，轻量 summary 判断）
//
// 上传时序（与后端约定）：
//   upload → POST /folders/{id}/upload 登记即返回 → 后端调度器异步解析（信号量=2）
//   → 前端 startPolling 轮询（summary 判断 + 已展开 folder 刷新）→ 全终态自动停
// 轮询终止条件：当前 kb 文档无 pending/ingesting/embedding（GET /documents/summary），
// 或页面切走（组件 unmount）
//
// 数据加载（2026-09-09 改造：树状单表 + 懒加载）：
//   - loadFolderTree() 拉 folder 树（带 doc_count，递归计数），进页面不拉文件
//   - 展开 folder → loadFolderFiles(folderId) 拉该 folder 直属文件（懒加载，folderDocs 缓存）
//   - 搜索/状态筛选 → loadSearchResults() 走后端 search/status 接口（searchResults 临时视图）
//   - 任何变更操作后：相关 folder 缓存失效 + 刷新 folder 树计数（缓存失效规则见下）
//   - 轮询：GET /documents/summary 判断是否还有非终态；有则刷新树计数 + 覆盖式重拉已展开 folder
//
// 计数一致性约定：
//   - 文件夹行"X 个文档"来自 folderTree 的 doc_count；顶部 kb 下拉"（N）"来自 kbs 的 doc_count
//   - 任何增删文档的操作（上传/删文档/删文件夹）后，必须同时刷新 loadFolderTree + loadKbs，
//     否则会出现"文件行出现了但计数不动"的界面不一致
//
// 缓存失效规则（重要）：
//   - 上传 → 目标 folder 失效；删除文档 → 所在 folder 失效；移动文件 → 源 + 目标 folder 失效
//   - 重命名/移动 folder → 该子树下所有 folder 失效（folder_path 变化）；删除 folder → 子树缓存删除
//   - 失效 = 从 folderDocs 删除 + folderLoaded 移除标记，下次展开自动重拉，不额外请求

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import type {
  DocStatus,
  DocumentItem,
  DocumentUploadResult,
  Folder,
  FolderTreeNode,
  KnowledgeBase,
  MixedFolderNode,
  MixedFileNode,
  MixedNode,
  MoveDocumentResult,
} from '../types/api'
import * as docApi from '../api/documents'
import * as folderApi from '../api/folders'
import * as kbApi from '../api/kb'

const POLL_INTERVAL_MS = 3_000
const UPLOAD_CONCURRENCY = 3 // 前端同时并发上传的文件数（后端解析并发另有信号量=2）

const IN_PROGRESS: DocStatus[] = ['pending', 'ingesting', 'embedding']
// 单 folder 直属文件一次拉取上限（项目定位 1-5 人、单 folder 内文件通常 <5000）
const FULL_PAGE_SIZE = 5_000

export const useDocumentStore = defineStore('document', () => {
  // ==================== state ====================
  const kbs = ref<KnowledgeBase[]>([])
  const currentKbId = ref<string>('default')

  // 当前选中的 folder（用于"上传到哪"+"列表筛哪个 folder"），null = kb 根（默认 folder 兜底）
  const currentFolderId = ref<string | null>(null)

  // 当前 kb 的 folder 树（含 doc_count）
  const folderTree = ref<FolderTreeNode[]>([])

  // 按 folder 缓存的直属文件（懒加载）；key = folder_id
  const folderDocs = ref<Map<string, DocumentItem[]>>(new Map())
  // 已加载标记：区分"加载过=空 folder"与"未加载"
  const folderLoaded = ref<Set<string>>(new Set())
  // 正在展开加载中的 folder（UI 显示"加载中…"）
  const loadingFolderIds = ref<Set<string>>(new Set())
  // 搜索/状态筛选结果集；null = 非搜索态（显示 folderDocs 缓存视图）
  const searchResults = ref<DocumentItem[] | null>(null)

  // 单表选中节点的 row key；folder:<folder_id> 或 doc:<doc_id>
  const currentNodeKey = ref<string | null>(null)

  // el-table 受控展开的 row keys（folder:<id>）
  const expandedKeys = ref<string[]>([])

  const page = ref(1)
  const pageSize = ref(20)
  const statusFilter = ref<DocStatus | ''>('')
  const search = ref('')

  const loading = ref(false)
  const uploading = ref(false)
  const deletingIds = ref<Set<string>>(new Set())
  const reprocessingIds = ref<Set<string>>(new Set())
  // folder 删除是异步重活（级联可能涉及多文档删除补偿），UI 上做按钮禁用
  const deletingFolderIds = ref<Set<string>>(new Set())

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let pollRequested = false

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
    currentFolderId.value = null
    currentNodeKey.value = null
    await loadFolderTree()
    return kb
  }

  async function setCurrentKb(kbId: string) {
    if (kbId === currentKbId.value) return
    currentKbId.value = kbId
    currentFolderId.value = null
    currentNodeKey.value = null
    expandedKeys.value = []
    invalidateAllFolders()
    await loadFolderTree()
  }

  // ==================== folder 树 ====================

  async function loadFolderTree(opts?: { silent?: boolean }) {
    if (!opts?.silent) loading.value = true
    try {
      const res = await folderApi.getTree(currentKbId.value)
      folderTree.value = res.items
    } catch (e) {
      ElMessage.error((e as Error).message || '文件夹树加载失败')
    } finally {
      if (!opts?.silent) loading.value = false
    }
  }

  // ==================== 文档懒加载（按 folder） ====================

  /**
   * 拉取某 folder 的直属文件并缓存。有缓存且非 force 时直接返回（复用）。
   * force=true 用于轮询刷新/变更后重拉（覆盖缓存，更新状态 tag）。
   * 加载中不弹全局遮罩，由 UI 用 loadingFolderIds 行内提示。
   */
  async function loadFolderFiles(
    folderId: string,
    opts?: { force?: boolean; silent?: boolean },
  ): Promise<DocumentItem[] | null> {
    if (!folderId) return null
    if (!opts?.force && folderLoaded.value.has(folderId)) {
      return folderDocs.value.get(folderId) ?? []
    }
    loadingFolderIds.value.add(folderId)
    try {
      const res = await docApi.list({
        kb_id: currentKbId.value,
        folder_id: folderId,
        status: '',
        search: '',
        page: 1,
        page_size: FULL_PAGE_SIZE,
      })
      folderDocs.value.set(folderId, res.items)
      folderLoaded.value.add(folderId)
      if (pollRequested && !pollTimer) schedulePoll()
      return res.items
    } catch (e) {
      ElMessage.error((e as Error).message || '文件夹文件加载失败')
      return null
    } finally {
      loadingFolderIds.value.delete(folderId)
    }
  }

  /** 按 folder 逐个加载当前 kb 全部文件（"全部加载"语义；懒加载改造前的 loadAllDocs 保留入口）。 */
  async function loadAllDocs(opts?: { silent?: boolean }) {
    const ids = collectAllFolderIds(folderTree.value)
    for (const id of ids) {
      await loadFolderFiles(id, { force: true, silent: opts?.silent })
    }
  }

  /** 搜索/状态筛选：走后端接口（跨树模糊搜索 + 状态过滤），结果写入 searchResults。 */
  async function loadSearchResults() {
    const hasFilter = Boolean(search.value || statusFilter.value)
    if (!hasFilter) {
      searchResults.value = null
      return
    }
    try {
      const res = await docApi.list({
        kb_id: currentKbId.value,
        folder_id: null,
        status: statusFilter.value,
        search: search.value,
        page: 1,
        page_size: FULL_PAGE_SIZE,
      })
      searchResults.value = res.items
    } catch (e) {
      ElMessage.error((e as Error).message || '搜索失败')
    }
  }

  // ==================== 缓存失效（变更后一致性） ====================

  function invalidateFolder(folderId: string | null | undefined) {
    if (!folderId) return
    folderDocs.value.delete(folderId)
    folderLoaded.value.delete(folderId)
  }

  /** 收集某 folder 自身 + 全部后代 folder id。 */
  function collectSubtreeFolderIds(roots: FolderTreeNode[], folderId: string): string[] {
    const out: string[] = []
    const walk = (nodes: FolderTreeNode[]): boolean => {
      for (const n of nodes) {
        if (n.folder_id === folderId) {
          out.push(n.folder_id)
          const sub = (n.children ?? []).flatMap((c) => collectSubtreeFolderIds([c], c.folder_id))
          out.push(...sub)
          return true
        }
        if (walk(n.children ?? [])) return true
      }
      return false
    }
    walk(roots)
    return out
  }

  /** 失效某 folder 及其子树下所有 folder 的缓存（重命名/移动 folder 后 folder_path 变化）。 */
  function invalidateFolderSubtree(folderId: string) {
    for (const id of collectSubtreeFolderIds(folderTree.value, folderId)) {
      invalidateFolder(id)
    }
  }

  function invalidateAllFolders() {
    folderDocs.value = new Map()
    folderLoaded.value = new Set()
    searchResults.value = null
  }

  /** 变更后统一刷新计数（folder 行 + kb 下拉）。 */
  async function refreshCounts() {
    await loadFolderTree({ silent: true })
    await loadKbs()
  }

  // ==================== 混合树（UI 方案 B：folder + file 统一一张表） ====================

  /** 合并 folderTree + folderDocs/searchResults 为统一 MixedTree；children 顺序：子 folder 在前，文件在后（按名称排序）。 */
  const mixedTree = computed<MixedNode[]>(() => {
    return folderTree.value.map((f) => buildFolderNode(f))
  })

  /** 已加载文档的摊平视图（兼容旧引用；搜索态下为命中集）。 */
  const allDocs = computed<DocumentItem[]>(() => {
    if (searchResults.value !== null) return searchResults.value
    return [...folderDocs.value.values()].flat()
  })

  function buildFolderNode(folder: FolderTreeNode): MixedFolderNode {
    const folderNode: MixedFolderNode = {
      node_type: 'folder',
      node_id: `folder:${folder.folder_id}`,
      folder_id: folder.folder_id,
      parent_id: folder.parent_id,
      name: folder.name,
      depth: folder.depth,
      is_system: folder.is_system,
      direct_doc_count: folder.doc_count,
      total_doc_count: 0, // 下面重算
      created_at: folder.created_at,
      updated_at: folder.updated_at,
      children: [],
    }
    const childFolders: MixedFolderNode[] = folder.children.map((c) => buildFolderNode(c))
    // 搜索态：文件来自 searchResults（按 folder_id 过滤）；非搜索态：来自 folderDocs 缓存
    const source =
      searchResults.value !== null
        ? searchResults.value
        : folderDocs.value.get(folder.folder_id) ?? []
    const directFiles: MixedNode[] = source
      .filter((d) => d.folder_id === folder.folder_id)
      .map((d) => toFileNode(d, folder.depth + 1))
      .sort((a, b) =>
        (a as MixedFileNode).file_name.localeCompare((b as MixedFileNode).file_name),
      )
    folderNode.children = [...childFolders, ...directFiles]
    // total = 直属（self 直挂的 file）+ 子 folder 递归总数。
    // ⚠️ self 直挂 file 已被 direct_doc_count 计入（来自后端 FolderTreeNode.doc_count），
    // reduce 这里不能再把 children 里的 file 算 +1，否则 self 直挂 file 会被算两遍。
    folderNode.total_doc_count =
      folderNode.direct_doc_count +
      folderNode.children
        .filter((c): c is MixedFolderNode => c.node_type === 'folder')
        .reduce((sum, c) => sum + c.total_doc_count, 0)
    // 搜索态：folder 行计数改为"命中 N"（本子树命中文件数，递归）
    if (searchResults.value !== null) {
      folderNode._hit_count =
        directFiles.length +
        childFolders.reduce((sum, c) => sum + (c._hit_count ?? 0), 0)
    }
    return folderNode
  }

  function toFileNode(d: DocumentItem, parentDepth: number): MixedFileNode {
    return {
      node_type: 'file',
      node_id: `doc:${d.doc_id}`,
      doc_id: d.doc_id,
      folder_id: d.folder_id ?? '',
      folder_path: d.folder_path,
      file_name: d.file_name,
      file_ext: d.file_ext,
      file_size: d.file_size,
      page_count: d.page_count,
      chunk_count: d.chunk_count,
      status: d.status,
      error: d.error,
      _depth: parentDepth,
      // 仅当 file 位于子 folder（parentDepth > 2）下才显示 folder_path 二级灰字；
      // 顶层 folder（含默认 folder）下的文件省略单段前缀，避免冗余
      _show_path: parentDepth > 2,
      created_at: d.created_at,
      updated_at: d.updated_at,
    }
  }

  /**
   * 搜索/状态筛选后的展示树：剪掉既不含目标文件、又非空文件夹的子树。
   * - 搜索：folder 行总保留（仅显示），文件需 file_name 命中；folder 名命中 → 整棵子树保留
   * - 状态：仅文件生效（folder 行不携带 status），筛选匹配的文件保留，其余隐藏
   *   * 空 folder 在状态过滤下保留展示（用户能感知"这里存在 folder"）
   */
  const displayTree = computed<MixedNode[]>(() => {
    return mixedTree.value.map((n) => pruneNode(n)).filter(Boolean) as MixedNode[]
  })

  function pruneNode(node: MixedNode): MixedNode | null {
    if (node.node_type === 'file') {
      return matchFile(node) ? node : null
    }
    const newChildren = node.children
      .map(pruneNode)
      .filter((c): c is MixedNode => Boolean(c))
    // folder 自身恒保留（即便空也要可见，便于操作）
    return { ...node, children: newChildren }
  }

  function matchFile(node: MixedNode & { node_type: 'file' }): boolean {
    if (statusFilter.value && node.status !== statusFilter.value) return false
    if (search.value) {
      const kw = search.value.toLowerCase()
      return node.file_name.toLowerCase().includes(kw)
    }
    return true
  }

  // ==================== 选中与展开 ====================

  /** 行点击：folder → 推断 currentFolderId；file → 推断 currentFolderId = 该 doc 所在 folder。 */
  function selectNode(key: string | null) {
    currentNodeKey.value = key
    if (!key) {
      currentFolderId.value = null
      return
    }
    if (key.startsWith('folder:')) {
      currentFolderId.value = key.slice('folder:'.length)
    } else if (key.startsWith('doc:')) {
      const docId = key.slice('doc:'.length)
      const d = allDocs.value.find((x) => x.doc_id === docId)
      currentFolderId.value = d?.folder_id ?? currentFolderId.value
    }
  }

  function selectFolder(folderId: string | null) {
    currentFolderId.value = folderId
    currentNodeKey.value = folderId ? `folder:${folderId}` : null
  }

  /** 展开/折叠 folder；展开且未加载时触发懒加载。 */
  function toggleExpand(key: string) {
    const expanding = !expandedKeys.value.includes(key)
    expandedKeys.value = expanding
      ? [...expandedKeys.value, key]
      : expandedKeys.value.filter((k) => k !== key)
    if (expanding && key.startsWith('folder:')) {
      void loadFolderFiles(key.slice('folder:'.length))
    }
  }

  /**
   * el-table tree 受控展开的双向同步入口：
   * 用户点击 el-table 默认展开图标时，el-table 内部切换 expand 状态并 emit 此事件；
   * 父组件必须把最新 keys 写入 prop，否则下次 prop 重渲染时强制回到原状态。
   */
  function updateExpandKeys(keys: string[]) {
    const prev = new Set(expandedKeys.value)
    expandedKeys.value = [...keys]
    for (const k of keys) {
      if (!prev.has(k) && k.startsWith('folder:')) {
        void loadFolderFiles(k.slice('folder:'.length))
      }
    }
  }

  function expandAll() {
    const keys = collectAllFolderKeys(mixedTree.value)
    expandedKeys.value = keys
    for (const k of keys) {
      if (k.startsWith('folder:')) void loadFolderFiles(k.slice('folder:'.length))
    }
  }

  function collapseAll() {
    expandedKeys.value = []
  }

  /** 默认展开顶层 folder（depth=1），子 folder 默认折叠。 */
  function expandTopFolders() {
    const keys = mixedTree.value
      .filter((n) => n.node_type === 'folder' && n.depth === 1)
      .map((n) => n.node_id)
    expandedKeys.value = keys
    for (const k of keys) {
      if (k.startsWith('folder:')) void loadFolderFiles(k.slice('folder:'.length))
    }
  }

  function collectAllFolderKeys(nodes: MixedNode[]): string[] {
    const out: string[] = []
    for (const n of nodes) {
      if (n.node_type === 'folder') {
        out.push(n.node_id)
        out.push(...collectAllFolderKeys(n.children))
      }
    }
    return out
  }

  function collectAllFolderIds(nodes: FolderTreeNode[]): string[] {
    const out: string[] = []
    for (const n of nodes) {
      out.push(n.folder_id)
      out.push(...collectAllFolderIds(n.children ?? []))
    }
    return out
  }

  // ==================== 列表（兼容保留） ====================

  /** 兼容入口：刷新 folder 树 + 按 folder 重拉全部文件（旧 UI reload 语义）。 */
  async function reload() {
    await loadFolderTree({ silent: true })
    await loadAllDocs({ silent: true })
  }

  function setStatus(status: DocStatus | '') {
    if (status === statusFilter.value) return
    statusFilter.value = status
    void loadSearchResults()
  }

  function setSearch(keyword: string) {
    search.value = keyword
    void loadSearchResults()
  }

  function setPage(p: number) {
    if (p === page.value) return
    page.value = p
  }

  // 兼容旧 ref 语义：文档总数 = 当前视图（已加载缓存 或 搜索结果）的条数
  const total = computed<number>(() => allDocs.value.length)
  // 旧 documents ref 保留兼容外部代码（已不挂 UI）
  const documents = computed<DocumentItem[]>(() => allDocs.value)

  // ==================== 上传（多文件，前端并发 3） ====================

  function hasAnyInProgress(): boolean {
    return allDocs.value.some((d) => IN_PROGRESS.includes(d.status))
  }

  /** 轻量轮询：summary 判断是否还有非终态；每轮先刷新已展开视图（收敛状态），无非终态后停止。 */
  async function pollOnce() {
    try {
      const s = await docApi.summary(currentKbId.value)
      const done = s.in_progress === 0
      try {
        await refreshCounts()
        for (const k of expandedKeys.value) {
          if (k.startsWith('folder:')) {
            await loadFolderFiles(k.slice('folder:'.length), { force: true, silent: true })
          }
        }
        if (searchResults.value !== null) await loadSearchResults()
      } catch {
        // 刷新失败不中断，下一轮重试
      }
      if (done) {
        stopPoll()
        pollRequested = false
      }
    } catch {
      return // summary 单次失败不中断，下一轮重试
    }
  }

  function schedulePoll() {
    stopPoll()
    pollTimer = setInterval(() => {
      void pollOnce()
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

  /** 上传到指定 folder；folderId 为空则进默认 folder（kb 下第一个 is_system folder）。 */
  function _resolveTargetFolderId(folderId: string | null): string | null {
    if (folderId) return folderId
    const def = folderTree.value.find((f) => f.is_system)
    return def?.folder_id ?? folderTree.value[0]?.folder_id ?? null
  }

  /** 多文件上传：分批并发（每批 3 个），登记即返回；随后刷新目标 folder + 计数 + 轮询进度。
   *  目标 folder 来自当前选中的 currentFolderId（kb 根则用默认 folder）。 */
  async function uploadFiles(files: File[]): Promise<DocumentUploadResult[]> {
    uploading.value = true
    const targetFolderId = _resolveTargetFolderId(currentFolderId.value)
    if (!targetFolderId) {
      ElMessage.warning('当前 kb 没有可用文件夹，请先创建一个')
      uploading.value = false
      return []
    }
    const results: DocumentUploadResult[] = []
    try {
      // 显式分批，避免一次性丢 100 个文件给后端
      for (let i = 0; i < files.length; i += UPLOAD_CONCURRENCY) {
        const batch = files.slice(i, i + UPLOAD_CONCURRENCY)
        const batchResults = await folderApi.uploadFiles(targetFolderId, batch)
        results.push(...batchResults)
      }
      _summarizeUploadResults(results)
      // 上传会改变文件夹行与顶部 kb 下拉的文档计数：目标 folder 缓存失效后重拉 + 刷新计数
      invalidateFolder(targetFolderId)
      await loadFolderFiles(targetFolderId)
      await refreshCounts()
      startPolling()
    } catch (e) {
      ElMessage.error((e as Error).message || '上传失败')
      throw e
    } finally {
      uploading.value = false
    }
    return results
  }

  /** 递归目录上传（webkitdirectory）。files 与 paths 一一对应。 */
  async function uploadDirectory(
    files: File[],
    paths: string[],
  ): Promise<DocumentUploadResult[]> {
    uploading.value = true
    const targetFolderId = _resolveTargetFolderId(currentFolderId.value)
    if (!targetFolderId) {
      ElMessage.warning('当前 kb 没有可用文件夹，请先创建一个')
      uploading.value = false
      return []
    }
    try {
      const res = await folderApi.uploadDirectory(targetFolderId, files, paths)
      ElMessage.success(
        `目录上传完成：${res.summary.uploaded_count} 个成功，${res.summary.rejected_count} 个失败`,
      )
      if (res.rejected.length > 0) {
        const sample = res.rejected
          .slice(0, 3)
          .map((r) => `${r.file_name}：${r.error}`)
          .join('；')
        ElMessage.warning(
          `失败明细（前 3 条）：${sample}${res.rejected.length > 3 ? '…' : ''}`,
        )
      }
      invalidateFolder(targetFolderId)
      await loadFolderFiles(targetFolderId)
      await refreshCounts()
      startPolling()
      return res.uploaded
    } catch (e) {
      ElMessage.error((e as Error).message || '目录上传失败')
      throw e
    } finally {
      uploading.value = false
    }
  }

  function _summarizeUploadResults(results: DocumentUploadResult[]) {
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
  }

  // ==================== 移动（folder 归属变更） ====================

  /** 批量移动文档到目标文件夹：只改 folder 归属（不重解析、不动向量），随后刷新树+计数+失效源/目标缓存。
   *  返回逐文件结果（moved/rejected），失败明细已通过 ElMessage 汇总提示。 */
  async function moveDocs(
    docIds: string[],
    targetFolderId: string,
  ): Promise<MoveDocumentResult[]> {
    const res = await docApi.move(docIds, targetFolderId)
    const moved = res.filter((r) => r.status === 'moved').length
    const rejected = res.filter((r) => r.status === 'rejected')
    if (rejected.length > 0) {
      const sample = rejected
        .slice(0, 3)
        .map((r) => r.error || r.doc_id)
        .join('；')
      ElMessage.warning(
        `已移动 ${moved} 个文件，${rejected.length} 个失败：${sample}${
          rejected.length > 3 ? '…' : ''
        }`,
      )
    } else if (moved > 0) {
      ElMessage.success(`已移动 ${moved} 个文件`)
    }
    // 源 folder（从已加载缓存反查）+ 目标 folder 都失效并重拉，保证再展开时看到最新归属
    const touched = new Set<string>()
    for (const [fid, docs] of folderDocs.value) {
      if (docs.some((d) => docIds.includes(d.doc_id))) touched.add(fid)
    }
    touched.add(targetFolderId)
    for (const fid of touched) {
      invalidateFolder(fid)
      await loadFolderFiles(fid)
    }
    // 移动只改变 folder 归属与 folder 行计数（kb 总文档数不变）：刷新树
    await loadFolderTree({ silent: true })
    return res
  }

  // ==================== 删除 / 重试 ====================

  async function removeDoc(docId: string) {
    deletingIds.value.add(docId)
    try {
      await docApi.remove(docId)
      // 搜索态：先从命中集移除（避免删除后残留）
      if (searchResults.value !== null) {
        searchResults.value = searchResults.value.filter((d) => d.doc_id !== docId)
      }
      // 乐观更新：从已加载缓存移除
      let affectedFolderId: string | null = null
      for (const [fid, docs] of folderDocs.value) {
        if (docs.some((d) => d.doc_id === docId)) {
          folderDocs.value.set(fid, docs.filter((d) => d.doc_id !== docId))
          affectedFolderId = fid
          break
        }
      }
      if (affectedFolderId) {
        // 所在 folder 缓存失效并立即重拉：若只清缓存不重拉，
        // 已展开 folder 的文件列表会全部消失（整页刷新才恢复）
        invalidateFolder(affectedFolderId)
        await loadFolderFiles(affectedFolderId)
      }
      if (currentNodeKey.value === `doc:${docId}`) {
        currentNodeKey.value = null
        currentFolderId.value = null
      }
      // 删除会改变文件夹行与 kb 计数，同步刷新
      await refreshCounts()
      ElMessage.success('已删除')
    } catch (e) {
      ElMessage.error((e as Error).message || '删除失败')
      throw e
    } finally {
      deletingIds.value.delete(docId)
    }
  }

  /** 批量删除：并行调单删接口，成功后统一失效并重拉受影响 folder（部分失败逐条报告）。 */
  async function removeDocs(docIds: string[]) {
    const ids = [...new Set(docIds)]
    if (ids.length === 0) return
    for (const id of ids) deletingIds.value.add(id)
    const failed: string[] = []
    try {
      await Promise.all(
        ids.map(async (id) => {
          try {
            await docApi.remove(id)
          } catch {
            failed.push(id)
          }
        }),
      )
      // 搜索态：从命中集移除已删除项
      if (searchResults.value !== null) {
        searchResults.value = searchResults.value.filter(
          (d) => !ids.includes(d.doc_id),
        )
      }
      // 受影响 folder：从缓存移除已删文档 → 失效 → 统一重拉
      const affected = new Set<string>()
      for (const [fid, docs] of folderDocs.value) {
        const rest = docs.filter((d) => !ids.includes(d.doc_id))
        if (rest.length !== docs.length) {
          folderDocs.value.set(fid, rest)
          affected.add(fid)
        }
      }
      for (const fid of affected) invalidateFolder(fid)
      await Promise.all([...affected].map((fid) => loadFolderFiles(fid)))
      // 当前选中的文档若被删，清空选中
      if (currentNodeKey.value?.startsWith('doc:')) {
        const cur = currentNodeKey.value.slice('doc:'.length)
        if (ids.includes(cur)) {
          currentNodeKey.value = null
          currentFolderId.value = null
        }
      }
      // 删除会改变文件夹行与 kb 计数，同步刷新
      await refreshCounts()
      if (failed.length > 0) {
        ElMessage.error(`删除失败 ${failed.length} 个，其余已删除`)
      } else {
        ElMessage.success(`已删除 ${ids.length} 个文件`)
      }
    } catch (e) {
      ElMessage.error((e as Error).message || '批量删除失败')
      throw e
    } finally {
      for (const id of ids) deletingIds.value.delete(id)
    }
  }

  /** 批量重试/重新解析：并行调单文档 reprocess，成功后失效重拉并启动轮询（部分失败隔离）。 */
  async function reprocessDocs(docIds: string[]) {
    const ids = [...new Set(docIds)]
    if (ids.length === 0) return
    for (const id of ids) reprocessingIds.value.add(id)
    const failed: string[] = []
    try {
      await Promise.all(
        ids.map(async (id) => {
          try {
            await docApi.reprocess(id)
          } catch {
            failed.push(id)
          }
        }),
      )
      // 受影响 folder 缓存失效并重拉（状态将变化），随后启动轮询跟踪到终态
      const affected = new Set<string>()
      for (const [fid, docs] of folderDocs.value) {
        if (docs.some((d) => ids.includes(d.doc_id))) {
          invalidateFolder(fid)
          affected.add(fid)
        }
      }
      await Promise.all([...affected].map((fid) => loadFolderFiles(fid)))
      startPolling()
      if (failed.length > 0) {
        ElMessage.error(`解析调度失败 ${failed.length} 个，其余已加入队列`)
      } else {
        ElMessage.success(`已调度 ${ids.length} 个文档解析，请稍候`)
      }
    } catch (e) {
      ElMessage.error((e as Error).message || '批量解析调度失败')
      throw e
    } finally {
      for (const id of ids) reprocessingIds.value.delete(id)
    }
  }

  async function reprocessDoc(docId: string) {
    reprocessingIds.value.add(docId)
    try {
      await docApi.reprocess(docId)
      ElMessage.success('已调度解析，请稍候')
      // 所在 folder 缓存失效重拉（状态会变化），并启动轮询
      for (const [fid, docs] of folderDocs.value) {
        if (docs.some((d) => d.doc_id === docId)) {
          invalidateFolder(fid)
          await loadFolderFiles(fid)
          break
        }
      }
      startPolling()
    } catch (e) {
      ElMessage.error((e as Error).message || '调度失败')
      throw e
    } finally {
      reprocessingIds.value.delete(docId)
    }
  }

  async function createFolder(parentId: string | null, name: string): Promise<Folder> {
    const f = await folderApi.create({
      kb_id: currentKbId.value,
      parent_id: parentId,
      name,
    })
    ElMessage.success(`已创建：${f.name}`)
    // 新 folder 无缓存，展开时自动加载；父 folder 计数变化 → 刷新树
    await loadFolderTree({ silent: true })
    return f
  }

  async function renameFolder(folderId: string, newName: string): Promise<Folder> {
    const f = await folderApi.rename(folderId, newName)
    ElMessage.success(`已重命名为：${f.name}`)
    // 重命名后 folder_path 会变，子树下所有 folder 缓存失效
    invalidateFolderSubtree(folderId)
    await loadFolderTree({ silent: true })
    return f
  }

  async function moveFolderToParent(folderId: string, parentId: string | null): Promise<Folder> {
    const f = await folderApi.move(folderId, parentId)
    // 移动后子树 folder_path 变化 + 归属变化：子树缓存失效
    invalidateFolderSubtree(folderId)
    await loadFolderTree({ silent: true })
    return f
  }

  async function deleteFolder(folderId: string) {
    deletingFolderIds.value.add(folderId)
    try {
      const res = await folderApi.remove(folderId)
      ElMessage.success(res.detail || '文件夹已删除')
      if (currentFolderId.value === folderId) currentFolderId.value = null
      if (currentNodeKey.value === `folder:${folderId}`) currentNodeKey.value = null
      // 把子树从 expandedKeys 中清理（避免行级 row 引用幽灵节点）
      const prefix = `folder:${folderId}`
      expandedKeys.value = expandedKeys.value.filter((k) => k !== prefix)
      // 子树缓存删除
      for (const id of collectSubtreeFolderIds(folderTree.value, folderId)) {
        invalidateFolder(id)
      }
      // 删除会改变 kb 总文档数，刷新树 + kb 计数
      await refreshCounts()
    } catch (e) {
      ElMessage.error((e as Error).message || '删除失败')
      throw e
    } finally {
      deletingFolderIds.value.delete(folderId)
    }
  }

  // ==================== 二次确认弹窗（业务层封装） ====================

  /** 删除 folder 二次确认：folder 内 + 子 folder 下所有文件数（含递归）。 */
  async function confirmDeleteFolder(folderId: string) {
    const folder = findFolderNode(folderTree.value, folderId)
    if (!folder) {
      ElMessage.error('文件夹不存在')
      return
    }
    const totalDocs = countFolderDocs(folder)
    const tip = totalDocs > 0
      ? `该文件夹（含子文件夹）共有 ${totalDocs} 个文档，将一并删除向量、文件与数据库记录，不可恢复。确认删除？`
      : '确认删除该空文件夹？'
    try {
      await ElMessageBox.confirm(tip, `删除文件夹「${folder.name}」`, {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
    await deleteFolder(folderId)
  }

  function findFolderNode(roots: FolderTreeNode[], id: string): FolderTreeNode | null {
    for (const n of roots) {
      if (n.folder_id === id) return n
      const sub = findFolderNode(n.children, id)
      if (sub) return sub
    }
    return null
  }

  function countFolderDocs(f: FolderTreeNode): number {
    return (
      f.doc_count + f.children.reduce((sum, c) => sum + countFolderDocs(c), 0)
    )
  }

  return {
    // state
    kbs,
    currentKbId,
    currentFolderId,
    folderTree,
    folderDocs,
    folderLoaded,
    loadingFolderIds,
    searchResults,
    allDocs,
    currentNodeKey,
    expandedKeys,
    total,
    page,
    pageSize,
    statusFilter,
    search,
    loading,
    uploading,
    deletingIds,
    reprocessingIds,
    deletingFolderIds,
    // 兼容旧字段
    documents,
    topFolders: computed<Folder[]>(() =>
      folderTree.value.map((n) => ({
        folder_id: n.folder_id,
        kb_id: n.kb_id,
        parent_id: n.parent_id,
        name: n.name,
        depth: n.depth,
        is_system: n.is_system,
        created_at: n.created_at,
        updated_at: n.updated_at,
      })),
    ),
    // computed（树状单表）
    mixedTree,
    displayTree,
    // computed
    hasAnyInProgress,
    // kb
    loadKbs,
    createKb,
    setCurrentKb,
    // folder
    loadFolderTree,
    createFolder,
    renameFolder,
    moveFolderToParent,
    deleteFolder,
    confirmDeleteFolder,
    // docs
    loadFolderFiles,
    loadAllDocs,
    loadSearchResults,
    reload, // 兼容旧 API
    setStatus,
    setSearch,
    setPage,
    // 缓存失效
    invalidateFolder,
    invalidateFolderSubtree,
    invalidateAllFolders,
    // 选中与展开
    selectNode,
    selectFolder,
    toggleExpand,
    updateExpandKeys,
    expandAll,
    expandTopFolders,
    collapseAll,
    // 上传
    uploadFiles,
    uploadDirectory,
    // doc
    moveDocs,
    removeDoc,
    removeDocs,
    reprocessDoc,
    reprocessDocs,
    // 轮询
    startPolling,
    stopPoll,
  }
})
