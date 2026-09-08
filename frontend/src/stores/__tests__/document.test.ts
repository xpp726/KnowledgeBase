// document store 测试：kb 加载/切换、folder 树、列表筛选参数（含 folder_id）、上传调度轮询、终态停轮询
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDocumentStore } from '../document'
import type { DocumentItem, FolderTreeNode, KnowledgeBase } from '../../types/api'

vi.mock('../../api/documents', () => ({
  list: vi.fn(),
  remove: vi.fn(),
  reprocess: vi.fn(),
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

  it('reload 全量拉取文档（树状单表不分页，状态/搜索走前端过滤）', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    store.statusFilter = 'failed'
    store.search = '公示'
    store.page = 2
    await store.reload()
    // 状态/搜索/分页不在请求参数透传：UI 方案 B 下 always 全量（FULL_PAGE_SIZE=20000）
    expect(docApi.list).toHaveBeenLastCalledWith({
      kb_id: 'default',
      folder_id: null,
      status: '',
      search: '',
      page: 1,
      page_size: 20_000,
    })
  })

  it('切换 kb 重置 folder + 选中 + 展开键，并加载', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    store.currentNodeKey = 'folder:f_default'
    store.expandedKeys = ['folder:f_default']
    store.page = 3
    await store.setCurrentKb('kb_2')
    expect(store.currentKbId).toBe('kb_2')
    expect(store.page).toBe(1)
    expect(store.currentFolderId).toBeNull()
    expect(store.currentNodeKey).toBeNull()
    expect(store.expandedKeys).toEqual([])
    expect(docApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ kb_id: 'kb_2', page: 1 }),
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
    // 单表下文档一次性拉过即可，selectFolder 只切"上传目标"语义
    expect(docApi.list).not.toHaveBeenCalled()
  })

  it('uploadFiles 走 folderApi.uploadFiles（带 folder_id）并启动轮询（存在非终态）', async () => {
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

  it('轮询推进到全终态后停止', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(folderApi.uploadFiles).mockResolvedValue([
      { doc_id: 'd1', file_name: 'a.pdf', folder_id: 'f_default', status: 'pending', duplicated: false },
    ])
    vi.mocked(docApi.list)
      .mockResolvedValueOnce({
        items: [makeDoc({ status: 'ingesting' })],
        total: 1,
        page: 1,
        page_size: 20,
      })
      .mockResolvedValueOnce({
        items: [makeDoc({ status: 'ingesting' })],
        total: 1,
        page: 1,
        page_size: 20,
      })
      .mockResolvedValue({
        items: [makeDoc({ status: 'done' })],
        total: 1,
        page: 1,
        page_size: 20,
      })

    await store.uploadFiles([new File(['x'], 'a.pdf')])
    await vi.advanceTimersByTimeAsync(3_000)
    expect(store.documents[0].status).toBe('ingesting')
    await vi.advanceTimersByTimeAsync(3_000)
    expect(store.documents[0].status).toBe('done')
    expect(store.hasAnyInProgress()).toBe(false)
  })

  it('removeDoc 删除后回退空页并刷新', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    await store.loadFolderTree()
    vi.mocked(docApi.list)
      .mockResolvedValueOnce({
        items: [makeDoc()],
        total: 1,
        page: 1,
        page_size: 20,
      })
      .mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
    await store.reload()
    vi.mocked(docApi.remove).mockResolvedValue({ ok: true })
    await store.removeDoc('d1')
    expect(docApi.remove).toHaveBeenCalledWith('d1')
    expect(store.total).toBe(0)
  })

  it('deleteFolder 调 folderApi.remove 并刷新树+列表', async () => {
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
      page_size: 20_000,
    })
    await store.loadFolderTree()
    await store.loadAllDocs()

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