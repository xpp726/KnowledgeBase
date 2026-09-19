// 系统设置和基础设施诊断类型。

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
  dialect?: string
  collections?: string[]
  target_collection?: string
  buckets?: string[]
  target_bucket?: string
  target_exists?: boolean
  model?: string
  reply?: string
}

export interface ConfigDiagnosticsLLM {
  provider: string
  current: ConfigDiagnosticsItem
  deepseek?: ConfigDiagnosticsItem
}

export interface ConfigDiagnostics {
  llm: ConfigDiagnosticsLLM
  embedding: ConfigDiagnosticsItem
  milvus: ConfigDiagnosticsItem
  mysql: ConfigDiagnosticsItem
  minio: ConfigDiagnosticsItem
  config: Record<string, unknown>
}
