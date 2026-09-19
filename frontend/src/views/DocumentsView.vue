<script setup lang="ts">
// 文档管理页（方案 B：树状单表）
//
// UI 布局：整页只有一张 el-table；行可能是 folder（可展开，含子 folder + 文件）
// 或 file（叶子）。folder 用统一的文件夹图标 + 系统/默认标记；file 用类型图标。
//
// 关键约定（与后端对齐）：
// - kb 下挂 folder 树（最深 2 层）；默认 folder（is_system）不可删可改名。
// - 上传目标 folder 由当前选中行推断：folder 行 → 自身 folder；file 行 → 所在 folder；
//   无选中 → 默认 folder。
// - 状态/搜索过滤在前端剪枝（displayTree），不重新请求。
// - 展开用受控 expandedKeys（Set→Array），便于新增/删除后保持展开。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import FilePreviewDialog from '../components/documents/FilePreviewDialog.vue'
import DocumentToolbar from '../components/documents/DocumentToolbar.vue'
import DocumentTreeTable from '../components/documents/DocumentTreeTable.vue'
import DocumentMoveDialogs from '../components/documents/DocumentMoveDialogs.vue'
import DocumentKnowledgeBaseDialog from '../components/documents/DocumentKnowledgeBaseDialog.vue'
import { useDocumentStore } from '../stores/document'
import { useAuthStore } from '../stores/auth'
import { useDocumentFolderDialogs } from '../composables/useDocumentFolderDialogs'
import { useDocumentFileActions } from '../composables/useDocumentFileActions'
import { useDocumentBatchActions } from '../composables/useDocumentBatchActions'
import type {
  FolderTreeNode,
  MixedFileNode,
  MixedFolderNode,
  MixedNode,
} from '../types/documents'

const store = useDocumentStore()
const auth = useAuthStore()

// ==================== 上传（文件 / 目录） ====================
type DocumentToolbarExpose = { clearFiles: () => void }
const toolbarRef = ref<DocumentToolbarExpose>()

async function handleUpload(files: File[]) {
  if (files.length === 0) {
    ElMessage.info('请先选择要上传的文件')
    return
  }
  try {
    await store.uploadFiles(files)
    toolbarRef.value?.clearFiles()
  } catch {
    // store 已提示错误
  }
}

async function handleDirectoryUpload(files: File[], paths: string[]) {
  if (files.length === 0) return
  try {
    await store.uploadDirectory(files, paths)
  } catch {
    // store 已提示
  }
}

// ==================== folder 操作 ====================

// ==================== 移动 folder ====================

type MoveTreeOption = {
  value: string
  label: string
  children?: MoveTreeOption[]
}

const moveDialogVisible = ref(false)
const moveTargetFolderId = ref<string | null>(null)
const movingFolder = ref<MixedFolderNode | null>(null)

/** 弹窗 tree 数据：把要移动的 folder 从树里剔除（避免循环），格式化成 { value, label, children }。 */
const moveTreeData = computed(() => {
  const strip = (nodes: FolderTreeNode[]): MoveTreeOption[] =>
    nodes
      .filter((n) => !movingFolder.value || n.folder_id !== movingFolder.value.folder_id)
      .map((n) => ({
        value: n.folder_id,
        label: n.name,
        children: strip(n.children),
      }))
  return strip(store.folderTree)
})

function handleMoveFolder(node: MixedFolderNode) {
  movingFolder.value = node
  moveTargetFolderId.value = node.parent_id // 默认不变
  moveDialogVisible.value = true
}

async function confirmMove() {
  if (!movingFolder.value) return
  const target = moveTargetFolderId.value
  try {
    await store.moveFolderToParent(movingFolder.value.folder_id, target)
    ElMessage.success(
      target ? `已移动到目标文件夹` : `已移到 kb 根（顶级）`,
    )
    moveDialogVisible.value = false
  } catch {
    // store 已提示（FolderSystemProtectedError / FolderDepthLimitError / FolderNameConflictError 等）
  }
}

// ==================== 文件批量移动 ====================

const fileMoveDialogVisible = ref(false)
const fileMoveTargetFolderId = ref<string | null>(null)

/** 文件移动弹窗目标树：展示全部 folder（与 folder 移动不同，不剔除任何节点）。 */
const fileMoveTreeData = computed(() => {
  const strip = (
    nodes: FolderTreeNode[],
  ): MoveTreeOption[] =>
    nodes.map((n) => ({
      value: n.folder_id,
      label: n.name,
      children: strip(n.children),
    }))
  return strip(store.folderTree)
})

function openFileMoveDialog() {
  fileMoveTargetFolderId.value = null
  fileMoveDialogVisible.value = true
}

async function confirmMoveFiles() {
  const target = fileMoveTargetFolderId.value
  if (!target) {
    ElMessage.warning('请选择目标文件夹')
    return
  }
  const docIds = selectedFiles.value.map((r) => r.doc_id)
  if (docIds.length === 0) return
  try {
    await store.moveDocs(docIds, target)
    fileMoveDialogVisible.value = false
    clearSelectedFiles()
  } catch {
    // store 已提示
  }
}

function findFolderImpl(roots: FolderTreeNode[], id: string): FolderTreeNode | null {
  for (const n of roots) {
    if (n.folder_id === id) return n
    const sub = findFolderImpl(n.children, id)
    if (sub) return sub
  }
  return null
}

const {
  handleCreateTopFolder,
  handleCreateSubFolder,
  handleRenameFolder,
  handleDeleteFolder,
} = useDocumentFolderDialogs({
  currentFolderId: () => store.currentFolderId,
  expandedKeys: store.expandedKeys,
  getFolderName: (id) => findFolderImpl(store.folderTree, id)?.name,
  createFolder: store.createFolder,
  renameFolder: store.renameFolder,
  confirmDeleteFolder: store.confirmDeleteFolder,
  expandAll: store.expandAll,
})

// ==================== 多选（批量移动文件） ====================

type DocumentTreeTableExpose = { clearSelection: () => void }
const treeTableRef = ref<DocumentTreeTableExpose>()
const selectedFiles = ref<MixedFileNode[]>([])

function clearSelectedFiles() {
  selectedFiles.value = []
  treeTableRef.value?.clearSelection()
}

const {
  batchDeleting,
  batchReprocessing,
  handleBatchDelete,
  handleBatchReprocess,
} = useDocumentBatchActions({
  getSelectedFiles: () => selectedFiles.value,
  removeDocs: store.removeDocs,
  reprocessDocs: store.reprocessDocs,
  clearSelection: clearSelectedFiles,
})

function onSelectionChange(rows: MixedNode[]) {
  selectedFiles.value = rows.filter(
    (r): r is MixedFileNode => r.node_type === 'file',
  )
}

// ==================== 行点击：选中并展开 ====================

function onRowClick(row: MixedNode) {
  store.selectNode(row.node_id)
}

// ==================== 文件行操作 ====================

async function handleDeleteDoc(row: MixedNode & { node_type: 'file' }) {
  try {
    await store.removeDoc(row.doc_id)
  } catch {
    // store 已提示
  }
}

// ==================== 批量操作 ====================

async function handleReprocess(row: MixedNode & { node_type: 'file' }) {
  try {
    await store.reprocessDoc(row.doc_id)
  } catch {
    // store 已提示
  }
}

// ==================== 文件预览 / 下载 ====================
const {
  previewVisible,
  previewDoc,
  downloadingIds,
  handlePreview,
  handleDownload,
} = useDocumentFileActions()

// 当前选中节点是否能"上传到此 folder"：仅 folder 行可作为上传目标
const canUploadToSelected = computed(
  () => !!store.currentFolderId && store.currentNodeKey?.startsWith('folder:'),
)

const kbDialogVisible = ref(false)
const newKbName = ref('')
const newKbDesc = ref('')

async function handleCreateKb() {
  const name = newKbName.value.trim()
  if (!name) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  try {
    await store.createKb(name, newKbDesc.value.trim())
    kbDialogVisible.value = false
    newKbName.value = ''
    newKbDesc.value = ''
    ElMessage.success('知识库已创建并切换')
  } catch (e) {
    ElMessage.error((e as Error).message || '创建失败')
  }
}

function currentKbName(): string {
  const kb = store.kbs.find((k) => k.kb_id === store.currentKbId)
  return kb?.name ?? ''
}
void currentKbName // 当前由 selectedTargetLabel 承担提示，保留以备 breadcrumb 后续接入

// 当前选中节点的目标 folder 显示（面包屑用）
const selectedTargetLabel = computed<string>(() => {
  if (!store.currentNodeKey) {
    const def = store.folderTree.find((f) => f.is_system)
    return def ? `${def.name}（默认）` : '默认文件夹'
  }
  if (store.currentNodeKey.startsWith('folder:')) {
    const f = findFolderImpl(store.folderTree, store.currentFolderId ?? '')
    return f?.name ?? ''
  }
  if (store.currentNodeKey.startsWith('doc:')) {
    const docId = store.currentNodeKey.slice('doc:'.length)
    const d = store.allDocs.find((x) => x.doc_id === docId)
    return d?.folder_path ?? ''
  }
  return ''
})

// ==================== 生命周期 ====================

onMounted(async () => {
  await store.loadKbs()
  await store.loadFolderTree()
  // 展开顶层 folder（内部对已展开 folder 触发懒加载，不拉全量）
  store.expandTopFolders()
})

onUnmounted(() => {
  store.stopPoll()
})
</script>

<template>
  <div class="documents-view">
    <!-- 顶部：知识库、搜索筛选、上传与批量操作 -->
    <DocumentToolbar
      ref="toolbarRef"
      :knowledge-bases="store.kbs"
      :current-kb-id="store.currentKbId"
      :status-filter="store.statusFilter"
      :can-edit="auth.canEditDocuments()"
      :uploading="store.uploading"
      :selected-file-count="selectedFiles.length"
      :batch-deleting="batchDeleting"
      :batch-reprocessing="batchReprocessing"
      @select-kb="store.setCurrentKb"
      @create-kb="kbDialogVisible = true"
      @search="store.setSearch"
      @clear-search="store.setSearch('')"
      @status-change="store.setStatus"
      @create-top-folder="handleCreateTopFolder"
      @upload-files="handleUpload"
      @upload-directory="handleDirectoryUpload"
      @move-files="openFileMoveDialog"
      @batch-delete="handleBatchDelete"
      @batch-reprocess="handleBatchReprocess"
      @expand-all="store.expandAll"
      @collapse-all="store.collapseAll"
    />
    <!-- 选中节点提示条（上传目标） -->
    <div v-if="auth.canEditDocuments()" class="target-hint">
      <span class="hint-label">上传目标：</span>
      <span class="hint-value">
        <span v-if="!store.currentNodeKey" class="hint-default">{{ selectedTargetLabel }}</span>
        <span v-else-if="canUploadToSelected">{{ selectedTargetLabel }}</span>
        <span v-else class="hint-file">文件「{{ selectedTargetLabel }}」（将上传到其所在文件夹）</span>
      </span>
    </div>

    <!-- 树状单表 -->
    <DocumentTreeTable
      ref="treeTableRef"
      :loading="store.loading"
      :nodes="store.displayTree"
      :expanded-keys="store.expandedKeys"
      :current-node-key="store.currentNodeKey"
      :loading-folder-ids="store.loadingFolderIds"
      :deleting-folder-ids="store.deletingFolderIds"
      :deleting-ids="store.deletingIds"
      :reprocessing-ids="store.reprocessingIds"
      :downloading-ids="downloadingIds"
      :can-edit="auth.canEditDocuments()"
      @row-click="onRowClick"
      @selection-change="onSelectionChange"
      @update-expand-keys="store.updateExpandKeys"
      @create-sub-folder="handleCreateSubFolder"
      @rename-folder="handleRenameFolder"
      @move-folder="handleMoveFolder"
      @delete-folder="handleDeleteFolder"
      @preview="handlePreview"
      @download="handleDownload"
      @reprocess="handleReprocess"
      @delete-doc="handleDeleteDoc"
    />

    <DocumentKnowledgeBaseDialog
      :visible="kbDialogVisible"
      :name="newKbName"
      :description="newKbDesc"
      @update:visible="kbDialogVisible = $event"
      @update:name="newKbName = $event"
      @update:description="newKbDesc = $event"
      @create="handleCreateKb"
    />

    <DocumentMoveDialogs
      :move-visible="moveDialogVisible"
      :moving-folder="movingFolder"
      :move-target-folder-id="moveTargetFolderId"
      :move-tree-data="moveTreeData"
      :file-move-visible="fileMoveDialogVisible"
      :file-move-target-folder-id="fileMoveTargetFolderId"
      :file-move-tree-data="fileMoveTreeData"
      :selected-file-count="selectedFiles.length"
      :loading="store.uploading"
      @update:move-visible="moveDialogVisible = $event"
      @update:move-target-folder-id="moveTargetFolderId = $event"
      @confirm-move="confirmMove"
      @update:file-move-visible="fileMoveDialogVisible = $event"
      @update:file-move-target-folder-id="fileMoveTargetFolderId = $event"
      @confirm-file-move="confirmMoveFiles"
    />

    <!-- 文件预览弹窗（PDF / 图片 / TXT） -->
    <FilePreviewDialog v-model="previewVisible" :doc="previewDoc" />
  </div>
</template>

<style scoped>
.documents-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 16px 20px;
  gap: 10px;
  box-sizing: border-box;
}

.target-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 4px 8px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.hint-label {
  font-weight: 500;
}

.hint-value {
  color: var(--el-text-color-primary);
}

.hint-default {
  color: var(--el-color-warning);
}

.hint-file {
  color: var(--el-text-color-regular);
}

</style>
