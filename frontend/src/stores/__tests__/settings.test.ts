// settings store 测试：加载、保存确认流、自动重启轮询、取消/失败分支
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSettingsStore } from '../settings'
import type {
  ConfigDiagnostics,
  ConfigParamsSnapshot,
  ConfigSystemInfo,
} from '../../types/api'

vi.mock('../../api/config', () => ({
  systemInfo: vi.fn(),
  params: vi.fn(),
  saveParams: vi.fn(),
  diagnostics: vi.fn(),
}))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  ElMessageBox: { confirm: vi.fn() },
}))

import * as configApi from '../../api/config'
import { ElMessage, ElMessageBox } from 'element-plus'

const SYSTEM: ConfigSystemInfo = {
  app_name: 'KnowledgeBase API',
  version: '0.3.0',
  host: '0.0.0.0',
  port: 8000,
  debug: true,
  uptime_seconds: 120,
  reload_mode: false,
  database: 'sqlite',
  llm_provider: 'deepseek',
  embedding: 'http://localhost:8003 / BAAI/bge-m3',
  milvus: 'localhost:19530',
  storage: 'local',
  log_dir: 'data/logs',
  log_level: 'INFO',
  log_retention_days: 30,
  default_kb: '默认知识库（default）',
}

const SNAPSHOT: ConfigParamsSnapshot = {
  editable: [
    {
      key: 'log_retention_days',
      value: 30,
      label: '日志保留天数',
      desc: '按天轮转，超期文件自动删除',
      type: 'number',
      coerce: 'int',
      min: 1,
      max: 365,
      step: 1,
    },
    {
      key: 'log_level',
      value: 'INFO',
      label: '日志级别',
      desc: '日志文件记录的级别',
      type: 'select',
      coerce: 'enum',
      options: ['DEBUG', 'INFO', 'WARNING', 'ERROR'],
    },
  ],
  infra: [
    { key: 'llm_provider', label: 'LLM 供应商', value: 'deepseek / deepseek-chat' },
    { key: 'llm_api_key', label: 'LLM API Key', value: 'sk-e1****dc23', masked: true },
  ],
}

const DIAG: ConfigDiagnostics = {
  llm: { provider: 'deepseek', current: { ok: true, latency_ms: 320, model: 'deepseek-chat' } },
  embedding: { ok: true, latency_ms: 45 },
  milvus: { ok: true, version: 'v2.5.27', target_exists: true, latency_ms: 12 },
  mysql: { ok: true, dialect: 'mysql', version: '8.0.36', latency_ms: 3 },
  minio: { ok: true, target_bucket: 'kb-files', target_exists: true, latency_ms: 5 },
  config: {},
}

describe('settings store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(configApi.systemInfo).mockResolvedValue(SYSTEM)
    vi.mocked(configApi.params).mockResolvedValue(SNAPSHOT)
    vi.mocked(configApi.diagnostics).mockResolvedValue(DIAG)
  })

  it('loadAll 拉取系统信息与参数白名单', async () => {
    const store = useSettingsStore()
    await store.loadAll()
    expect(configApi.systemInfo).toHaveBeenCalledOnce()
    expect(configApi.params).toHaveBeenCalledOnce()
    expect(store.systemInfo?.log_retention_days).toBe(30)
    expect(store.editable.length).toBe(2)
    expect(store.infra[1].masked).toBe(true)
  })

  it('runDiagnostics 拉取并写入诊断结果', async () => {
    const store = useSettingsStore()
    await store.runDiagnostics()
    expect(configApi.diagnostics).toHaveBeenCalledOnce()
    expect(store.diagnostics?.llm.current.ok).toBe(true)
    expect(store.diagnostics?.milvus.version).toBe('v2.5.27')
  })

  it('save：确认后提交，重启完成重新拉取', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValue('confirm' as never)
    vi.mocked(configApi.saveParams).mockResolvedValue({
      saved: ['log_retention_days'],
      needs_restart: false,
    })
    // 第一次轮询即返回新进程（uptime 重置为 2s）
    vi.mocked(configApi.systemInfo)
      .mockResolvedValueOnce(SYSTEM)
      .mockResolvedValueOnce({ ...SYSTEM, log_retention_days: 60, uptime_seconds: 2 })

    const store = useSettingsStore()
    const ok = await store.save({ log_retention_days: 60 })

    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(configApi.saveParams).toHaveBeenCalledWith({ log_retention_days: 60 })
    expect(ok).toBe(true)
    expect(ElMessage.success).toHaveBeenCalled()
    // 重启完成后重新拉取参数（save 内部 loadAll 调用 1 次）
    expect(configApi.params).toHaveBeenCalledTimes(1)
  })

  it('save：用户取消不调用保存接口', async () => {
    vi.mocked(ElMessageBox.confirm).mockRejectedValue('cancel' as never)
    const store = useSettingsStore()
    const ok = await store.save({ log_retention_days: 60 })
    expect(ok).toBe(false)
    expect(configApi.saveParams).not.toHaveBeenCalled()
  })

  it('save：needs_restart=true 提示手动重启', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValue('confirm' as never)
    vi.mocked(configApi.saveParams).mockResolvedValue({
      saved: ['log_level'],
      needs_restart: true,
    })
    const store = useSettingsStore()
    const ok = await store.save({ log_level: 'ERROR' })
    expect(ok).toBe(true)
    expect(ElMessage.warning).toHaveBeenCalledWith(
      expect.stringContaining('手动重启'),
    )
  })

  it('save：保存接口报错提示且不进入轮询', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValue('confirm' as never)
    vi.mocked(configApi.saveParams).mockRejectedValue(new Error('日志保留天数需在 1 ~ 365 之间'))
    const store = useSettingsStore()
    const ok = await store.save({ log_retention_days: 999 })
    expect(ok).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('1 ~ 365'))
    expect(configApi.saveParams).toHaveBeenCalledWith({ log_retention_days: 999 })
  })
})
