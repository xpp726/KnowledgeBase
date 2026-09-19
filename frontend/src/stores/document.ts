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
import { useDocumentActions } from '../composables/useDocumentActions'
import { useDocumentTree } from '../composables/useDocumentTree'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'
import { useDocumentUpload } from '../composables/useDocumentUpload'
import type {
  DocStatus,
  DocumentItem,
  Folder,
  FolderTreeNode,
  KnowledgeBase,
  MixedFolderNode,
  MixedFileNode,
  MixedNode,
} from '../types/documents'
import { confirmDialog, notify } from '../services/feedback'

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
  const documentTree = useDocumentTree({
    currentKbId,
    folderTree,
    folderDocs,
    folderLoaded,
    loadingFolderIds,
    searchResults,
    statusFilter,
    search,
    loading,
  })
  const {
    loadFolderTree,
    loadFolderFiles,
    loadAllDocs,
    loadSearchResults,
    invalidateFolder,
    invalidateFolderSubtree,
    invalidateAllFolders,
  } = documentTree

  /** 变更后统一刷新计数（folder 行 + kb 下拉）。 */
  async function refreshCounts() {
    await loadFolderTree({ silent: true })
    await loadKbs()
  }

  const knowledgeBase = useKnowledgeBase({
    kbs,
    currentKbId,
    currentFolderId,
    currentNodeKey,
    expandedKeys,
    invalidateAllFolders,
    loadFolderTree,
  })
  const { loadKbs, createKb, setCurrentKb } = knowledgeBase

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

  const uploadFlow = useDocumentUpload({
    currentKbId,
    currentFolderId,
    folderTree,
    expandedKeys,
    searchResults,
    allDocs: () => allDocs.value,
    loadFolderFiles,
    loadSearchResults,
    refreshCounts,
    invalidateFolder,
  })
  const {
    uploading,
    hasAnyInProgress,
    startPolling,
    stopPolling,
    uploadFiles,
    uploadDirectory,
  } = uploadFlow

  const actions = useDocumentActions({
    currentKbId,
    currentFolderId,
    currentNodeKey,
    expandedKeys,
    folderTree,
    folderDocs,
    searchResults,
    loadFolderTree,
    loadFolderFiles,
    refreshCounts,
    invalidateFolder,
    invalidateFolderSubtree,
    startPolling,
  })
  const {
    deletingIds,
    reprocessingIds,
    deletingFolderIds,
    moveDocs,
    removeDoc,
    removeDocs,
    reprocessDoc,
    reprocessDocs,
    createFolder,
    renameFolder,
    moveFolderToParent,
    deleteFolder,
  } = actions

  // ==================== 二次确认弹窗（业务层封装） ====================

  /** 删除 folder 二次确认：folder 内 + 子 folder 下所有文件数（含递归）。 */
  async function confirmDeleteFolder(folderId: string) {
    const folder = findFolderNode(folderTree.value, folderId)
    if (!folder) {
      notify.error('文件夹不存在')
      return
    }
    const totalDocs = countFolderDocs(folder)
    const tip = totalDocs > 0
      ? `该文件夹（含子文件夹）共有 ${totalDocs} 个文档，将一并删除向量、文件与数据库记录，不可恢复。确认删除？`
      : '确认删除该空文件夹？'
    try {
      await confirmDialog(tip, `删除文件夹「${folder.name}」`, {
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
    stopPoll: stopPolling,
  }
})
