// document store 测试：kb 加载/切换、列表筛选参数、上传调度轮询、终态停轮询
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDocumentStore } from '../document'
import type { DocumentItem, KnowledgeBase } from '../../types/api'

vi.mock('../../api/documents', () => ({
  list: vi.fn(),
  upload: vi.fn(),
  remove: vi.fn(),
  reprocess: vi.fn(),
}))
vi.mock('../../api/kb', () => ({
  list: vi.fn(),
  create: vi.fn(),
}))
// node 测试环境无 DOM，element-plus message 渲染会抛错，mock 掉
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

import * as docApi from '../../api/documents'
import * as kbApi from '../../api/kb'

const KBS: KnowledgeBase[] = [
  {
    kb_id: 'default',
    name: '默认知识库',
    description: '',
    doc_count: 3,
    created_at: 1,
    updated_at: 2,
  },
  {
    kb_id: 'kb_2',
    name: '研发资料',
    description: '',
    doc_count: 0,
    created_at: 1,
    updated_at: 2,
  },
]

function makeDoc(over: Partial<DocumentItem> = {}): DocumentItem {
  return {
    doc_id: 'd1',
    kb_id: 'default',
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

  it('reload 按当前 kb/状态/搜索/分页传参', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    store.statusFilter = 'failed'
    store.search = '公示'
    store.page = 2
    await store.reload()
    expect(docApi.list).toHaveBeenCalledWith({
      kb_id: 'default',
      status: 'failed',
      search: '公示',
      page: 2,
      page_size: 20,
    })
  })

  it('切换 kb 重置到第一页并加载', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    store.page = 3
    await store.setCurrentKb('kb_2')
    expect(store.currentKbId).toBe('kb_2')
    expect(store.page).toBe(1)
    expect(docApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ kb_id: 'kb_2', page: 1 }),
    )
  })

  it('uploadFiles 批量上传后启动轮询（存在非终态）', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    vi.mocked(docApi.upload).mockResolvedValue([
      { doc_id: 'd1', file_name: 'a.pdf', status: 'pending', duplicated: false },
    ])
    vi.mocked(docApi.list).mockResolvedValue({
      items: [makeDoc({ status: 'ingesting' })],
      total: 1,
      page: 1,
      page_size: 20,
    })

    await store.uploadFiles([new File(['x'], 'a.pdf'), new File(['y'], 'b.pdf')])
    expect(docApi.upload).toHaveBeenCalledTimes(1) // 2 文件 < 并发 3，一批
    expect(store.uploading).toBe(false)
    // 轮询定时器已建立（fake timers 下 setInterval 挂起）
    expect(store.hasAnyInProgress()).toBe(true)
  })

  it('轮询推进到全终态后停止', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
    // 第一次上传后状态为 ingesting → 轮询；下一轮返回 done → 停止
    vi.mocked(docApi.upload).mockResolvedValue([
      { doc_id: 'd1', file_name: 'a.pdf', status: 'pending', duplicated: false },
    ])
    vi.mocked(docApi.list)
      // uploadFiles 内部 silent reload + 轮询第一轮 → ingesting
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
      // 轮询第二轮 → done
      .mockResolvedValue({
        items: [makeDoc({ status: 'done' })],
        total: 1,
        page: 1,
        page_size: 20,
      })

    await store.uploadFiles([new File(['x'], 'a.pdf')])
    // 第一轮轮询：仍非终态 → 保持
    await vi.advanceTimersByTimeAsync(3_000)
    expect(store.documents[0].status).toBe('ingesting')
    // 第二轮：done → 停
    await vi.advanceTimersByTimeAsync(3_000)
    expect(store.documents[0].status).toBe('done')
    expect(store.hasAnyInProgress()).toBe(false)
  })

  it('removeDoc 删除后回退空页并刷新', async () => {
    const store = useDocumentStore()
    await store.loadKbs()
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
})
