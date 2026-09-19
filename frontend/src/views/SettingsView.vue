<script setup lang="ts">
// 系统设置页（阶段 3 迭代 4）：四板块
// ① 系统信息（只读） ② 连通性诊断（LLM/Embedding/Milvus 探测）
// ③ 业务参数（白名单可编辑 → 保存并自动重启） ④ 基础设施（只读，敏感字段掩码）
import { computed, onMounted, reactive, watch } from 'vue'
import { useSettingsStore } from '../stores/settings'
import SettingsDiagnosticsPanel from '../components/settings/SettingsDiagnosticsPanel.vue'
import SettingsInfoPanel from '../components/settings/SettingsInfoPanel.vue'
import SettingsParametersPanel from '../components/settings/SettingsParametersPanel.vue'

const store = useSettingsStore()

// 业务参数表单：key -> 输入值（深拷贝 editable 当前值，避免直接改 store）
const form = reactive<Record<string, number | string>>({})

function initForm() {
  for (const p of store.editable) {
    form[p.key] = p.value
  }
}

// editable 变化（初始加载 / 重启后重新拉取）时重建表单
watch(
  () => store.editable.map((p) => `${p.key}:${p.value}`).join('|'),
  () => initForm(),
)

const isDirty = computed(() => {
  for (const p of store.editable) {
    if (form[p.key] !== p.value) return true
  }
  return false
})

function fmtUptime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const parts: string[] = []
  if (d) parts.push(`${d}天`)
  if (h) parts.push(`${h}小时`)
  if (m) parts.push(`${m}分钟`)
  parts.push(`${sec}秒`)
  return parts.join(' ')
}

async function handleSave() {
  const payload: Record<string, unknown> = {}
  for (const p of store.editable) {
    payload[p.key] = form[p.key]
  }
  await store.save(payload)
  initForm() // 无论成功/取消，回到服务端最新值
}

const diagItems = computed(() => {
  const d = store.diagnostics
  if (!d) return []
  const llmItem = d.llm.current
  return [
    { key: 'llm', name: 'LLM 服务', ok: llmItem?.ok ?? false, detail: diagDetail('llm', llmItem) },
    { key: 'embedding', name: 'Embedding 服务', ok: d.embedding.ok, detail: diagDetail('embedding', d.embedding) },
    { key: 'milvus', name: 'Milvus 向量库', ok: d.milvus.ok, detail: diagDetail('milvus', d.milvus) },
    { key: 'mysql', name: 'MySQL 数据库', ok: d.mysql?.ok ?? false, detail: diagDetail('mysql', d.mysql) },
    { key: 'minio', name: 'MinIO 对象存储', ok: d.minio?.ok ?? false, detail: diagDetail('minio', d.minio) },
  ]
})

function diagDetail(
  kind: string,
  item?: { ok: boolean; error?: string; latency_ms?: number; version?: string; dialect?: string; target_bucket?: string; target_exists?: boolean; model?: string },
): string {
  if (!item || !item.ok) return item?.error || '不可用'
  const parts: string[] = []
  if (item.latency_ms !== undefined) parts.push(`${item.latency_ms}ms`)
  if (kind === 'llm' && item.model) parts.push(item.model)
  if (kind === 'embedding' && item.model) parts.push(item.model)
  if (kind === 'milvus') {
    if (item.version) parts.push(item.version)
    parts.push(item.target_exists ? '目标集合存在' : '目标集合缺失')
  }
  if (kind === 'mysql') {
    if (item.dialect) parts.push(item.dialect)
    if (item.version) parts.push(item.version)
  }
  if (kind === 'minio') {
    parts.push(item.target_exists ? `bucket ${item.target_bucket} 存在` : `bucket ${item.target_bucket} 缺失`)
  }
  return parts.join(' · ') || '正常'
}

const infoRows = computed(() => {
  const s = store.systemInfo
  if (!s) return []
  return [
    { label: '应用名称', value: s.app_name },
    { label: '版本', value: `v${s.version}` },
    { label: '监听地址', value: `${s.host}:${s.port}` },
    { label: '运行时长', value: fmtUptime(s.uptime_seconds) },
    { label: '调试模式', value: s.debug ? '开' : '关' },
    { label: '数据库', value: s.database },
    { label: 'LLM 供应商', value: s.llm_provider },
    { label: 'Embedding', value: s.embedding },
    { label: 'Milvus', value: s.milvus },
    { label: '文件存储', value: s.storage },
    { label: '日志目录', value: s.log_dir },
    { label: '日志级别', value: s.log_level },
    { label: '日志保留', value: `${s.log_retention_days} 天` },
    { label: '默认知识库', value: s.default_kb },
  ]
})

onMounted(async () => {
  await store.loadAll()
  initForm()
})
</script>

<template>
  <div class="settings-view">
    <SettingsInfoPanel title="系统信息" :rows="infoRows" />
    <SettingsDiagnosticsPanel
      :items="diagItems"
      :loading="store.diagnosticsLoading"
      @run="store.runDiagnostics"
    />
    <SettingsParametersPanel
      :params="store.editable"
      :values="form"
      :dirty="isDirty"
      :saving="store.saving"
      @update="(key, value) => (form[key] = value)"
      @save="handleSave"
    />
    <SettingsInfoPanel title="基础设施" :rows="store.infra" mono />
  </div>
</template>

<style scoped>
.settings-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 16px 20px;
  gap: 12px;
  box-sizing: border-box;
  overflow-y: auto;
}

</style>
