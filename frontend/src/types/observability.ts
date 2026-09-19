// 日志和统计后端契约类型。

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
