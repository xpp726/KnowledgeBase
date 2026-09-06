// 问答流式请求封装：组装 query → 交 createSseClient 解析
// 只做请求与解析，不含任何 UI/状态逻辑（可单测）

import {
  createSseClient,
  type SseClient,
  type SseHandlers,
  type SseOptions,
} from './sse'
export type { SseClient, SseHandlers, SseOptions } from './sse'

export interface StreamChatParams {
  question: string
  conversationId?: string | null
  kbId?: string // 本期固定 'default'，二期 kb 切换时直接传（D2 留位）
  // 问答模式：dense/hybrid=知识库检索（前端下拉"知识库问答"→dense）；general=通用问答（不检索）
  mode?: 'dense' | 'hybrid' | 'general'
}

export function streamChat(
  params: StreamChatParams,
  handlers: SseHandlers,
  opts: SseOptions = {},
): SseClient {
  const search = new URLSearchParams({
    question: params.question,
    kb_id: params.kbId ?? 'default',
    mode: params.mode ?? 'dense',
  })
  if (params.conversationId) {
    search.set('conversation_id', params.conversationId)
  }
  return createSseClient(`/api/chat/stream?${search.toString()}`, handlers, opts)
}
