<script setup lang="ts">
// 运行日志页（阶段 3）：文件切换 / 级别与关键词筛选 / 倒序游标分页 / 自动刷新（可暂停）/ 下载
import { onMounted, onUnmounted } from 'vue'
import { useLogStore } from '../stores/logs'
import { downloadUrl } from '../api/logs'
import LogToolbar from '../components/logs/LogToolbar.vue'
import LogTable from '../components/logs/LogTable.vue'

const store = useLogStore()

function handleFileChange(name: string) {
  store.setFile(name)
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
    <LogToolbar
      :files="store.files"
      :current-file="store.currentFile"
      :level-filter="store.levelFilter"
      :auto-refresh="store.autoRefresh"
      :loading="store.loading"
      @file-change="handleFileChange"
      @level-change="store.setLevel"
      @search="store.applySearch"
      @toggle-auto-refresh="store.toggleAutoRefresh"
      @refresh="store.reload"
      @download="handleDownload"
    />
    <LogTable
      :entries="store.entries"
      :loading="store.loading"
      :next-end-line="store.nextEndLine"
      :loading-more="store.loadingMore"
      @load-more="store.loadMore"
    />
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

</style>
