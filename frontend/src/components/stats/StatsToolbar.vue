<script setup lang="ts">
const ALL_DAYS_VALUE = '__all__'

defineProps<{
  days: number | null
  mode: string
  loading: boolean
}>()

const emit = defineEmits<{
  (event: 'days-change', value: number | null): void
  (event: 'mode-change', value: string): void
  (event: 'refresh'): void
}>()

function onDaysChange(value: number | string | null) {
  emit('days-change', value === ALL_DAYS_VALUE ? null : (value as number | null))
}
</script>

<template>
  <div class="toolbar">
    <el-select
      :model-value="days"
      class="days-select"
      @update:model-value="onDaysChange"
    >
      <el-option label="近 7 天" :value="7" />
      <el-option label="近 30 天" :value="30" />
      <el-option label="全部" :value="ALL_DAYS_VALUE" />
    </el-select>
    <el-select
      :model-value="mode"
      class="mode-select"
      @update:model-value="(value: string) => emit('mode-change', value)"
    >
      <el-option label="知识库问答" value="kb" />
      <el-option label="通用问答" value="general" />
      <el-option label="全部口径" value="all" />
    </el-select>
    <el-button class="refresh-btn" :loading="loading" @click="emit('refresh')">刷新</el-button>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.days-select { width: 130px; }
.mode-select { width: 140px; }
.refresh-btn { margin-left: auto; }
</style>
