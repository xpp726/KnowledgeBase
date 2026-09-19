<script setup lang="ts">
defineProps<{
  visible: boolean
  name: string
  description: string
}>()

const emit = defineEmits<{
  (event: 'update:visible', visible: boolean): void
  (event: 'update:name', name: string): void
  (event: 'update:description', description: string): void
  (event: 'create'): void
}>()
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="新建知识库"
    width="420"
    @update:model-value="emit('update:visible', $event)"
  >
    <el-form label-width="80px" @submit.prevent>
      <el-form-item label="名称" required>
        <el-input
          :model-value="name"
          placeholder="例如：研发资料库"
          maxlength="64"
          @update:model-value="emit('update:name', $event)"
        />
      </el-form-item>
      <el-form-item label="描述">
        <el-input
          :model-value="description"
          type="textarea"
          :rows="2"
          maxlength="200"
          @update:model-value="emit('update:description', $event)"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="emit('create')">创建</el-button>
    </template>
  </el-dialog>
</template>
