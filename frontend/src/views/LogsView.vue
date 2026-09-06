<script setup lang="ts">
// 运行日志页（阶段 3）：文件切换 / 级别与关键词筛选 / 倒序游标分页 / 自动刷新（可暂停）/ 下载
import { onMounted, onUnmounted, ref } from 'vue'
import { useLogStore } from '../stores/logs'
import { downloadUrl } from '../api/logs'
import type { LogEntry } from '../types/api'

const store = useLogStore()

// 搜索：本地输入，回车/失焦/清空时才触发（避免 v-model 直接改 store 导致 applySearch 短路）
const searchInput = ref('')

function applySearch() {
  store.applySearch(searchInput.value.trim())
}

function handleFileChange(name: string) {
  searchInput.value = '' // 切文件清本地搜索框（store 内同步重置筛选）
  store.setFile(name)
}

// 级别展示映射
const LEVEL_META = {
  INFO: 'info',
  WARNING: 'warning',
  ERROR: 'danger',
  DEBUG: 'info',
  CRITICAL: 'danger',
  OTHER: '',
} as const

function displayLevel(level: LogEntry['level']): string {
  return level === 'OTHER' ? 'RAW' : level
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function handleDownload() {
  window.open(downloadUrl(store.currentFile), '_blank')
}

onMounted(() => {
  void store.loadFiles()
  void store.reload()
  store.startAutoRefresh()
})

onUnmounted(() => {
  store.stopAutoRefresh()
})
</script>

<template>
  <div class="logs-view">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-select
        :model-value="store.currentFile"
        class="file-select"
        placeholder="选择日志文件"
        @update:model-value="(v: string) => handleFileChange(v)"
      >
        <el-option-group label="当前">
          <el-option
            v-for="f in store.files.filter((f) => !f.is_rotated)"
            :key="f.name"
            :label="`${f.name}（${formatSize(f.size_bytes)}）`"
            :value="f.name"
          />
        </el-option-group>
        <el-option-group label="历史轮转">
          <el-option
            v-for="f in store.files.filter((f) => f.is_rotated)"
            :key="f.name"
            :label="`${f.name}（${formatSize(f.size_bytes)}）`"
            :value="f.name"
          />
        </el-option-group>
      </el-select>

      <el-select
        :model-value="store.levelFilter"
        class="level-select"
        placeholder="全部级别"
        clearable
        @update:model-value="(v: string) => store.setLevel(v ?? '')"
      >
        <el-option label="INFO" value="INFO" />
        <el-option label="WARNING" value="WARNING" />
        <el-option label="ERROR" value="ERROR" />
        <el-option label="DEBUG" value="DEBUG" />
      </el-select>

      <el-input
        v-model="searchInput"
        class="search-input"
        placeholder="按消息关键词搜索"
        clearable
        @clear="applySearch"
        @keyup.enter="applySearch"
        @change="applySearch"
      />

      <el-switch
        :model-value="store.autoRefresh"
        active-text="自动刷新"
        class="auto-switch"
        @update:model-value="(v: boolean) => store.toggleAutoRefresh(v)"
      />

      <el-button class="refresh-btn" :loading="store.loading" @click="store.reload()">
        刷新
      </el-button>
      <el-button class="download-btn" plain @click="handleDownload">下载</el-button>
    </div>

    <!-- 日志列表 -->
    <el-table
      v-loading="store.loading"
      :data="store.entries"
      class="log-table"
      :row-class-name="({ row }: { row: LogEntry }) => `level-${row.level.toLowerCase()}`"
    >
      <el-table-column prop="line_no" label="#" width="64" align="right" />
      <el-table-column label="时间" width="150">
        <template #default="{ row }: { row: LogEntry }">
          <span class="log-ts">{{ row.ts || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="级别" width="90">
        <template #default="{ row }: { row: LogEntry }">
          <el-tag :type="LEVEL_META[row.level]" size="small" effect="plain">
            {{ displayLevel(row.level) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="source" label="来源" width="220" show-overflow-tooltip />
      <el-table-column label="消息" min-width="320">
        <template #default="{ row }: { row: LogEntry }">
          <span class="log-message">{{ row.message }}</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 空态 -->
    <el-empty
      v-if="!store.loading && store.entries.length === 0"
      description="暂无日志，可切换文件或调整筛选"
    />

    <!-- 加载更早 -->
    <div v-if="store.nextEndLine != null && store.entries.length > 0" class="load-more">
      <el-button
        :loading="store.loadingMore"
        plain
        @click="store.loadMore()"
      >
        加载更早的日志
      </el-button>
    </div>
    <div v-else-if="store.entries.length > 0" class="load-more">
      <span class="load-more-tip">已到最早日志</span>
    </div>
  </div>
</template>

<style scoped>
.logs-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 16px 20px;
  gap: 12px;
  box-sizing: border-box;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.file-select {
  width: 240px;
}

.level-select {
  width: 130px;
}

.search-input {
  width: 260px;
}

.auto-switch {
  margin-left: 4px;
}

.refresh-btn {
  margin-left: auto;
}

.log-table {
  flex: 1;
  min-height: 0;
}

.log-ts {
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}

.log-message {
  font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
  font-size: 12.5px;
  white-space: pre-wrap;
  word-break: break-all;
}

:deep(.level-error .log-message) {
  color: #c45656;
}

:deep(.level-warning .log-message) {
  color: #b8860b;
}

.load-more {
  display: flex;
  justify-content: center;
  padding: 4px 0 8px;
}

.load-more-tip {
  color: var(--text-secondary);
  font-size: 12px;
}
</style>
