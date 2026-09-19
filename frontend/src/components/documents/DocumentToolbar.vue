<script setup lang="ts">
import { ref } from 'vue'
import { Plus, Upload } from '@element-plus/icons-vue'
import type { UploadFile, UploadInstance, UploadUserFile } from 'element-plus'
import type { DocStatus, KnowledgeBase } from '../../types/documents'

defineProps<{
  knowledgeBases: KnowledgeBase[]
  currentKbId: string
  statusFilter: DocStatus | ''
  canEdit: boolean
  uploading: boolean
  selectedFileCount: number
  batchDeleting: boolean
  batchReprocessing: boolean
}>()

const emit = defineEmits<{
  (event: 'select-kb', kbId: string): void
  (event: 'create-kb'): void
  (event: 'search', value: string): void
  (event: 'clear-search'): void
  (event: 'status-change', status: DocStatus | ''): void
  (event: 'create-top-folder'): void
  (event: 'upload-files', files: File[]): void
  (event: 'upload-directory', files: File[], paths: string[]): void
  (event: 'move-files'): void
  (event: 'batch-delete'): void
  (event: 'batch-reprocess'): void
  (event: 'expand-all'): void
  (event: 'collapse-all'): void
}>()

const uploadRef = ref<UploadInstance>()
const pendingFiles = ref<UploadUserFile[]>([])
const searchInput = ref('')
const dirInputRef = ref<HTMLInputElement>()

function onFileChange(_file: UploadFile, files: UploadUserFile[]) {
  pendingFiles.value = files
}

function uploadSelectedFiles() {
  const files = pendingFiles.value
    .map((file) => file.raw)
    .filter((file): file is NonNullable<typeof file> => Boolean(file))
  if (files.length > 0) emit('upload-files', files)
}

function triggerDirPicker() {
  dirInputRef.value?.click()
}

function onDirChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (files.length > 0) {
    emit(
      'upload-directory',
      files,
      files.map((file) => file.webkitRelativePath || file.name),
    )
  }
  input.value = ''
}

function clearFiles() {
  pendingFiles.value = []
  uploadRef.value?.clearFiles()
}

defineExpose({ clearFiles })
</script>

<template>
  <div class="kb-bar">
    <el-select
      :model-value="currentKbId"
      class="kb-select"
      placeholder="选择知识库"
      @update:model-value="(value: string) => emit('select-kb', value)"
    >
      <el-option
        v-for="kb in knowledgeBases"
        :key="kb.kb_id"
        :label="`${kb.name}（${kb.doc_count}）`"
        :value="kb.kb_id"
      />
    </el-select>
    <el-button v-if="canEdit" class="kb-create" @click="emit('create-kb')">
      新建知识库
    </el-button>

    <div class="bar-divider" />

    <el-input
      v-model="searchInput"
      class="search-input"
      placeholder="按文件名搜索"
      clearable
      @clear="emit('clear-search')"
      @keyup.enter="emit('search', searchInput.trim())"
    />
    <el-select
      :model-value="statusFilter"
      class="status-select"
      placeholder="全部状态"
      clearable
      @update:model-value="(value: DocStatus | '') => emit('status-change', value ?? '')"
    >
      <el-option label="排队中" value="pending" />
      <el-option label="解析中" value="ingesting" />
      <el-option label="向量化中" value="embedding" />
      <el-option label="已完成" value="done" />
      <el-option label="失败" value="failed" />
    </el-select>

    <div class="bar-divider" />

    <template v-if="canEdit">
      <el-button type="primary" @click="emit('create-top-folder')">
        <el-icon><Plus /></el-icon>
        新建文件夹
      </el-button>
      <el-upload
        ref="uploadRef"
        class="upload-btn"
        :auto-upload="false"
        :show-file-list="false"
        multiple
        accept=".pdf,.docx,.xlsx,.xlsm,.txt,.md,.markdown"
        :on-change="onFileChange"
      >
        <el-button type="success">
          <el-icon><Upload /></el-icon>
          选择文件
        </el-button>
      </el-upload>
      <el-button
        v-if="pendingFiles.length > 0"
        type="success"
        plain
        :loading="uploading"
        @click="uploadSelectedFiles"
      >
        上传（{{ pendingFiles.length }}）
      </el-button>
      <el-button type="success" plain :loading="uploading" @click="triggerDirPicker">
        上传文件夹
      </el-button>
      <el-button
        type="primary"
        plain
        :disabled="selectedFileCount === 0"
        @click="emit('move-files')"
      >
        移动到...
      </el-button>
      <el-popconfirm
        :title="`删除选中的 ${selectedFileCount} 个文件？向量、文件与数据库记录一并移除，不可恢复。`"
        width="280"
        confirm-button-text="删除"
        cancel-button-text="取消"
        @confirm="emit('batch-delete')"
      >
        <template #reference>
          <el-button
            type="danger"
            plain
            :disabled="selectedFileCount === 0"
            :loading="batchDeleting"
          >
            批量删除
          </el-button>
        </template>
      </el-popconfirm>
      <el-button
        type="warning"
        plain
        :disabled="selectedFileCount === 0"
        :loading="batchReprocessing"
        @click="emit('batch-reprocess')"
      >
        批量解析
      </el-button>
      <input
        ref="dirInputRef"
        type="file"
        webkitdirectory
        directory
        multiple
        style="display: none"
        @change="onDirChange"
      />
    </template>

    <div class="bar-spacer" />

    <el-button size="small" link @click="emit('expand-all')">展开</el-button>
    <el-button size="small" link @click="emit('collapse-all')">折叠</el-button>
  </div>
</template>

<style scoped>
.kb-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.kb-select {
  width: 240px;
}

.bar-divider {
  width: 1px;
  height: 18px;
  background: var(--el-border-color-lighter);
  margin: 0 4px;
}

.bar-spacer {
  flex: 1;
}

.search-input {
  width: 220px;
}

.status-select {
  width: 130px;
}
</style>
