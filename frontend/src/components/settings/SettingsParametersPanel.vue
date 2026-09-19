<script setup lang="ts">
import type { ConfigEditableParam } from '../../types/settings'

defineProps<{
  params: ConfigEditableParam[]
  values: Record<string, number | string>
  dirty: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  (event: 'update', key: string, value: number | string): void
  (event: 'save'): void
}>()
</script>

<template>
  <section class="panel">
    <div class="panel-title">业务参数</div>
    <div class="param-list">
      <div v-for="param in params" :key="param.key" class="param-row">
        <div class="param-info">
          <div class="param-label">{{ param.label }}</div>
          <div class="param-desc">{{ param.desc }}</div>
        </div>
        <el-select
          v-if="param.type === 'select'"
          :model-value="values[param.key]"
          class="param-input"
          @update:model-value="(value: string) => emit('update', param.key, value)"
        >
          <el-option v-for="option in param.options" :key="option" :label="option" :value="option" />
        </el-select>
        <el-input-number
          v-else
          :model-value="values[param.key] as number"
          class="param-input"
          :min="param.min"
          :max="param.max"
          :step="param.step"
          @update:model-value="(value: number | undefined) => value !== undefined && emit('update', param.key, value)"
        />
      </div>
    </div>
    <div class="save-bar">
      <span v-if="dirty" class="dirty-tip">有未保存的修改</span>
      <el-button type="primary" :disabled="!dirty" :loading="saving" @click="emit('save')">保存并重启</el-button>
    </div>
  </section>
</template>

<style scoped>
.panel { background: #fff; border: 1px solid var(--border-color); border-radius: 10px; padding: 14px 16px; }
.panel-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--text-color); }
.param-list { display: flex; flex-direction: column; gap: 10px; }
.param-row { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 8px 0; border-bottom: 1px dashed var(--border-color); }
.param-info { flex: 1; min-width: 0; }
.param-label { font-size: 13px; font-weight: 600; color: var(--text-color); }
.param-desc { margin-top: 2px; font-size: 12px; color: var(--text-secondary); }
.param-input { width: 180px; flex-shrink: 0; }
.save-bar { display: flex; align-items: center; justify-content: flex-end; gap: 12px; margin-top: 14px; }
.dirty-tip { font-size: 12px; color: #faad14; }
</style>
