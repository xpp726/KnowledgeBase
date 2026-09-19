<script setup lang="ts">
defineProps<{
  title: string
  rows: Array<{ label: string; value: string }>
  mono?: boolean
}>()
</script>

<template>
  <section class="panel">
    <div class="panel-title">{{ title }}</div>
    <div v-if="rows.length" class="info-grid">
      <div v-for="row in rows" :key="row.label" class="info-row">
        <span class="info-label">{{ row.label }}</span>
        <span class="info-value" :class="{ mono }">{{ row.value }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.panel { background: #fff; border: 1px solid var(--border-color); border-radius: 10px; padding: 14px 16px; }
.panel-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--text-color); }
.info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 4px 24px; }
.info-row { display: flex; justify-content: space-between; gap: 16px; padding: 6px 0; border-bottom: 1px dashed var(--border-color); font-size: 13px; }
.info-label { color: var(--text-secondary); white-space: nowrap; }
.info-value { color: var(--text-color); text-align: right; word-break: break-all; }
.mono { font-family: Consolas, Monaco, monospace; font-size: 12px; }
</style>
