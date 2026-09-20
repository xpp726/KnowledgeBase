<script setup lang="ts">
// 运行日志工具栏：文件切换 / 级别筛选 / 关键词搜索 / 自动刷新开关 / 手动刷新 / 下载
import { ref } from 'vue'
import type { LogFile } from '../../types/observability'

defineProps<{
  files: LogFile[]
  currentFile: string
  levelFilter: string
  autoRefresh: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  (event: 'file-change', name: string): void
  (event: 'level-change', level: string): void
  (event: 'search', keyword: string): void
  (event: 'toggle-auto-refresh', on: boolean): void
  (event: 'refresh'): void
  (event: 'download'): void
}>()

const LEVEL_OPTIONS = [
  { label: '全部级别', value: '' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'CRITICAL', value: 'CRITICAL' },
  { label: 'OTHER', value: 'OTHER' },
]

const keyword = ref('')

function fileLabel(file: LogFile): string {
  return file.is_rotated ? `${file.name}（已轮转）` : file.name
}

// 回车或清空时触发搜索（store.applySearch 会 trim 并去重相同关键词）
function onSearch() {
  emit('search', keyword.value)
}
</script>

<template>
  <div class="log-toolbar">
    <el-select
      :model-value="currentFile"
      class="file-select"
      @update:model-value="(v: string) => emit('file-change', v)"
    >
      <el-option v-for="f in files" :key="f.name" :label="fileLabel(f)" :value="f.name" />
    </el-select>

    <el-select
      :model-value="levelFilter"
      class="level-select"
      @update:model-value="(v: string) => emit('level-change', v)"
    >
      <el-option v-for="opt in LEVEL_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
    </el-select>

    <el-input
      v-model="keyword"
      class="search-input"
      placeholder="搜索关键词"
      clearable
      @keyup.enter="onSearch"
      @clear="onSearch"
    />

    <el-switch
      :model-value="autoRefresh"
      active-text="自动刷新"
      @change="(v: string | number | boolean) => emit('toggle-auto-refresh', v === true)"
    />

    <div class="spacer" />

    <el-button :loading="loading" @click="emit('refresh')">刷新</el-button>
    <el-button type="primary" @click="emit('download')">下载</el-button>
  </div>
</template>

<style scoped>
.log-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-select {
  width: 200px;
}

.level-select {
  width: 120px;
}

.search-input {
  width: 220px;
}

.spacer {
  flex: 1;
}
</style>
