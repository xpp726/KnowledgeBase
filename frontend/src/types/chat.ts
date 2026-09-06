// 前端消息模型（store 与 UI 消费；api.ts 为后端契约，两者分离）

import type { Conversation, SourceItem } from './api'

export type StreamState = 'idle' | 'connecting' | 'streaming' | 'stopped' | 'error'

export interface MessageMeta {
  messageId?: string
  hitCount: number
  elapsed: number
  retrievalMs: number
  llmMs: number
}

export interface MessageItem {
  localId: string
  role: 'user' | 'assistant'
  content: string
  refs: SourceItem[]
  meta?: MessageMeta
  streaming?: boolean // 正在生成（显示光标）
  stopped?: boolean // 本地停止占位（不写库）
  error?: string // 错误文案（ErrorBubble + 重试）
  createdAt: number
}

export interface ChatState {
  conversations: Conversation[]
  currentId: string | null
  messages: MessageItem[]
  streamState: StreamState
  controller: AbortController | null
  pendingQuestion: string | null
}
