<script setup lang="ts">
import type { MixedFolderNode } from '../../types/documents'

interface TreeOption {
  value: string
  label: string
  children?: TreeOption[]
}

defineProps<{
  moveVisible: boolean
  movingFolder: MixedFolderNode | null
  moveTargetFolderId: string | null
  moveTreeData: TreeOption[]
  fileMoveVisible: boolean
  fileMoveTargetFolderId: string | null
  fileMoveTreeData: TreeOption[]
  selectedFileCount: number
  loading: boolean
}>()

const emit = defineEmits<{
  (event: 'update:move-visible', visible: boolean): void
  (event: 'update:move-target-folder-id', folderId: string | null): void
  (event: 'confirm-move'): void
  (event: 'update:file-move-visible', visible: boolean): void
  (event: 'update:file-move-target-folder-id', folderId: string | null): void
  (event: 'confirm-file-move'): void
}>()
</script>

<template>
  <el-dialog
    :model-value="moveVisible"
    title="移动文件夹"
    width="480"
    @update:model-value="emit('update:move-visible', $event)"
  >
    <el-form label-width="80px" @submit.prevent>
      <el-form-item label="待移动">
        <span class="move-source">{{ movingFolder?.name }}</span>
      </el-form-item>
      <el-form-item label="目标位置">
        <el-tree-select
          :model-value="moveTargetFolderId"
          :data="moveTreeData"
          :props="{ label: 'label', value: 'value', children: 'children' }"
          node-key="value"
          check-strictly
          clearable
          placeholder="不选则移到 kb 根（成为顶级文件夹）"
          style="width: 100%"
          @update:model-value="emit('update:move-target-folder-id', $event)"
        />
        <div class="move-hint">
          顶级 folder 可移动到另一顶级下；子 folder 移到顶级 → 升为顶级；后端会自动阻止超层与同名冲突
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:move-visible', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="emit('confirm-move')">确认移动</el-button>
    </template>
  </el-dialog>

  <el-dialog
    :model-value="fileMoveVisible"
    title="移动文件"
    width="480"
    @update:model-value="emit('update:file-move-visible', $event)"
  >
    <el-form label-width="80px" @submit.prevent>
      <el-form-item label="待移动">
        <span class="move-source">已选 {{ selectedFileCount }} 个文件</span>
      </el-form-item>
      <el-form-item label="目标位置">
        <el-tree-select
          :model-value="fileMoveTargetFolderId"
          :data="fileMoveTreeData"
          :props="{ label: 'label', value: 'value', children: 'children' }"
          node-key="value"
          check-strictly
          clearable
          placeholder="选择目标文件夹"
          style="width: 100%"
          @update:model-value="emit('update:file-move-target-folder-id', $event)"
        />
        <div class="move-hint">
          仅限当前知识库内移动；目标文件夹存在同名文件时，该文件将被拒绝
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:file-move-visible', false)">取消</el-button>
      <el-button type="primary" @click="emit('confirm-file-move')">确认移动</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.move-source {
  font-weight: 500;
}

.move-hint {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 6px;
  line-height: 1.5;
}
</style>
