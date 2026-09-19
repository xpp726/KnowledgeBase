// 问答后端契约类型（与 backend/app/schemas 对齐）。

export interface SourceItem {
  index: number
  chunk_id: string
  doc_id: string
  doc_name: string
  page: number
  score: number
  text: string
}

export type ChatMode = 'kb' | 'general'

export interface Conversation {
  id: string
  kb_id: string
  mode: ChatMode
  title: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  refs: SourceItem[]
  created_at: string
}

// 帧格式：event: {name}\ndata: {json}\n\n；时序 meta → references → delta×N → done。
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
