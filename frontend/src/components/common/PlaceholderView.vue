<script setup lang="ts">
defineProps<{
  title: string
  stage: string
  description?: string
}>()
</script>

<template>
  <div class="placeholder-view">
    <el-empty :description="`${title} · 阶段 ${stage} 待上线`" />
    <p v-if="description" class="placeholder-desc">{{ description }}</p>
  </div>
</template>

<style scoped>
.placeholder-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.placeholder-desc {
  color: var(--text-secondary);
  font-size: 13px;
  margin: 4px 0 0;
}
</style>
