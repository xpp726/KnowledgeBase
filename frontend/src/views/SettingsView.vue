<script setup lang="ts">
// 系统设置页（阶段 3 迭代 4）：四板块
// ① 系统信息（只读） ② 连通性诊断（LLM/Embedding/Milvus 探测）
// ③ 业务参数（白名单可编辑 → 保存并自动重启） ④ 基础设施（只读，敏感字段掩码）
import { computed, onMounted, reactive, watch } from 'vue'
import { useSettingsStore } from '../stores/settings'

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
  return [
    { key: 'llm', name: 'LLM 服务', ok: d.llm.ok, detail: diagDetail('llm', d.llm) },
    { key: 'embedding', name: 'Embedding 服务', ok: d.embedding.ok, detail: diagDetail('embedding', d.embedding) },
    { key: 'milvus', name: 'Milvus 向量库', ok: d.milvus.ok, detail: diagDetail('milvus', d.milvus) },
  ]
})

function diagDetail(
  kind: string,
  item: { ok: boolean; error?: string; latency_ms?: number; version?: string; target_exists?: boolean; model?: string },
): string {
  if (!item.ok) return item.error || '不可用'
  const parts: string[] = []
  if (item.latency_ms !== undefined) parts.push(`${item.latency_ms}ms`)
  if (kind === 'llm' && item.model) parts.push(item.model)
  if (kind === 'embedding' && item.model) parts.push(item.model)
  if (kind === 'milvus') {
    if (item.version) parts.push(item.version)
    parts.push(item.target_exists ? '目标集合存在' : '目标集合缺失')
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
    <!-- ① 系统信息 -->
    <section class="panel">
      <div class="panel-title">系统信息</div>
      <div class="info-grid" v-if="infoRows.length">
        <div v-for="row in infoRows" :key="row.label" class="info-row">
          <span class="info-label">{{ row.label }}</span>
          <span class="info-value">{{ row.value }}</span>
        </div>
      </div>
    </section>

    <!-- ② 连通性诊断 -->
    <section class="panel">
      <div class="panel-title-row">
        <div class="panel-title">连通性诊断</div>
        <el-button
          size="small"
          :loading="store.diagnosticsLoading"
          @click="store.runDiagnostics()"
        >
          运行诊断
        </el-button>
      </div>
      <div v-if="diagItems.length" class="diag-grid">
        <div
          v-for="item in diagItems"
          :key="item.key"
          class="diag-card"
          :class="item.ok ? 'diag-ok' : 'diag-fail'"
        >
          <div class="diag-name">
            <span class="diag-dot" :class="{ ok: item.ok }" />
            {{ item.name }}
          </div>
          <div class="diag-status">{{ item.ok ? '正常' : '异常' }}</div>
          <div class="diag-detail">{{ item.detail }}</div>
        </div>
      </div>
      <el-empty
        v-else-if="!store.diagnosticsLoading"
        description="点击「运行诊断」探测 LLM / Embedding / Milvus 连通性"
        :image-size="72"
      />
    </section>

    <!-- ③ 业务参数 -->
    <section class="panel">
      <div class="panel-title">业务参数</div>
      <div class="param-list">
        <div v-for="p in store.editable" :key="p.key" class="param-row">
          <div class="param-info">
            <div class="param-label">{{ p.label }}</div>
            <div class="param-desc">{{ p.desc }}</div>
          </div>
          <el-select
            v-if="p.type === 'select'"
            :model-value="form[p.key]"
            class="param-input"
            @update:model-value="(v: string) => (form[p.key] = v)"
          >
            <el-option v-for="opt in p.options" :key="opt" :label="opt" :value="opt" />
          </el-select>
          <el-input-number
            v-else
            :model-value="form[p.key] as number"
            class="param-input"
            :min="p.min"
            :max="p.max"
            :step="p.step"
            @update:model-value="(v: number | undefined) => v !== undefined && (form[p.key] = v)"
          />
        </div>
      </div>
      <div class="save-bar">
        <span v-if="isDirty" class="dirty-tip">有未保存的修改</span>
        <el-button
          type="primary"
          :disabled="!isDirty"
          :loading="store.saving"
          @click="handleSave()"
        >
          保存并重启
        </el-button>
      </div>
    </section>

    <!-- ④ 基础设施 -->
    <section class="panel">
      <div class="panel-title">基础设施</div>
      <div class="infra-list">
        <div v-for="row in store.infra" :key="row.key" class="info-row">
          <span class="info-label">{{ row.label }}</span>
          <span class="info-value mono">{{ row.value }}</span>
        </div>
      </div>
    </section>
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

.panel {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 14px 16px;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--text-color);
}

.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-title-row .panel-title {
  margin-bottom: 0;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 4px 24px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--border-color);
  font-size: 13px;
}

.info-label {
  color: var(--text-secondary);
  white-space: nowrap;
}

.info-value {
  color: var(--text-color);
  text-align: right;
  word-break: break-all;
}

.mono {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
}

/* 诊断 */
.diag-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.diag-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
}

.diag-ok {
  background: rgba(82, 196, 26, 0.04);
  border-color: rgba(82, 196, 26, 0.35);
}

.diag-fail {
  background: rgba(234, 102, 104, 0.04);
  border-color: rgba(234, 102, 104, 0.4);
}

.diag-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-color);
}

.diag-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ea6668;
}

.diag-dot.ok {
  background: #52c41a;
}

.diag-status {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #ea6668;
}

.diag-ok .diag-status {
  color: #52c41a;
}

.diag-detail {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
  word-break: break-all;
}

/* 业务参数 */
.param-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.param-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--border-color);
}

.param-info {
  flex: 1;
  min-width: 0;
}

.param-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-color);
}

.param-desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-secondary);
}

.param-input {
  width: 180px;
  flex-shrink: 0;
}

.save-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 14px;
}

.dirty-tip {
  font-size: 12px;
  color: #faad14;
}
</style>
