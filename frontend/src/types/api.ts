// 后端契约类型（与 backend/app/schemas.py 对齐，勿臆造字段）

export interface SourceItem {
  index: number
  chunk_id: string
  doc_id: string
  doc_name: string
  page: number
  score: number
  text: string
}

// 问答模式：kb=知识库问答（检索+引用）/ general=通用问答（直接 LLM）
export type ChatMode = 'kb' | 'general'

export interface Conversation {
  id: string
  kb_id: string
  mode: ChatMode
  title: string
  created_at: number // 秒级 float
  updated_at: number // 秒级 float
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  refs: SourceItem[]
  created_at: number
}

export interface OkResponse {
  ok: boolean
  detail?: string
}

// ==================== SSE 事件 ====================
// 帧格式：event: {name}\ndata: {json}\n\n；时序 meta → references → delta×N → done
// 注意：error 可在任意阶段出现，之后仍会补发 done（message_id=""）

export interface ChatMetaEvent {
  conversation_id: string
  is_new: boolean
}

export interface ChatReferencesEvent {
  sources: SourceItem[]
}

export interface ChatDeltaEvent {
  content: string
}

export interface ChatDoneEvent {
  conversation_id: string
  message_id: string
  hit_count: number
  elapsed: number
  retrieval_ms: number
  llm_ms: number
}

export interface ChatErrorEvent {
  stage: string
  message: string
}

export type SseEventName = 'meta' | 'references' | 'delta' | 'done' | 'error'

export type SseEvent =
  | ({ event: 'meta' } & ChatMetaEvent)
  | ({ event: 'references' } & ChatReferencesEvent)
  | ({ event: 'delta' } & ChatDeltaEvent)
  | ({ event: 'done' } & ChatDoneEvent)
  | ({ event: 'error' } & ChatErrorEvent)
