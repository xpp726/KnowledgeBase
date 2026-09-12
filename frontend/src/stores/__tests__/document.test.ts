// document store 测试：kb 加载/切换、folder 树、按 folder 懒加载、搜索走后端、缓存失效、上传调度轮询、终态停轮询
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDocumentStore } from '../document'
import type { DocumentItem, DocumentSummary, FolderTreeNode, KnowledgeBase } from '../../types/api'

vi.mock('../../api/documents', () => ({
  list: vi.fn(),
  summary: vi.fn(),
  remove: vi.fn(),
  reprocess: vi.fn(),
  move: vi.fn(),
}))
vi.mock('../../api/folders', () => ({
  getTree: vi.fn(),
  create: vi.fn(),
  rename: vi.fn(),
  move: vi.fn(),
  remove: vi.fn(),
  uploadFiles: vi.fn(),
  uploadDirectory: vi.fn(),
}))
vi.mock('../../api/kb', () => ({
  list: vi.fn(),
  create: vi.fn(),
}))
// node 测试环境无 DOM，element-plus message 渲染会抛错，mock 掉
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  ElMessageBox: { confirm: vi.fn().mockResolvedValue('ok') },
}))

import * as docApi from '../../api/documents'
import * as folderApi from '../../api/folders'
import * as kbApi from '../../api/kb'

const KBS: KnowledgeBase[] = [
  { kb_id: 'default', name: '默认知识库', description: '', doc_count: 3, created_at: 1, updated_at: 2 },
  { kb_id: 'kb_2', name: '研发资料', description: '', doc_count: 0, created_at: 1, updated_at: 2 },
]

const FOLDER_TREE: FolderTreeNode[] = [
  {
    folder_id: 'f_default',
    kb_id: 'default',
    parent_id: null,
    name: '默认文件夹',
    depth: 1,
    is_system: true,
    created_at: 1,
    updated_at: 2,
    doc_count: 0,
    children: [],
  },
]

function makeDoc(over: Partial<DocumentItem> = {}): DocumentItem {
  return {
    doc_id: 'd1',
    kb_id: 'default',
    folder_id: 'f_default',
    folder_path: '默认文件夹',
    file_name: 'a.pdf',
    file_ext: '.pdf',
    file_size: 100,
    page_count: 0,
    chunk_count: 0,
    table_chunks: 0,
    status: 'done',
    error: '',
    created_at: 1,
    updated_at: 2,
    ...over,
  }
}

function summaryOf(in_progress: number): DocumentSummary {
  return {
    total: in_progress,
    pending: 0,
    ingesting: in_progress,
    embedding: 0,
    done: 0,
    failed: 0,
    in_progress,
  }
}

describe('document store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.clearAllMocks()
    vi.mocked(docApi.list).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    })
    vi.mocked(docApi.summary).mockResolvedValue(summaryOf(0))
    vi.mocked(kbApi.list).mockResolvedValue(KBS)
    vi.mocked(folderApi.getTree).mockResolvedValue({ items: FOLDER_TREE })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loadKbs 设置列表并保持当前 kb 有效', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    expect(store.kbs).toHaveLength(2)
    expect(store.currentKbId).toBe('default')
  })

  it('loadFolderFiles 按 folder 懒加载（不进页面全量拉取）', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    // 未展开任何 folder 前，不请求文档列表
    expect(docApi.list).not.toHaveBeenCalled()
    const docs = await store.loadFolderFiles('f_default')
    expect(docApi.list).toHaveBeenLastCalledWith({
      kb_id: 'default',
      folder_id: 'f_default',
      status: '',
      search: '',
      page: 1,
      page_size: 5_000,
    })
    expect(store.folderLoaded.has('f_default')).toBe(true)
    expect(docs).toEqual([])
    // 有缓存时再次加载不重复请求
    vi.mocked(docApi.list).mockClear()
    await store.loadFolderFiles('f_default')
    expect(docApi.list).not.toHaveBeenCalled()
  })

  it('切换 kb 重置 folder + 选中 + 展开键 + 清空缓存，并加载新 kb 树', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    await store.loadFolderFiles('f_default')
    store.currentNodeKey = 'folder:f_default'
    store.expandedKeys = ['folder:f_default']
    await store.setCurrentKb('kb_2')
    expect(store.currentKbId).toBe('kb_2')
    expect(store.currentFolderId).toBeNull()
    expect(store.currentNodeKey).toBeNull()
    expect(store.expandedKeys).toEqual([])
    // 切 kb 后旧 folder 缓存清空、不自动拉文件（懒加载）
    expect(store.folderLoaded.has('f_default')).toBe(false)
    expect(docApi.list).not.toHaveBeenCalledWith(
      expect.objectContaining({ kb_id: 'kb_2', folder_id: 'f_default' }),
    )
    expect(folderApi.getTree).toHaveBeenLastCalledWith('kb_2')
  })

  it('selectFolder 只更新 currentFolderId/currentNodeKey，不再触发后端 reload（树状单表）', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(docApi.list).mockClear()
    store.selectFolder('f_default')
    expect(store.currentFolderId).toBe('f_default')
    expect(store.currentNodeKey).toBe('folder:f_default')
    expect(docApi.list).not.toHaveBeenCalled()
  })

  it('搜索/状态筛选走后端接口，清空后恢复缓存视图', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(docApi.list).mockResolvedValue({
      items: [makeDoc({ doc_id: 'hit1', file_name: '中标公示.pdf', status: 'done' })],
      total: 1,
      page: 1,
      page_size: 5_000,
    })
    store.search = '公示'
    await store.loadSearchResults()
    expect(docApi.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ kb_id: 'default', folder_id: null, search: '公示' }),
    )
    expect(store.searchResults).toHaveLength(1)
    // 清空搜索 → 恢复缓存视图
    store.search = ''
    await store.loadSearchResults()
    expect(store.searchResults).toBeNull()
  })

  it('uploadFiles 走 folderApi.uploadFiles（带 folder_id）并刷新目标 folder + 启动轮询（存在非终态）', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(folderApi.uploadFiles).mockResolvedValue([
      { doc_id: 'd1', file_name: 'a.pdf', folder_id: 'f_default', status: 'pending', duplicated: false },
    ])
    vi.mocked(docApi.list).mockResolvedValue({
      items: [makeDoc({ status: 'ingesting' })],
      total: 1,
      page: 1,
      page_size: 20,
    })

    await store.uploadFiles([new File(['x'], 'a.pdf'), new File(['y'], 'b.pdf')])
    // 默认 folder 应自动解析为 f_default（folder_tree 里唯一的 system folder）
    expect(folderApi.uploadFiles).toHaveBeenCalledWith('f_default', expect.any(Array))
    expect(folderApi.uploadFiles).toHaveBeenCalledTimes(1) // 2 文件 < 并发 3，一批
    expect(store.uploading).toBe(false)
    // 上传后目标 folder 缓存失效并重拉 → 已加载数据含非终态
    expect(store.folderDocs.get('f_default')?.[0]?.status).toBe('ingesting')
    expect(store.hasAnyInProgress()).toBe(true)
  })

  it('uploadDirectory 调用 folderApi.uploadDirectory', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(folderApi.uploadDirectory).mockResolvedValue({
      uploaded: [
        { doc_id: 'd1', file_name: 'a.pdf', folder_id: 'f_x', status: 'pending', duplicated: false, path: 'a.pdf' },
      ],
      rejected: [],
      summary: { uploaded_count: 1, rejected_count: 0, created_folder_ids: [] },
    })
    await store.uploadDirectory([new File(['x'], 'a.pdf')], ['a.pdf'])
    expect(folderApi.uploadDirectory).toHaveBeenCalledWith(
      'f_default',
      expect.any(Array),
      ['a.pdf'],
    )
  })

  it('轮询：summary 判断非终态，收敛刷新已展开 folder 后停止', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(folderApi.uploadFiles).mockResolvedValue([
      { doc_id: 'd1', file_name: 'a.pdf', folder_id: 'f_default', status: 'pending', duplicated: false },
    ])
    // 上传后目标 folder 首次拉取 → ingesting
    vi.mocked(docApi.list)
      .mockResolvedValueOnce({
        items: [makeDoc({ status: 'ingesting' })],
        total: 1,
        page: 1,
        page_size: 20,
      })
      // 轮询收敛刷新（展开状态下重拉）→ 逐轮推进
      .mockResolvedValueOnce({
        items: [makeDoc({ status: 'ingesting' })],
        total: 1,
        page: 1,
        page_size: 20,
      })
      .mockResolvedValueOnce({
        items: [makeDoc({ status: 'done' })],
        total: 1,
        page: 1,
        page_size: 20,
      })
    vi.mocked(docApi.summary)
      .mockResolvedValueOnce(summaryOf(1))
      .mockResolvedValue(summaryOf(0))

    await store.uploadFiles([new File(['x'], 'a.pdf')])
    // 展开默认 folder，让轮询能收敛刷新其文件
    store.toggleExpand('folder:f_default')
    await vi.advanceTimersByTimeAsync(3_000)
    expect(store.documents[0].status).toBe('ingesting')
    await vi.advanceTimersByTimeAsync(3_000)
    expect(store.documents[0].status).toBe('done')
    expect(store.hasAnyInProgress()).toBe(false)
    expect(store.searchResults).toBeNull()
  })

  it('removeDoc 删除后从缓存移除并刷新计数', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(docApi.list)
      .mockResolvedValueOnce({
        items: [makeDoc()],
        total: 1,
        page: 1,
        page_size: 5_000,
      })
      .mockResolvedValueOnce({
        items: [],
        total: 0,
        page: 1,
        page_size: 5_000,
      })
    await store.loadFolderFiles('f_default')
    vi.mocked(docApi.remove).mockResolvedValue({ ok: true })
    await store.removeDoc('d1')
    expect(docApi.remove).toHaveBeenCalledWith('d1')
    expect(store.total).toBe(0)
    // 删除后所在 folder 缓存失效并立即重拉（已展开 folder 列表不显示为空）
    expect(store.folderLoaded.has('f_default')).toBe(true)
    expect(store.folderDocs.get('f_default')).toEqual([])
  })

  it('removeDocs 批量删除后统一失效并重拉受影响 folder', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(docApi.list)
      .mockResolvedValueOnce({
        items: [makeDoc(), makeDoc({ doc_id: 'd2', file_name: 'b.pdf' })],
        total: 2,
        page: 1,
        page_size: 5_000,
      })
      .mockResolvedValueOnce({
        items: [],
        total: 0,
        page: 1,
        page_size: 5_000,
      })
    await store.loadFolderFiles('f_default')
    vi.mocked(docApi.remove).mockResolvedValue({ ok: true })
    await store.removeDocs(['d1', 'd2'])
    expect(docApi.remove).toHaveBeenCalledTimes(2)
    expect(store.total).toBe(0)
    // 删除后所在 folder 缓存失效并统一重拉
    expect(store.folderLoaded.has('f_default')).toBe(true)
    expect(store.folderDocs.get('f_default')).toEqual([])
  })

  it('removeDocs 部分失败时成功项仍更新缓存并报告失败', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(docApi.list)
      .mockResolvedValueOnce({
        items: [makeDoc(), makeDoc({ doc_id: 'd2', file_name: 'b.pdf' })],
        total: 2,
        page: 1,
        page_size: 5_000,
      })
      .mockResolvedValueOnce({
        items: [makeDoc({ doc_id: 'd2', file_name: 'b.pdf' })],
        total: 1,
        page: 1,
        page_size: 5_000,
      })
    await store.loadFolderFiles('f_default')
    vi.mocked(docApi.remove)
      .mockResolvedValueOnce({ ok: true })
      .mockRejectedValueOnce(new Error('模拟删除失败'))
    await store.removeDocs(['d1', 'd2'])
    expect(docApi.remove).toHaveBeenCalledTimes(2)
    // d1 成功：仍会失效并重拉（重拉返回剩余 d2）
    expect(store.folderLoaded.has('f_default')).toBe(true)
    expect(store.folderDocs.get('f_default')).toHaveLength(1)
  })

  it('reprocessDocs 批量调度并失效重拉', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(docApi.list)
      .mockResolvedValueOnce({
        items: [makeDoc(), makeDoc({ doc_id: 'd2', file_name: 'b.pdf' })],
        total: 2,
        page: 1,
        page_size: 5_000,
      })
      .mockResolvedValueOnce({
        items: [makeDoc(), makeDoc({ doc_id: 'd2', file_name: 'b.pdf' })],
        total: 2,
        page: 1,
        page_size: 5_000,
      })
    await store.loadFolderFiles('f_default')
    vi.mocked(docApi.reprocess).mockResolvedValue({ doc_id: 'd1', status: 'scheduled' })
    await store.reprocessDocs(['d1', 'd2'])
    expect(docApi.reprocess).toHaveBeenCalledTimes(2)
    // 缓存失效并重拉（状态将变化）
    expect(store.folderLoaded.has('f_default')).toBe(true)
    expect(store.folderDocs.get('f_default')).toHaveLength(2)
  })

  it('reprocessDocs 部分失败时成功项仍调度', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(docApi.list)
      .mockResolvedValueOnce({
        items: [makeDoc(), makeDoc({ doc_id: 'd2', file_name: 'b.pdf' })],
        total: 2,
        page: 1,
        page_size: 5_000,
      })
      .mockResolvedValueOnce({
        items: [makeDoc(), makeDoc({ doc_id: 'd2', file_name: 'b.pdf' })],
        total: 2,
        page: 1,
        page_size: 5_000,
      })
    await store.loadFolderFiles('f_default')
    vi.mocked(docApi.reprocess)
      .mockResolvedValueOnce({ doc_id: 'd1', status: 'scheduled' })
      .mockRejectedValueOnce(new Error('调度失败'))
    await store.reprocessDocs(['d1', 'd2'])
    expect(docApi.reprocess).toHaveBeenCalledTimes(2)
    // 失败项不影响成功项：缓存仍重拉
    expect(store.folderLoaded.has('f_default')).toBe(true)
  })

  it('moveDocs 调 docApi.move 并失效源/目标 folder 缓存 + 刷新树', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    // 源 folder 已加载（含待移动文件）
    vi.mocked(docApi.list).mockResolvedValue({
      items: [makeDoc({ doc_id: 'd1' }), makeDoc({ doc_id: 'd2' })],
      total: 2,
      page: 1,
      page_size: 5_000,
    })
    await store.loadFolderFiles('f_default')
    vi.mocked(docApi.move).mockResolvedValue([
      { doc_id: 'd1', status: 'moved' },
      { doc_id: 'd2', status: 'rejected', error: '目标文件夹已存在同名文件「b.pdf」' },
    ])
    vi.mocked(folderApi.getTree).mockClear()
    vi.mocked(docApi.list).mockClear()

    const res = await store.moveDocs(['d1', 'd2'], 'f_default')
    expect(docApi.move).toHaveBeenCalledWith(['d1', 'd2'], 'f_default')
    expect(res).toHaveLength(2)
    // 源 folder（f_default）+ 目标 folder（f_default）缓存失效并重拉；树刷新
    expect(docApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ folder_id: 'f_default' }),
    )
    expect(folderApi.getTree).toHaveBeenCalled()
  })

  it('deleteFolder 调 folderApi.remove 并刷新树+计数', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(folderApi.remove).mockResolvedValue({ ok: true, detail: 'deleted' })
    await store.deleteFolder('f_default')
    expect(folderApi.remove).toHaveBeenCalledWith('f_default')
    expect(folderApi.getTree).toHaveBeenCalled()
    // 删的是当前选中 folder → currentFolderId 应回到 null
    expect(store.currentFolderId).toBeNull()
  })

  it('mixedTree.total_doc_count = direct + 子 folder 汇总（不双计 self 直挂 file）', async () => {
    const store = useDocumentStore()
    // 构造复杂树：顶层 folder 含 3 个 self 直挂 file + 1 个子 folder（含 2 个 file）
    vi.mocked(folderApi.getTree).mockResolvedValue({
      items: [
        {
          folder_id: 'f_top',
          kb_id: 'default',
          parent_id: null,
          name: '顶级',
          depth: 1,
          is_system: true,
          created_at: 1,
          updated_at: 2,
          doc_count: 3, // ← 直属 3 文件
          children: [
            {
              folder_id: 'f_sub',
              kb_id: 'default',
              parent_id: 'f_top',
              name: '子级',
              depth: 2,
              is_system: false,
              created_at: 1,
              updated_at: 2,
              doc_count: 2, // ← 子 folder 直属 2 文件
              children: [],
            },
          ],
        },
      ],
    })
    vi.mocked(docApi.list).mockResolvedValue({
      items: [
        makeDoc({ doc_id: 'd1', folder_id: 'f_top', file_name: 'a.pdf' }),
        makeDoc({ doc_id: 'd2', folder_id: 'f_top', file_name: 'b.pdf' }),
        makeDoc({ doc_id: 'd3', folder_id: 'f_top', file_name: 'c.pdf' }),
        makeDoc({ doc_id: 'd4', folder_id: 'f_sub', file_name: 'd.pdf' }),
        makeDoc({ doc_id: 'd5', folder_id: 'f_sub', file_name: 'e.pdf' }),
      ],
      total: 5,
      page: 1,
      page_size: 5_000,
    })
    await store.loadFolderTree()
    // 懒加载：逐个展开/加载 folder
    await store.loadFolderFiles('f_top')
    await store.loadFolderFiles('f_sub')

    const top = store.mixedTree.find(
      (n): n is import('../../types/api').MixedFolderNode =>
        n.node_type === 'folder' && n.folder_id === 'f_top',
    )!
    const sub = top.children.find(
      (n): n is import('../../types/api').MixedFolderNode =>
        n.node_type === 'folder' && n.folder_id === 'f_sub',
    )!

    // 子 folder: 直挂 2 + 无子 folder → 2
    expect(sub.total_doc_count).toBe(2)
    // 顶层 folder: 直挂 3 + 子 folder 总数 2 = 5（不是 2 倍！）
    expect(top.total_doc_count).toBe(5)
    // 直挂数（用于显示"直属 X"标签）
    expect(top.direct_doc_count).toBe(3)
    expect(sub.direct_doc_count).toBe(2)
  })
})
