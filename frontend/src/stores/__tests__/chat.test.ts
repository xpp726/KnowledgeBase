import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ChatMode, Conversation } from '../../types/api'
import type { SseClient, SseHandlers, SseOptions } from '../../api/sse'

vi.mock('../../api/conversation', () => ({
  list: vi.fn(),
  create: vi.fn(),
  rename: vi.fn(),
  remove: vi.fn(),
  messages: vi.fn(),
}))

vi.mock('../../api/chat', () => ({
  streamChat: vi.fn(),
}))

vi.mock('../auth', () => ({
  useAuthStore: () => ({
    token: 'test-token',
    currentUser: null,
    logout: vi.fn(),
    isAdmin: () => false,
    isEditor: () => true,
    canEditDocuments: () => true,
  }),
}))

import * as convApi from '../../api/conversation'
import { streamChat } from '../../api/chat'
import { useChatStore } from '../chat'

// ---------- fake SseClient（手动驱动 handlers，模拟真实 sse 行为） ----------

interface FakeSse {
  handlers: SseHandlers | null
  abort: ReturnType<typeof vi.fn>
  done: Promise<void>
  emit(event: string, data: unknown): void
  fail(err: { kind: string; status?: number }): void
  finish(): void
}

function createFakeSse(): FakeSse {
  let resolveDone!: () => void
  const done = new Promise<void>((resolve) => {
    resolveDone = resolve
  })
  const fake: FakeSse = {
    handlers: null,
    abort: vi.fn(),
    done,
    emit(event, data) {
      fake.handlers?.onEvent(event, data)
    },
    fail(err) {
      fake.handlers?.onError?.(err as never)
    },
    finish() {
      fake.handlers?.onClose?.()
      resolveDone()
    },
  }
  return fake
}

let activeFake: FakeSse | null = null

function mockStreamChat() {
  vi.mocked(streamChat).mockImplementation(
    (_params, handlers: SseHandlers, opts?: SseOptions) => {
      const fake = createFakeSse()
      activeFake = fake
      fake.handlers = handlers
      // 模拟 sse.ts 的外部 signal 联动：abort → onError({kind:'aborted'})
      if (opts?.signal) {
        opts.signal.addEventListener(
          'abort',
          () => {
            fake.handlers?.onError?.({ kind: 'aborted' })
          },
          { once: true },
        )
      }
      return fake as unknown as SseClient
    },
  )
}

const conv = (id: string, title = '', mode: ChatMode = 'kb'): Conversation => ({
  id,
  kb_id: 'default',
  mode,
  title,
  created_at: 1,
  updated_at: 1,
})

const ref = (index: number) => ({
  index,
  chunk_id: `k${index}`,
  doc_id: 'd1',
  doc_name: 'a.md',
  page: 1,
  score: 0.9,
  text: '引用文本',
})

beforeEach(() => {
  setActivePinia(createPinia())
  activeFake = null
  vi.clearAllMocks()
  vi.mocked(convApi.list).mockResolvedValue([conv('c1', '旧会话')])
  vi.mocked(convApi.create).mockResolvedValue(conv('c_new'))
  vi.mocked(convApi.rename).mockImplementation(async (id, title) =>
    conv(id, title),
  )
  vi.mocked(convApi.remove).mockResolvedValue(undefined)
  vi.mocked(convApi.messages).mockResolvedValue([])
  mockStreamChat()
})

describe('stores/chat 流状态机与事件映射', () => {
  it('⑧ send→connecting→(meta)→streaming→(delta/refs)→(done)→idle 全迁移', async () => {
    const store = useChatStore()
    await store.switchConversation('c1') // 已有当前会话，send 不懒建
    const p = store.sendMessage('你好')

    expect(store.streamState).toBe('connecting')
    expect(store.messages).toHaveLength(2)
    expect(store.messages[0].role).toBe('user')
    expect(store.messages[1].streaming).toBe(true)

    const fake = activeFake!
    fake.emit('meta', { conversation_id: 'c1', is_new: false })
    expect(store.streamState).toBe('streaming')

    fake.emit('delta', { content: '你' })
    fake.emit('delta', { content: '好' })
    fake.emit('references', { sources: [ref(1), ref(2)] })
    fake.emit('done', {
      conversation_id: 'c1',
      message_id: 'm1',
      hit_count: 2,
      elapsed: 2.5,
      retrieval_ms: 100,
      llm_ms: 2400,
    })
    fake.finish()
    await p

    expect(store.streamState).toBe('idle')
    expect(store.messages[1].content).toBe('你好')
    expect(store.messages[1].refs).toHaveLength(2)
    expect(store.messages[1].meta).toMatchObject({
      messageId: 'm1',
      hitCount: 2,
      retrievalMs: 100,
      llmMs: 2400,
    })
    expect(store.messages[1].streaming).toBe(false)
    expect(store.controller).toBeNull()
  })

  it('⑨a 未出 delta 的 error：消息标错 + streamState=error，done 补发后回 idle 且 meta 仍固化', async () => {
    const store = useChatStore()
    await store.switchConversation('c1')
    const p = store.sendMessage('问题')
    const fake = activeFake!
    fake.emit('meta', { conversation_id: 'c1', is_new: false })
    fake.emit('error', { stage: 'retrieval', message: 'milvus 连接失败' })
    fake.emit('done', {
      conversation_id: 'c1',
      message_id: '',
      hit_count: 0,
      elapsed: 1,
      retrieval_ms: 0,
      llm_ms: 0,
    })
    fake.finish()
    await p

    const msg = store.messages[1]
    expect(msg.error).toContain('retrieval')
    expect(msg.content).toBe('')
    expect(msg.meta?.hitCount).toBe(0) // error 后补发的 done 仍固化
    expect(store.streamState).toBe('idle')
  })

  it('⑨b 已出 delta 的 error：内容保留 + 错误尾巴，无 done 时保持 error', async () => {
    const store = useChatStore()
    await store.switchConversation('c1')
    const p = store.sendMessage('问题')
    const fake = activeFake!
    fake.emit('meta', { conversation_id: 'c1', is_new: false })
    fake.emit('delta', { content: '部分回答' })
    fake.emit('error', { stage: 'llm', message: '生成失败' })
    fake.finish()
    await p

    const msg = store.messages[1]
    expect(msg.content).toBe('部分回答')
    expect(msg.error).toContain('生成失败')
    expect(store.streamState).toBe('error')
  })

  it('⑩ 停止生成：abort → 消息 stopped 占位（不写库）+ streamState=stopped', async () => {
    const store = useChatStore()
    await store.switchConversation('c1')
    const p = store.sendMessage('问题')
    const fake = activeFake!
    fake.emit('meta', { conversation_id: 'c1', is_new: false })
    fake.emit('delta', { content: '部分' })

    store.stopGeneration()

    const msg = store.messages[1]
    expect(msg.stopped).toBe(true)
    expect(msg.streaming).toBe(false)
    expect(store.streamState).toBe('stopped')
    // 不写库：停止不触发任何回写/重发动作
    const callsBefore = vi.mocked(convApi.messages).mock.calls.length
    expect(vi.mocked(streamChat).mock.calls.length).toBe(1)
    expect(vi.mocked(convApi.messages).mock.calls.length).toBe(callsBefore)
    fake.finish()
    await p
  })

  it('⑪ 重试：移除失败对，复用 pendingQuestion 重建流', async () => {
    const store = useChatStore()
    await store.switchConversation('c1')
    const p = store.sendMessage('原始问题')
    let fake = activeFake!
    fake.emit('meta', { conversation_id: 'c1', is_new: false })
    fake.emit('error', { stage: 'llm', message: 'boom' })
    fake.finish()
    await p

    expect(store.messages[store.messages.length - 1].error).toBeTruthy()
    expect(vi.mocked(streamChat)).toHaveBeenCalledTimes(1)

    store.retryLast()
    fake = activeFake! // 第二次流

    expect(vi.mocked(streamChat)).toHaveBeenCalledTimes(2)
    expect(vi.mocked(streamChat).mock.calls[1][0].question).toBe('原始问题')
    expect(store.messages).toHaveLength(2) // 失败对已移除，重建一对
    expect(store.messages[0].content).toBe('原始问题')
    expect(store.messages[1].streaming).toBe(true)
  })

  it('⑫ 切换会话：取消在途流（abort）并加载目标历史', async () => {
    const store = useChatStore()
    await store.switchConversation('c1')
    void store.sendMessage('问题')
    const fake = activeFake!
    fake.emit('meta', { conversation_id: 'c1', is_new: false })
    fake.emit('delta', { content: '进行中' })

    vi.mocked(convApi.messages).mockResolvedValue([
      {
        id: 'm1',
        conversation_id: 'c2',
        role: 'user',
        content: '旧问',
        refs: [],
        created_at: 1,
      },
      {
        id: 'm2',
        conversation_id: 'c2',
        role: 'assistant',
        content: '旧答',
        refs: [ref(1)],
        created_at: 2,
      },
    ])

    await store.switchConversation('c2')

    expect(store.currentId).toBe('c2')
    expect(store.messages).toHaveLength(2)
    expect(store.messages[1].refs).toHaveLength(1)
    expect(store.streamState).toBe('idle')
    expect(store.controller).toBeNull()
    // 在途流被终止：原流消息不会继续追加
    fake.emit('delta', { content: '残留' })
    expect(store.messages[1].content).toBe('旧答')
  })

  it('⑬ 无会话时 send 懒建会话（后端新建 title=question，mode 随当前模式）', async () => {
    const store = useChatStore()
    const p = store.sendMessage('第一个问题')
    await p // 懒建完成 + 消息已推 + 流已建立
    expect(convApi.create).toHaveBeenCalledWith('第一个问题', 'kb')
    expect(store.currentId).toBe('c_new')
    expect(store.streamState).toBe('connecting')

    const fake = activeFake!
    fake.emit('meta', { conversation_id: 'c_new', is_new: false })
    fake.emit('done', {
      conversation_id: 'c_new',
      message_id: 'm1',
      hit_count: 0,
      elapsed: 1,
      retrieval_ms: 0,
      llm_ms: 0,
    })
    fake.finish()
    expect(store.streamState).toBe('idle')
    expect(store.conversations[0].id).toBe('c_new')
  })

  it('⑭ 改名/删除会话更新侧栏列表', async () => {
    const store = useChatStore()
    await store.loadConversations()
    expect(store.conversations).toHaveLength(1)

    await store.renameConversation('c1', '新名字')
    expect(store.conversations[0].title).toBe('新名字')

    await store.removeConversation('c1')
    expect(store.conversations).toHaveLength(0)
    expect(store.currentId).toBeNull()
    expect(store.messages).toHaveLength(0)
  })
})

describe('stores/chat 问答模式（下拉切换与隔离）', () => {
  it('⑮ loadConversations 按 currentMode 过滤（默认 kb）', async () => {
    const store = useChatStore()
    vi.mocked(convApi.list).mockResolvedValue([conv('k1', 'kb会话', 'kb')])
    await store.loadConversations()
    expect(convApi.list).toHaveBeenCalledWith('kb')
    expect(store.conversations.map((c) => c.mode)).toEqual(['kb'])
  })

  it('⑯ switchMode：重拉对应模式列表、清空消息区、取消在途流', async () => {
    const store = useChatStore()
    await store.switchConversation('c1')
    void store.sendMessage('问题')
    const fake = activeFake!
    fake.emit('meta', { conversation_id: 'c1', is_new: false })
    fake.emit('delta', { content: '进行中' })

    vi.mocked(convApi.list).mockResolvedValue([conv('g1', '通用会话', 'general')])
    await store.switchMode('general')

    expect(store.currentMode).toBe('general')
    expect(convApi.list).toHaveBeenCalledWith('general')
    expect(store.conversations.map((c) => c.mode)).toEqual(['general'])
    expect(store.currentId).toBeNull()
    expect(store.messages).toHaveLength(0)
    expect(store.streamState).toBe('idle')
    // 在途流已终止：残留 delta 不再追加
    fake.emit('delta', { content: '残留' })
    expect(store.messages).toHaveLength(0)
  })

  it('⑰ 通用模式 sendMessage：懒建带 mode=general，streamChat 组装 mode=general', async () => {
    const store = useChatStore()
    vi.mocked(convApi.list).mockResolvedValue([])
    await store.switchMode('general') // 先切到通用模式
    vi.mocked(convApi.create).mockResolvedValue(conv('g_new', '通用问题', 'general'))

    const p = store.sendMessage('通用问题')
    await p
    expect(convApi.create).toHaveBeenCalledWith('通用问题', 'general')
    expect(vi.mocked(streamChat).mock.calls[0][0].mode).toBe('general')

    const fake = activeFake!
    // 通用模式：后端不发 references 事件
    fake.emit('meta', { conversation_id: 'g_new', is_new: true })
    fake.emit('delta', { content: '通用' })
    fake.emit('delta', { content: '回答' })
    fake.emit('done', {
      conversation_id: 'g_new',
      message_id: 'm1',
      hit_count: 0,
      elapsed: 1.2,
      retrieval_ms: 0,
      llm_ms: 1200,
    })
    fake.finish()
    await p

    expect(store.conversations[0]).toMatchObject({ id: 'g_new', mode: 'general' })
    const msg = store.messages[1]
    expect(msg.content).toBe('通用回答')
    expect(msg.refs).toHaveLength(0)
    expect(msg.meta).toMatchObject({ hitCount: 0, retrievalMs: 0, llmMs: 1200 })
  })

  it('⑱ 知识库模式 sendMessage：streamChat 组装 mode=dense', async () => {
    const store = useChatStore()
    await store.switchConversation('c1')
    void store.sendMessage('知识库问题')
    expect(vi.mocked(streamChat).mock.calls[0][0].mode).toBe('dense')
    const fake = activeFake!
    fake.emit('meta', { conversation_id: 'c1', is_new: false })
    fake.finish()
  })
})
