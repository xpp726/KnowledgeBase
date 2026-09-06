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

// ==================== 文档管理 ====================

// 文档状态机（backend/doc_states.py）：
// pending → ingesting → embedding → done/failed；IN_PROGRESS = pending/ingesting/embedding
export type DocStatus = 'pending' | 'ingesting' | 'embedding' | 'done' | 'failed'

export interface KnowledgeBase {
  kb_id: string
  name: string
  description: string
  doc_count: number
  created_at: number
  updated_at: number
}

export interface KnowledgeBaseCreate {
  name: string
  description?: string
}

export interface DocumentItem {
  doc_id: string
  kb_id: string
  file_name: string
  file_ext: string
  file_size: number
  page_count: number
  chunk_count: number
  table_chunks: number
  status: DocStatus
  error: string
  created_at: number
  updated_at: number
}

export interface DocumentListResult {
  items: DocumentItem[]
  total: number
  page: number
  page_size: number
}

export interface DocumentUploadResult {
  doc_id: string
  file_name: string
  status: DocStatus | 'rejected'
  duplicated: boolean
  error?: string
}

export interface DocumentListQuery {
  kb_id?: string
  status?: DocStatus | ''
  search?: string
  page?: number
  page_size?: number
}

// ==================== 运行日志 ====================

export interface LogEntry {
  line_no: number
  ts: string
  level: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG' | 'CRITICAL' | 'OTHER'
  source: string
  message: string
}

export interface LogEntriesResult {
  items: LogEntry[]
  next_end_line: number | null
}

export interface LogFile {
  name: string
  size_bytes: number
  mtime: number
  is_rotated: boolean
}

// ==================== 数据统计 ====================

export interface StatsCards {
  total: number
  hit_count: number
  hit_rate: number
  avg_retrieval_ms: number
  avg_llm_ms: number
  avg_total_ms: number
  no_hit_count: number
}

export interface StatsTrendPoint {
  date: string
  count: number
  hit_rate: number
  avg_total_ms: number
}

export interface StatsTopQuestion {
  question: string
  count: number
}

export interface StatsTopDoc {
  doc_name: string
  count: number
}

export interface StatsKbDist {
  kb_id: string
  count: number
}

export interface StatsSummary {
  cards: StatsCards
  trend: StatsTrendPoint[]
  top_questions: StatsTopQuestion[]
  top_docs: StatsTopDoc[]
  kb_dist: StatsKbDist[]
}

// ==================== 系统设置 ====================

export interface ConfigEditableParam {
  key: string
  value: number | string
  label: string
  desc: string
  type: 'number' | 'select'
  coerce: 'int' | 'float' | 'enum'
  min?: number
  max?: number
  step?: number
  options?: string[]
}

export interface ConfigInfraParam {
  key: string
  label: string
  value: string
  masked?: boolean
}

export interface ConfigParamsSnapshot {
  editable: ConfigEditableParam[]
  infra: ConfigInfraParam[]
}

export interface ConfigSystemInfo {
  app_name: string
  version: string
  host: string
  port: number
  debug: boolean
  uptime_seconds: number
  reload_mode: boolean
  database: string
  llm_provider: string
  embedding: string
  milvus: string
  storage: string
  log_dir: string
  log_level: string
  log_retention_days: number
  default_kb: string
}

export interface ConfigSaveResult {
  saved: string[]
  needs_restart: boolean
}

export interface ConfigDiagnosticsItem {
  ok: boolean
  error?: string
  latency_ms?: number
  version?: string
  collections?: string[]
  target_collection?: string
  target_exists?: boolean
  model?: string
}

export interface ConfigDiagnostics {
  llm: ConfigDiagnosticsItem
  embedding: ConfigDiagnosticsItem
  milvus: ConfigDiagnosticsItem
  config: Record<string, unknown>
}

// ==================== 认证与用户 ====================

export type UserRole = 'admin' | 'editor' | 'viewer'

export interface User {
  id: string
  username: string
  display_name: string
  role: UserRole
  is_active: boolean
  created_at: number
  updated_at: number
  last_login_at: number
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  token: string
  user: User
}

export interface UserCreate {
  username: string
  password: string
  display_name?: string
  role: UserRole
}

export interface UserUpdate {
  role?: UserRole
  is_active?: boolean
  display_name?: string
  reset_password?: string
}

export interface UserListResponse {
  users: User[]
}
