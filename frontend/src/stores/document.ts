// 文档管理 store：知识库维度 UI + folder 树状组织 + 列表分页/搜索/筛选 + 多文件上传（前端并发 3）
// + folder CRUD + 删除/重试 + 异步进度轮询（3s，存在非终态才轮询）
//
// 上传时序（与后端约定）：
//   upload → POST /folders/{id}/upload 登记即返回 → 后端调度器异步解析（信号量=2）
//   → 前端 startPolling 轮询 list 观察状态推进 → 全终态自动停
// 轮询终止条件：当前 kb 文档无 pending/ingesting/embedding，或页面切走（组件 unmount）
//
// folder 树（与后端约定）：
//   - kb 下挂 folder 树（最深 2 层：顶层 → 子 folder，文件在子 folder 下）
//   - 默认 folder（is_system=true）不可删，可改名
//   - 同 parent 下 folder 名唯一；同 folder 内 file 名唯一
//   - 上传前必须先选 folder（默认进默认 folder）
//
// 方案 B（混合树单表）数据流：
//   - loadFolderTree() 拉 folder 树（带 doc_count）
//   - loadAllDocs() 拉全 kb 文档（无 folder_id 过滤），写入 allDocs
//   - mixedTree（computed）合并两者；displayTree（computed）在搜索/状态过滤时剪枝
//   - 上传目标 folder 由 currentFolderId 决定（UI 选中行 → 推断）
//
// 计数一致性约定：
//   - 文件夹行"X 个文档"来自 folderTree 的 doc_count；顶部 kb 下拉"（N）"来自 kbs 的 doc_count
//   - 任何增删文档的操作（上传/删文档/删文件夹）后，必须同时刷新 loadFolderTree + loadKbs，
//     否则会出现"文件行出现了但计数不动"的界面不一致（历史 bug：uploadFiles 曾只刷 allDocs）
//   - 轮询刷新（loadAllDocs）走 silent 模式，不弹 loading 遮罩，避免页面每 3 秒"闪一下"

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
} from '../types/api'
import * as docApi from '../api/documents'
import * as folderApi from '../api/folders'
import * as kbApi from '../api/kb'

const POLL_INTERVAL_MS = 3_000
const UPLOAD_CONCURRENCY = 3 // 前端同时并发上传的文件数（后端解析并发另有信号量=2）

const IN_PROGRESS: DocStatus[] = ['pending', 'ingesting', 'embedding']
// 树状单表全量拉取上限（项目定位 1-5 人、1000-10000 文档；这里给到 20000 兜底）
const FULL_PAGE_SIZE = 20_000

export const useDocumentStore = defineStore('document', () => {
  // ==================== state ====================
  const kbs = ref<KnowledgeBase[]>([])
  const currentKbId = ref<string>('default')

  // 当前选中的 folder（用于"上传到哪"+"列表筛哪个 folder"），null = kb 根（默认 folder 兜底）
  const currentFolderId = ref<string | null>(null)

  // 当前 kb 的 folder 树（含 doc_count）
  const folderTree = ref<FolderTreeNode[]>([])

  // 全 kb 文档缓存（不分 folder；UI 单表铺开 + 前端分组挂载到 folder 节点）
  const allDocs = ref<DocumentItem[]>([])

  // 单表选中节点的 row key；folder:<folder_id> 或 doc:<doc_id>
  const currentNodeKey = ref<string | null>(null)

  // el-table 受控展开的 row keys（folder:<id>）
  const expandedKeys = ref<string[]>([])

  const total = ref(0) // 兼容历史字段；新 UI 不用，但保留避免测试 break
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
    await loadAllDocs()
    return kb
  }

  async function setCurrentKb(kbId: string) {
    if (kbId === currentKbId.value) return
    currentKbId.value = kbId
    currentFolderId.value = null
    currentNodeKey.value = null
    expandedKeys.value = []
    await loadFolderTree()
    await loadAllDocs()
  }

  // ==================== folder 树 ====================

  async function loadFolderTree() {
    try {
      const res = await folderApi.getTree(currentKbId.value)
      folderTree.value = res.items
    } catch (e) {
      ElMessage.error((e as Error).message || '文件夹树加载失败')
    }
  }

  /** 单表用：一次拉全 kb 文档（无 folder 过滤 + 大 page_size）。
   *  silent=true 时（轮询后台刷新）不弹 loading 遮罩，避免页面周期性闪烁。 */
  async function loadAllDocs(opts?: { silent?: boolean }) {
    if (!opts?.silent) loading.value = true
    try {
      const res = await docApi.list({
        kb_id: currentKbId.value,
        folder_id: null,
        status: '',
        search: '',
        page: 1,
        page_size: FULL_PAGE_SIZE,
      })
      allDocs.value = res.items
      total.value = res.total
      page.value = 1
      if (pollRequested && !pollTimer) schedulePoll()
    } catch (e) {
      ElMessage.error((e as Error).message || '文档列表加载失败')
    } finally {
      if (!opts?.silent) loading.value = false
    }
  }

  async function createFolder(parentId: string | null, name: string): Promise<Folder> {
    const f = await folderApi.create({
      kb_id: currentKbId.value,
      parent_id: parentId,
      name,
    })
    ElMessage.success(`已创建：${f.name}`)
    await loadFolderTree()
    return f
  }

  async function renameFolder(folderId: string, newName: string): Promise<Folder> {
    const f = await folderApi.rename(folderId, newName)
    ElMessage.success(`已重命名为：${f.name}`)
    await loadFolderTree()
    // 重命名后 folder_path 会变，重拉文档
    await loadAllDocs()
    return f
  }

  async function moveFolderToParent(folderId: string, parentId: string | null): Promise<Folder> {
    const f = await folderApi.move(folderId, parentId)
    await loadFolderTree()
    await loadAllDocs()
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
      await loadFolderTree()
      await loadAllDocs()
      // 删除会改变 kb 总文档数，刷新顶部 kb 计数
      await loadKbs()
    } catch (e) {
      ElMessage.error((e as Error).message || '删除失败')
      throw e
    } finally {
      deletingFolderIds.value.delete(folderId)
    }
  }

  // ==================== 混合树（UI 方案 B：folder + file 统一一张表） ====================

  /** 合并 folderTree + allDocs 为统一 MixedTree；children 顺序：子 folder 在前，文件在后（按名称排序）。 */
  const mixedTree = computed<MixedNode[]>(() => {
    return folderTree.value.map((f) => buildFolderNode(f))
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
    const directFiles: MixedNode[] = allDocs.value
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

  function toggleExpand(key: string) {
    if (expandedKeys.value.includes(key)) {
      expandedKeys.value = expandedKeys.value.filter((k) => k !== key)
    } else {
      expandedKeys.value = [...expandedKeys.value, key]
    }
  }

  /**
   * el-table tree 受控展开的双向同步入口：
   * 用户点击 el-table 默认展开图标时，el-table 内部切换 expand 状态并 emit 此事件；
   * 父组件必须把最新 keys 写入 prop，否则下次 prop 重渲染时强制回到原状态。
   */
  function updateExpandKeys(keys: string[]) {
    // el-table emit 顺序：折叠时先 emit 旧 keys（含自身），再 emit 新 keys（已剔除）；
    // 展开时反之。我们只需保留最终态，直接赋值。
    expandedKeys.value = [...keys]
  }

  function expandAll() {
    expandedKeys.value = collectAllFolderKeys(mixedTree.value)
  }

  function collapseAll() {
    expandedKeys.value = []
  }

  /** 默认展开顶层 folder（depth=1），子 folder 默认折叠。 */
  function expandTopFolders() {
    expandedKeys.value = mixedTree.value
      .filter((n) => n.node_type === 'folder' && n.depth === 1)
      .map((n) => n.node_id)
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

  // ==================== 列表（兼容保留，供 selectFolder 触发后端 list 使用） ====================
  // 旧实现里 reload 用于"右表"列表分页；UI 方案 B 下不再使用，但保留给可能的脚本调用与测试。
  async function reload() {
    await loadAllDocs()
  }

  function setStatus(status: DocStatus | '') {
    if (status === statusFilter.value) return
    statusFilter.value = status
  }

  function setSearch(keyword: string) {
    search.value = keyword
  }

  function setPage(p: number) {
    if (p === page.value) return
    page.value = p
  }

  // 旧 documents ref 保留兼容外部代码（已不挂 UI）
  const documents = computed<DocumentItem[]>(() => allDocs.value)

  // ==================== 上传（多文件，前端并发 3） ====================

  function hasAnyInProgress(): boolean {
    return allDocs.value.some((d) => IN_PROGRESS.includes(d.status))
  }

  function schedulePoll() {
    stopPoll()
    pollTimer = setInterval(() => {
      void (async () => {
        try {
          // 轮询属后台静默刷新：不弹 loading 遮罩，避免表格每 3 秒闪一下
          await loadAllDocs({ silent: true })
        } catch {
          // 轮询单次失败不中断，下一轮重试
          return
        }
        if (!hasAnyInProgress()) {
          stopPoll()
          pollRequested = false
        }
      })()
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

  /** 多文件上传：分批并发（每批 3 个），登记即返回；随后刷新列表 + 计数 + 轮询进度。
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
        await loadAllDocs()
      }
      _summarizeUploadResults(results)
      // 上传会改变文件夹行与顶部 kb 下拉的文档计数：同步刷新文件夹树与 kb 列表
      await loadFolderTree()
      await loadKbs()
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
      await loadFolderTree()
      await loadAllDocs()
      // 目录上传同样改变 kb 总文档数，刷新顶部 kb 计数
      await loadKbs()
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

  // ==================== 删除 / 重试 ====================

  async function removeDoc(docId: string) {
    deletingIds.value.add(docId)
    try {
      await docApi.remove(docId)
      // 乐观更新：从 allDocs 移除
      allDocs.value = allDocs.value.filter((d) => d.doc_id !== docId)
      total.value = Math.max(0, total.value - 1)
      if (currentNodeKey.value === `doc:${docId}`) {
        currentNodeKey.value = null
        currentFolderId.value = null
      }
      await loadAllDocs()
      // 删除会改变文件夹行与 kb 计数，同步刷新
      await loadFolderTree()
      await loadKbs()
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
      await loadAllDocs()
    } catch (e) {
      ElMessage.error((e as Error).message || '调度失败')
      throw e
    } finally {
      reprocessingIds.value.delete(docId)
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
    loadAllDocs,
    reload, // 兼容旧 API
    setStatus,
    setSearch,
    setPage,
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
    removeDoc,
    reprocessDoc,
    // 轮询
    startPolling,
    stopPoll,
  }
})
