// 问答状态与数据流（B · 全并 store）：
// 会话列表 + 当前消息 + 流状态机 + abort 控制 + 事件→动作映射
// 协议层（api/sse.ts、api/chat.ts）保持独立纯函数，本 store 只做编排与 UI 状态

import { ref } from 'vue'
import { defineStore } from 'pinia'
import type {
  ChatDeltaEvent,
  ChatDoneEvent,
  ChatErrorEvent,
  ChatMetaEvent,
  ChatReferencesEvent,
  ChatMode,
  Conversation,
  Message,
} from '../types/api'
import type { MessageItem, StreamState } from '../types/chat'
import { streamChat, type SseHandlers } from '../api/chat'
import * as convApi from '../api/conversation'
import { useAuthStore } from './auth'

// D2：本期固定 default，二期 kb 切换时改为 store 字段并接选择器
const KB_ID = 'default'

export const useChatStore = defineStore('chat', () => {
  // ==================== state ====================
  const conversations = ref<Conversation[]>([])
  // 问答模式（下拉框）：kb=知识库问答 / general=通用问答；会话列表按模式隔离
  const currentMode = ref<ChatMode>('kb')
  const currentId = ref<string | null>(null)
  const messages = ref<MessageItem[]>([])
  const streamState = ref<StreamState>('idle')
  const controller = ref<AbortController | null>(null)
  const pendingQuestion = ref<string | null>(null)

  // 非响应式内部状态
  let localSeq = 0
  let streamingLocalId: string | null = null
  let streamHadError = false

  const nextLocalId = () => `l_${++localSeq}`

  function findStreaming(): MessageItem | null {
    if (!streamingLocalId) return null
    return messages.value.find((m) => m.localId === streamingLocalId) ?? null
  }

  function toMessageItem(m: Message): MessageItem {
    return {
      localId: m.id,
      role: m.role,
      content: m.content,
      refs: m.refs ?? [],
      createdAt: m.created_at * 1000,
    }
  }

  function cancelInFlight() {
    if (controller.value) {
      controller.value.abort()
      controller.value = null
    }
  }

  // ==================== 会话 CRUD ====================

  async function loadConversations() {
    try {
      conversations.value = await convApi.list(currentMode.value)
    } catch {
      // 加载失败保持空列表（侧栏显示空态）
    }
  }

  async function createConversation(title = '', mode: ChatMode = currentMode.value): Promise<Conversation> {
    const conv = await convApi.create(title, mode)
    conversations.value.unshift(conv)
    return conv
  }

  // 切换问答模式（下拉框）：重拉对应模式会话列表并清空当前消息区
  async function switchMode(mode: ChatMode) {
    if (mode === currentMode.value) return
    cancelInFlight()
    currentMode.value = mode
    currentId.value = null
    messages.value = []
    streamingLocalId = null
    streamState.value = 'idle'
    await loadConversations()
  }

  async function renameConversation(id: string, title: string) {
    const updated = await convApi.rename(id, title)
    const idx = conversations.value.findIndex((c) => c.id === id)
    if (idx !== -1) conversations.value[idx] = updated
  }

  async function removeConversation(id: string) {
    await convApi.remove(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (currentId.value === id) {
      cancelInFlight()
      currentId.value = null
      messages.value = []
      streamState.value = 'idle'
    }
  }

  async function switchConversation(id: string) {
    if (id === currentId.value) return
    cancelInFlight()
    currentId.value = id
    messages.value = []
    streamingLocalId = null
    streamState.value = 'idle'
    try {
      messages.value = (await convApi.messages(id)).map(toMessageItem)
    } catch {
      // 历史拉取失败：空消息展示，UI 提示可重试
    }
  }

  function newConversation() {
    cancelInFlight()
    currentId.value = null
    messages.value = []
    streamingLocalId = null
    streamState.value = 'idle'
  }

  // ==================== 流式问答 ====================

  async function sendMessage(raw: string) {
    const question = raw.trim()
    if (!question) return
    if (streamState.value === 'connecting' || streamState.value === 'streaming')
      return

    pendingQuestion.value = question
    streamHadError = false
    streamState.value = 'connecting'

    // 无当前会话时懒建（后端新建会话 title=question）
    let convId = currentId.value
    if (!convId) {
      try {
        convId = (await createConversation(question.slice(0, 40), currentMode.value)).id
        currentId.value = convId
      } catch {
        streamState.value = 'idle'
        return
      }
    }

    // 本地先落 user + 空 assistant(streaming)
    messages.value.push({
      localId: nextLocalId(),
      role: 'user',
      content: question,
      refs: [],
      createdAt: Date.now(),
    })
    const assistantLocalId = nextLocalId()
    messages.value.push({
      localId: assistantLocalId,
      role: 'assistant',
      content: '',
      refs: [],
      streaming: true,
      createdAt: Date.now(),
    })
    streamingLocalId = assistantLocalId

    const ac = new AbortController()
    controller.value = ac

    const handlers: SseHandlers = {
      onEvent(event, data) {
        switch (event) {
          case 'meta': {
            const meta = data as ChatMetaEvent
            currentId.value = meta.conversation_id
            if (meta.is_new) {
              conversations.value.unshift({
                id: meta.conversation_id,
                kb_id: KB_ID,
                mode: currentMode.value,
                title: question.slice(0, 40),
                created_at: Date.now() / 1000,
                updated_at: Date.now() / 1000,
              })
            }
            streamState.value = 'streaming'
            break
          }
          case 'references': {
            const msg = findStreaming()
            if (msg) msg.refs = (data as ChatReferencesEvent).sources
            break
          }
          case 'delta': {
            const msg = findStreaming()
            if (msg) msg.content += (data as ChatDeltaEvent).content
            break
          }
          case 'done': {
            const done = data as ChatDoneEvent
            const msg = findStreaming()
            if (msg) {
              msg.streaming = false
              msg.meta = {
                messageId: done.message_id || undefined,
                hitCount: done.hit_count,
                elapsed: done.elapsed,
                retrievalMs: done.retrieval_ms,
                llmMs: done.llm_ms,
              }
              // error 后仍补发 done：保留错误标记，但耗时/命中照常固化
              if (streamHadError) msg.error = msg.error || '生成中断'
            }
            streamingLocalId = null
            streamState.value = 'idle'
            break
          }
          case 'error': {
            const e = data as ChatErrorEvent
            const msg = findStreaming()
            streamHadError = true
            if (msg) {
              msg.streaming = false
              msg.error = `[${e.stage}] ${e.message}`
            }
            streamState.value = 'error'
            break
          }
        }
      },
      onClose() {
        // 兜底：流自然结束但未收到 done（异常断开）
        if (streamingLocalId) {
          const msg = findStreaming()
          if (msg) {
            msg.streaming = false
            msg.error = msg.error || (streamHadError ? '生成中断' : '连接意外断开')
          }
          streamingLocalId = null
        }
        if (streamState.value !== 'idle') {
          streamState.value = streamHadError ? 'error' : 'idle'
        }
      },
      onError(err) {
        const msg = findStreaming()
        streamingLocalId = null
        if (err.kind === 'aborted') {
          // B1：停止生成 → 本地"已停止"占位（不写库）
          if (msg) {
            msg.streaming = false
            msg.stopped = true
          }
          streamState.value = 'stopped'
        } else {
          // 401：token 过期，触发登出跳转
          if (err.kind === 'http' && err.status === 401) {
            const auth = useAuthStore()
            auth.logout()
            window.location.href = '/login'
            return
          }
          // B3：超时 / HTTP / 网络 / 解析失败 → error，供气泡重试
          const label =
            err.kind === 'timeout'
              ? '响应超时（60s 无数据）'
              : err.kind === 'http'
                ? `请求失败（HTTP ${err.status ?? '?'}）`
                : err.kind === 'network'
                  ? '网络连接失败'
                  : '数据解析失败'
          if (msg) {
            msg.streaming = false
            msg.error = msg.content ? `${label}：已生成部分内容` : label
          }
          streamState.value = 'error'
        }
      },
    }

    const auth = useAuthStore()
    const client = streamChat(
      {
        question,
        conversationId: convId,
        kbId: KB_ID,
        mode: currentMode.value === 'general' ? 'general' : 'dense',
        token: auth.token || undefined,
      },
      handlers,
      { signal: ac.signal },
    )
    void client.done.then(() => {
      if (controller.value === ac) controller.value = null
    })
  }

  function stopGeneration() {
    if (controller.value) controller.value.abort()
  }

  function retryLast() {
    if (streamState.value === 'connecting' || streamState.value === 'streaming')
      return
    if (!pendingQuestion.value) return
    // 移除失败对（最后一条 error assistant + 其前一条 user），原地重试
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant' && last.error) {
      messages.value.splice(messages.value.length - 2, 2)
    }
    void sendMessage(pendingQuestion.value)
  }

  return {
    conversations,
    currentMode,
    currentId,
    messages,
    streamState,
    controller,
    pendingQuestion,
    loadConversations,
    switchMode,
    createConversation,
    renameConversation,
    removeConversation,
    switchConversation,
    newConversation,
    sendMessage,
    stopGeneration,
    retryLast,
  }
})
