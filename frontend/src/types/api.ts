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
  folder_id: string | null
  folder_path: string // "默认文件夹 / 子目录A"，便于溯源展示
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
  folder_id: string | null
  status: DocStatus | 'rejected'
  duplicated: boolean
  error?: string
  /** 仅目录上传（uploadDirectory）返回时携带：原始相对路径，便于溯源。 */
  path?: string
}

export interface DocumentListQuery {
  kb_id?: string
  folder_id?: string | null
  status?: DocStatus | ''
  search?: string
  page?: number
  page_size?: number
}

export interface MoveDocumentsPayload {
  doc_ids: string[]
  target_folder_id: string
}

export interface MoveDocumentResult {
  doc_id: string
  status: 'moved' | 'rejected'
  error?: string
}

// ==================== 文件夹 ====================

export interface Folder {
  folder_id: string
  kb_id: string
  parent_id: string | null
  name: string
  depth: number
  is_system: boolean
  created_at: number
  updated_at: number
}

export interface FolderTreeNode extends Folder {
  children: FolderTreeNode[]
  doc_count: number // 直属文件数（不含子 folder）
}

// 递归统计某 folder 节点下（含所有子孙）的总文件数。
// 前端 UI 在删除确认 / 列表显示时使用，避免每次都遍历整棵树。
export function totalDocCount(node: FolderTreeNode): number {
  return node.doc_count + node.children.reduce((sum, c) => sum + totalDocCount(c), 0)
}

export interface FolderTreeResult {
  items: FolderTreeNode[]
}

export interface FolderCreatePayload {
  kb_id: string
  parent_id: string | null
  name: string
}

export interface FolderMovePayload {
  parent_id: string | null
}

export interface DirectoryUploadResult {
  uploaded: DocumentUploadResult[]
  rejected: Array<{ file_name: string; path?: string; folder_id?: string; status: 'rejected'; error: string }>
  summary: {
    uploaded_count: number
    rejected_count: number
    created_folder_ids: string[]
  }
}

// ==================== 混合树（UI 方案 B：folder + file 统一一张表） ====================
// 一棵挂载在 kb 根上的统一树，folder 行携带 children（子 folder + 直属 file）；
// file 行无 children，自动成 el-table 树形叶子。
// node_id 形如 "folder:<id>" / "doc:<id>"，前端行 key 唯一。
// 生成在 store 内部（merge folderTree + 全 kb 文档）；不在后端暴露。

export interface MixedFolderNode {
  node_type: 'folder'
  node_id: string
  folder_id: string
  parent_id: string | null
  name: string
  depth: number
  is_system: boolean
  /** 直接子文档数（不含子 folder）；来自后端 FolderTreeNode.doc_count */
  direct_doc_count: number
  /** 自身 + 全部子孙 folder 的文档总数（含子 folder 文件）；递归累加 */
  total_doc_count: number
  created_at: number
  updated_at: number
  children: MixedNode[]
}

export interface MixedFileNode {
  node_type: 'file'
  node_id: string
  doc_id: string
  folder_id: string
  /** 形如 "默认文件夹 / 研发资料"，UI 显示在行名下的二级灰字 */
  folder_path: string
  file_name: string
  file_ext: string
  file_size: number
  page_count: number
  chunk_count: number
  status: DocStatus
  error: string
  /** 渲染缩进用：file 所在 folder 的 depth（=folder.depth+1）；前端 UI 自定义缩进必备。 */
  _depth: number
  /** 是否显示 folder_path 二级灰字：仅当 file 位于子 folder（depth>1）下才显示，避免顶层文件多一截冗余前缀。 */
  _show_path: boolean
  created_at: number
  updated_at: number
}

export type MixedNode = MixedFolderNode | MixedFileNode

export function isFolderNode(n: MixedNode): n is MixedFolderNode {
  return n.node_type === 'folder'
}

export function isFileNode(n: MixedNode): n is MixedFileNode {
  return n.node_type === 'file'
}

/** 在 MixedFolderNode 上递归统计总文档数（含所有子孙 folder 的文件）。
 *  ⚠️ self 直挂的 file 已被 direct_doc_count 计入；这里只递归子 folder，不再 +1 file。 */
export function mixedTotalDocCount(node: MixedFolderNode): number {
  return (
    node.direct_doc_count +
    node.children
      .filter((c): c is MixedFolderNode => c.node_type === 'folder')
      .reduce((sum, c) => sum + mixedTotalDocCount(c), 0)
  )
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
  reply?: string
}

// LLM 探测返回结构（与 backend/app/services/health.py 对齐）：
// current = 当前生效 provider 的探测结果；deepseek = 若配置了公网 key 则顺带探测
export interface ConfigDiagnosticsLLM {
  provider: string
  current: ConfigDiagnosticsItem
  deepseek?: ConfigDiagnosticsItem
}

export interface ConfigDiagnostics {
  llm: ConfigDiagnosticsLLM
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
