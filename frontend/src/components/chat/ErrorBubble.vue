<script setup lang="ts">
// 失败/超时气泡 + 重试按钮（B3）
defineProps<{ message: string }>()
const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="error-bubble">
    <el-icon class="error-icon"><WarningFilled /></el-icon>
    <span class="error-text">{{ message }}</span>
    <el-button size="small" type="danger" plain @click="emit('retry')">重试</el-button>
  </div>
</template>

<style scoped>
.error-bubble {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding: 8px 12px;
  background: rgba(234, 102, 104, 0.08);
  border: 1px solid rgba(234, 102, 104, 0.35);
  border-radius: 8px;
  font-size: 13px;
}

.error-icon {
  flex-shrink: 0;
}

.error-text {
  flex: 1;
  min-width: 0;
  color: var(--text);
}
</style>
