// 问答流式请求封装：组装 query → 交 createSseClient 解析
// 只做请求与解析，不含任何 UI/状态逻辑（可单测）

import {
  createSseClient,
  type SseClient,
  type SseHandlers,
  type SseOptions,
} from './sse'
import { getAuthHeaders } from './http'
export type { SseClient, SseHandlers, SseOptions } from './sse'

export interface StreamChatParams {
  question: string
  conversationId?: string | null
  kbId?: string // 本期固定 'default'，二期 kb 切换时直接传（D2 留位）
  // 问答模式：dense/hybrid=知识库检索（前端下拉"知识库问答"→dense）；general=通用问答（不检索）
  mode?: 'dense' | 'hybrid' | 'general'
  token?: string // JWT token（SSE 用 fetch，需手动带）
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
  // SSE 用 fetch 不走 Axios 拦截器，复用统一 Token 来源；保留 token 参数兼容现有调用方。
  const finalOpts: SseOptions = { ...opts }
  const authHeaders = params.token
    ? { Authorization: `Bearer ${params.token}` }
    : getAuthHeaders()
  if (Object.keys(authHeaders).length > 0) {
    finalOpts.headers = { ...opts.headers, ...authHeaders }
  }
  return createSseClient(`/api/chat/stream?${search.toString()}`, handlers, finalOpts)
}
