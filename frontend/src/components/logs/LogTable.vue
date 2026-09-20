<script setup lang="ts">
// 运行日志表格：倒序展示（最新在前）/ 级别标签 / 滚动接近底部自动加载更早日志
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import type { LogEntry } from '../../types/observability'

const props = defineProps<{
  entries: LogEntry[]
  loading: boolean
  nextEndLine: number | null
  loadingMore: boolean
}>()

const emit = defineEmits<{
  (event: 'load-more'): void
}>()

function levelTagType(level: LogEntry['level']): 'info' | 'warning' | 'danger' {
  if (level === 'ERROR' || level === 'CRITICAL') return 'danger'
  if (level === 'WARNING') return 'warning'
  return 'info'
}

// el-table 内部滚动容器是 .el-scrollbar__wrap，原生 scroll 不冒泡，需手动挂载监听
const wrapRef = ref<HTMLElement | null>(null)
let scrollEl: HTMLElement | null = null

function onScroll(e: Event) {
  const el = e.target as HTMLElement
  if (props.nextEndLine == null) return
  // 距底部不足 80px 且还有更早数据时触发
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) {
    emit('load-more')
  }
}

onMounted(async () => {
  await nextTick()
  scrollEl = wrapRef.value?.querySelector('.el-scrollbar__wrap') ?? null
  scrollEl?.addEventListener('scroll', onScroll)
})

onUnmounted(() => {
  scrollEl?.removeEventListener('scroll', onScroll)
  scrollEl = null
})
</script>

<template>
  <div ref="wrapRef" class="log-table">
    <el-table
      :data="entries"
      v-loading="loading"
      stripe
      height="100%"
    >
      <el-table-column prop="line_no" label="#" width="80" />
      <el-table-column prop="ts" label="时间" width="210" show-overflow-tooltip />
      <el-table-column label="级别" width="110">
        <template #default="{ row }">
          <el-tag :type="levelTagType(row.level)" size="small">{{ row.level }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="source" label="来源" width="180" show-overflow-tooltip />
      <el-table-column prop="message" label="消息" min-width="320" show-overflow-tooltip />
    </el-table>

    <div v-if="loadingMore" class="load-more-bar">正在加载更早日志…</div>
    <div
      v-else-if="!loading && nextEndLine == null && entries.length > 0"
      class="load-more-bar muted"
    >
      已到最早记录
    </div>
  </div>
</template>

<style scoped>
.log-table {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  box-sizing: border-box;
}

.load-more-bar {
  text-align: center;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 4px 0;
}

.load-more-bar.muted {
  color: var(--el-text-color-placeholder);
}
</style>
