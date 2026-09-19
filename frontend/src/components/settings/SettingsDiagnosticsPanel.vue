<script setup lang="ts">
defineProps<{
  items: Array<{ key: string; name: string; ok: boolean; detail: string }>
  loading: boolean
}>()

const emit = defineEmits<{ (event: 'run'): void }>()
</script>

<template>
  <section class="panel">
    <div class="panel-title-row">
      <div class="panel-title">连通性诊断</div>
      <el-button size="small" :loading="loading" @click="emit('run')">运行诊断</el-button>
    </div>
    <div v-if="items.length" class="diag-grid">
      <div v-for="item in items" :key="item.key" class="diag-card" :class="item.ok ? 'diag-ok' : 'diag-fail'">
        <div class="diag-name"><span class="diag-dot" :class="{ ok: item.ok }" />{{ item.name }}</div>
        <div class="diag-status">{{ item.ok ? '正常' : '异常' }}</div>
        <div class="diag-detail">{{ item.detail }}</div>
      </div>
    </div>
    <el-empty
      v-else-if="!loading"
      description="点击「运行诊断」探测 LLM / Embedding / Milvus / MySQL / MinIO 连通性"
      :image-size="72"
    />
  </section>
</template>

<style scoped>
.panel { background: #fff; border: 1px solid var(--border-color); border-radius: 10px; padding: 14px 16px; }
.panel-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--text-color); }
.panel-title-row { display: flex; align-items: center; justify-content: space-between; }
.panel-title-row .panel-title { margin-bottom: 0; }
.diag-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 12px; }
.diag-card { border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; }
.diag-ok { background: rgba(82, 196, 26, 0.04); border-color: rgba(82, 196, 26, 0.35); }
.diag-fail { background: rgba(234, 102, 104, 0.04); border-color: rgba(234, 102, 104, 0.4); }
.diag-name { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text-color); }
.diag-dot { width: 8px; height: 8px; border-radius: 50%; background: #ea6668; }
.diag-dot.ok { background: #52c41a; }
.diag-status { margin-top: 6px; font-size: 13px; font-weight: 600; color: #ea6668; }
.diag-ok .diag-status { color: #52c41a; }
.diag-detail { margin-top: 4px; font-size: 12px; color: var(--text-secondary); word-break: break-all; }
</style>
