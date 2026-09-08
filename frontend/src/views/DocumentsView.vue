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
import { ElMessage, ElMessageBox } from 'element-plus'
import type { TableInstance, UploadFile, UploadInstance, UploadUserFile } from 'element-plus'
import { useDocumentStore } from '../stores/document'
import { useAuthStore } from '../stores/auth'
import type {
  DocStatus,
  FolderTreeNode,
  MixedFileNode,
  MixedFolderNode,
  MixedNode,
} from '../types/api'

const store = useDocumentStore()
const auth = useAuthStore()

// ==================== 上传（文件 / 目录） ====================
const uploadRef = ref<UploadInstance>()
const pendingFiles = ref<UploadUserFile[]>([])

function onFileChange(_file: UploadFile, files: UploadUserFile[]) {
  pendingFiles.value = files
}

function clearFiles() {
  pendingFiles.value = []
  uploadRef.value?.clearFiles()
}

async function handleUpload() {
  const files = pendingFiles.value
    .map((f) => f.raw)
    .filter((raw): raw is NonNullable<typeof raw> => Boolean(raw))
  if (files.length === 0) {
    ElMessage.info('请先选择要上传的文件')
    return
  }
  try {
    await store.uploadFiles(files)
    clearFiles()
  } catch {
    // store 已提示错误
  }
}

// 上传目录（webkitdirectory）
const dirInputRef = ref<HTMLInputElement>()
function triggerDirPicker() {
  dirInputRef.value?.click()
}
async function onDirChange(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (files.length === 0) return
  const paths = files.map((f) => f.webkitRelativePath || f.name)
  try {
    await store.uploadDirectory(files, paths)
  } catch {
    // store 已提示
  } finally {
    input.value = ''
  }
}

// ==================== folder 操作 ====================

async function handleCreateTopFolder() {
  let name = ''
  try {
    const r = await ElMessageBox.prompt(
      '输入新文件夹名（kb 顶级）',
      '新建文件夹',
      { inputPlaceholder: '例如：研发资料', confirmButtonText: '创建', cancelButtonText: '取消' },
    )
    name = r.value
  } catch {
    return
  }
  try {
    await store.createFolder(null, name.trim())
    // 新建后自动展开（根 folder 一定可见，新顶级无须展开动作）
    store.expandAll()
  } catch {
    // store 已提示
  }
}

async function handleCreateSubFolder() {
  if (!store.currentFolderId) {
    ElMessage.warning('请先选中一个文件夹，再新建子文件夹')
    return
  }
  const parent = findFolderImpl(store.folderTree, store.currentFolderId)
  let name = ''
  try {
    const r = await ElMessageBox.prompt(
      `在「${parent?.name ?? '当前文件夹'}」下新建子文件夹`,
      '新建子文件夹',
      { inputPlaceholder: '例如：合同', confirmButtonText: '创建', cancelButtonText: '取消' },
    )
    name = r.value
  } catch {
    return
  }
  try {
    const newFolder = await store.createFolder(store.currentFolderId, name.trim())
    // 自动展开新建 folder 的父节点，确保新 folder 行可见
    const parentKey = `folder:${store.currentFolderId}`
    if (!store.expandedKeys.includes(parentKey)) {
      store.expandedKeys.push(parentKey)
    }
    store.expandedKeys.push(`folder:${newFolder.folder_id}`)
  } catch {
    // store 已提示
  }
}

async function handleRenameFolder(node: MixedFolderNode) {
  let newName = ''
  try {
    const r = await ElMessageBox.prompt(
      `新名称（${node.is_system ? '默认文件夹可改名' : '重命名'}）`,
      '重命名文件夹',
      { inputValue: node.name, confirmButtonText: '确认', cancelButtonText: '取消' },
    )
    newName = r.value
  } catch {
    return
  }
  try {
    await store.renameFolder(node.folder_id, newName.trim())
  } catch {
    // store 已提示
  }
}

async function handleDeleteFolder(node: MixedFolderNode) {
  await store.confirmDeleteFolder(node.folder_id)
}

// ==================== 移动 folder ====================

const moveDialogVisible = ref(false)
const moveTargetFolderId = ref<string | null>(null)
const movingFolder = ref<MixedFolderNode | null>(null)

/** 弹窗 tree 数据：把要移动的 folder 从树里剔除（避免循环），格式化成 { value, label, children }。 */
const moveTreeData = computed(() => {
  const strip = (nodes: FolderTreeNode[]): Array<{ value: string; label: string; children?: unknown[] }> =>
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
  ): Array<{ value: string; label: string; children?: unknown[] }> =>
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
    tableRef.value?.clearSelection()
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

// ==================== 多选（批量移动文件） ====================

const tableRef = ref<TableInstance>()
const selectedFiles = ref<MixedFileNode[]>([])

// 仅文件行可勾选（folder 行走行内"移动到..."按钮）
function isFileSelectable(row: MixedNode): boolean {
  return row.node_type === 'file'
}

function onSelectionChange(rows: MixedNode[]) {
  selectedFiles.value = rows.filter(
    (r): r is MixedFileNode => r.node_type === 'file',
  )
}

// ==================== 行点击：选中并展开 ====================

function onRowClick(row: MixedNode) {
  store.selectNode(row.node_id)
}

// 行 class：高亮当前选中节点
const rowClassName = ({ row }: { row: MixedNode }) =>
  row.node_id === store.currentNodeKey ? 'is-selected-row' : ''

// 缩进层次：每层 24px；首格 paddingLeft = depth * 24px。
// 用 cell-style 而不是 el-table 自带 tree 缩进，便于精细控制（file 行缩进 = folder.depth + 1）。
// 注意 element-plus el-table 的 cell-style callback 参数是 { row, column, rowIndex, columnIndex }，
// 列号必须用 columnIndex（旧实现误用 column.index 一直为 undefined 所以缩进从未生效）。
const INDENT_PX = 24
function cellStyle({
  row,
  column,
}: {
  row: MixedNode
  column: unknown
  rowIndex: number
  columnIndex: number
}) {
  // “名称”列与“勾选”列共用同一层级缩进：勾选框随行缩进，
  // 与格式图标间距恒定（44px 列宽 + cell padding），视觉成组
  if (!column) return {}
  const c = column as { label?: string; type?: string }
  if (c.label !== '名称' && c.type !== 'selection') return {}
  const d = row.node_type === 'folder' ? row.depth : row._depth
  return { paddingLeft: `${d * INDENT_PX}px` }
}

// 展开按钮：folder 行专属。点击切换展开，不触发行选中。
function onToggleExpand(row: MixedNode) {
  if (row.node_type !== 'folder') return
  store.toggleExpand(row.node_id)
}

// ==================== 文件行操作 ====================

async function handleDeleteDoc(row: MixedNode & { node_type: 'file' }) {
  try {
    await store.removeDoc(row.doc_id)
  } catch {
    // store 已提示
  }
}

async function handleReprocess(row: MixedNode & { node_type: 'file' }) {
  try {
    await store.reprocessDoc(row.doc_id)
  } catch {
    // store 已提示
  }
}

// ==================== 工具栏：搜索 / 筛选 ====================
const searchInput = ref('')
function applySearch() {
  store.setSearch(searchInput.value.trim())
}
function clearSearch() {
  searchInput.value = ''
  store.setSearch('')
}

// ==================== 视图辅助 ====================
const STATUS_META: Record<DocStatus, { text: string; type: 'info' | 'primary' | 'success' | 'danger' }> = {
  pending: { text: '排队中', type: 'info' },
  ingesting: { text: '解析中', type: 'primary' },
  embedding: { text: '向量化中', type: 'primary' },
  done: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
}

function formatSize(bytes: number): string {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(ts: number): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

// 文件类型图标：按 file_ext 着色的小方块标签
const EXT_COLOR: Record<string, string> = {
  '.pdf': 'pdf',
  '.docx': 'doc',
  '.doc': 'doc',
  '.xlsx': 'xls',
  '.xlsm': 'xls',
  '.pptx': 'ppt',
  '.txt': 'txt',
  '.md': 'md',
  '.markdown': 'md',
}
function extClass(ext: string): string {
  return `ext-tag ext-${EXT_COLOR[ext] ?? 'default'}`
}

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
  await store.loadAllDocs()
  store.expandTopFolders()
})

onUnmounted(() => {
  store.stopPoll()
})
</script>

<template>
  <div class="documents-view">
    <!-- 顶部：kb + 工具栏 -->
    <div class="kb-bar">
      <el-select
        :model-value="store.currentKbId"
        class="kb-select"
        placeholder="选择知识库"
        @update:model-value="(v: string) => store.setCurrentKb(v)"
      >
        <el-option
          v-for="kb in store.kbs"
          :key="kb.kb_id"
          :label="`${kb.name}（${kb.doc_count}）`"
          :value="kb.kb_id"
        />
      </el-select>
      <el-button v-if="auth.canEditDocuments()" class="kb-create" @click="kbDialogVisible = true">
        新建知识库
      </el-button>

      <div class="bar-divider" />

      <el-input
        v-model="searchInput"
        class="search-input"
        placeholder="按文件名搜索"
        clearable
        @clear="clearSearch"
        @keyup.enter="applySearch"
      />
      <el-select
        :model-value="store.statusFilter"
        class="status-select"
        placeholder="全部状态"
        clearable
        @update:model-value="(v: DocStatus | '') => store.setStatus(v ?? '')"
      >
        <el-option label="排队中" value="pending" />
        <el-option label="解析中" value="ingesting" />
        <el-option label="向量化中" value="embedding" />
        <el-option label="已完成" value="done" />
        <el-option label="失败" value="failed" />
      </el-select>

      <div class="bar-divider" />

      <template v-if="auth.canEditDocuments()">
        <el-button type="primary" @click="handleCreateTopFolder">
          <el-icon><Plus /></el-icon>
          新建文件夹
        </el-button>
        <el-button
          type="primary"
          plain
          :disabled="!store.currentFolderId"
          @click="handleCreateSubFolder"
        >
          +子文件夹
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
          :loading="store.uploading"
          @click="handleUpload"
        >
          上传（{{ pendingFiles.length }}）
        </el-button>
        <el-button type="success" plain :loading="store.uploading" @click="triggerDirPicker">
          上传文件夹
        </el-button>
        <el-button
          type="primary"
          plain
          :disabled="selectedFiles.length === 0"
          @click="openFileMoveDialog"
        >
          移动到...
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

      <el-button size="small" link @click="store.expandAll">展开</el-button>
      <el-button size="small" link @click="store.collapseAll">折叠</el-button>
    </div>

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
    <el-table
      v-loading="store.loading"
      :data="store.displayTree"
      class="mixed-table"
      row-key="node_id"
      :tree-props="{ children: 'children' }"
      :expand-row-keys="store.expandedKeys"
      :row-class-name="rowClassName"
      :cell-style="cellStyle"
      :default-expand-all="false"
      empty-text="暂无文件夹与文件"
      @row-click="onRowClick"
      @selection-change="onSelectionChange"
      @update:expand-row-keys="store.updateExpandKeys"
    >
      <el-table-column
        v-if="auth.canEditDocuments()"
        type="selection"
        width="44"
        :selectable="isFileSelectable"
      />
      <el-table-column label="名称" min-width="420">
        <template #default="{ row }: { row: MixedNode }">
          <template v-if="row.node_type === 'folder'">
            <div class="folder-cell">
              <button
                class="expand-btn"
                :aria-label="store.expandedKeys.includes(row.node_id) ? '折叠' : '展开'"
                @click.stop="onToggleExpand(row)"
              >
                <span class="expand-icon" :class="{ 'is-expanded': store.expandedKeys.includes(row.node_id) }">▶</span>
              </button>
              <span class="folder-icon">📁</span>
              <span class="folder-name">{{ row.name }}</span>
              <el-tag v-if="row.is_system" size="small" type="warning" effect="plain">默认</el-tag>
              <span class="folder-meta">
                {{ row.total_doc_count }} 个文档
                <span v-if="row.direct_doc_count !== row.total_doc_count" class="folder-meta-sub">
                  （直属 {{ row.direct_doc_count }}）
                </span>
              </span>
            </div>
          </template>
          <template v-else>
            <div class="file-cell">
              <span class="file-icon" :class="extClass(row.file_ext)">{{ row.file_ext.toUpperCase().replace('.', '') }}</span>
              <span class="file-name">{{ row.file_name }}</span>
              <span v-if="row._show_path && row.folder_path" class="folder-path-hint">{{ row.folder_path }}</span>
            </div>
          </template>
        </template>
      </el-table-column>

      <el-table-column label="大小 / 文件数" width="120">
        <template #default="{ row }: { row: MixedNode }">
          <template v-if="row.node_type === 'folder'">
            <span class="muted">文件夹</span>
          </template>
          <template v-else>
            {{ formatSize(row.file_size) }}
          </template>
        </template>
      </el-table-column>

      <el-table-column label="状态" width="100">
        <template #default="{ row }: { row: MixedNode }">
          <template v-if="row.node_type === 'file'">
            <el-tooltip
              :content="row.status === 'failed' ? row.error || '解析失败' : ''"
              placement="top"
              :disabled="row.status !== 'failed'"
            >
              <el-tag :type="STATUS_META[row.status].type" size="small">
                {{ STATUS_META[row.status].text }}
              </el-tag>
            </el-tooltip>
          </template>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>

      <el-table-column label="分块" width="70" align="right">
        <template #default="{ row }: { row: MixedNode }">
          <template v-if="row.node_type === 'file'">
            {{ row.chunk_count || '-' }}
          </template>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>

      <el-table-column label="页数" width="70" align="right">
        <template #default="{ row }: { row: MixedNode }">
          <template v-if="row.node_type === 'file'">
            {{ row.page_count || '-' }}
          </template>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>

      <el-table-column label="更新时间" width="170">
        <template #default="{ row }: { row: MixedNode }">
          <template v-if="row.node_type === 'file'">{{ formatTime(row.updated_at) }}</template>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }: { row: MixedNode }">
          <template v-if="row.node_type === 'folder'">
            <template v-if="auth.canEditDocuments()">
              <el-button link type="primary" size="small" @click.stop="handleCreateSubFolder">
                +子文件夹
              </el-button>
              <el-button link type="primary" size="small" @click.stop="handleRenameFolder(row)">
                重命名
              </el-button>
              <el-button link type="primary" size="small" @click.stop="handleMoveFolder(row)">
                移动到...
              </el-button>
              <el-button
                link
                type="danger"
                size="small"
                :disabled="store.deletingFolderIds.has(row.folder_id)"
                @click.stop="handleDeleteFolder(row)"
              >
                {{ store.deletingFolderIds.has(row.folder_id) ? '删除中' : '删除' }}
              </el-button>
            </template>
            <span v-else class="readonly-tag">只读</span>
          </template>
          <template v-else>
            <template v-if="auth.canEditDocuments()">
              <el-button
                v-if="row.status === 'done'"
                link
                type="primary"
                size="small"
                :loading="store.reprocessingIds.has(row.doc_id)"
                @click.stop="handleReprocess(row)"
              >
                重新解析
              </el-button>
              <el-button
                v-else-if="row.status === 'failed'"
                link
                type="warning"
                size="small"
                :loading="store.reprocessingIds.has(row.doc_id)"
                @click.stop="handleReprocess(row)"
              >
                重试
              </el-button>
              <el-button v-else link type="info" size="small" disabled>处理中</el-button>
              <el-popconfirm
                title="删除后向量、文件与记录一并移除，确认删除？"
                width="220"
                confirm-button-text="删除"
                cancel-button-text="取消"
                @confirm.stop="handleDeleteDoc(row)"
              >
                <template #reference>
                  <el-button
                    link
                    type="danger"
                    size="small"
                    :loading="store.deletingIds.has(row.doc_id)"
                    @click.stop
                  >
                    删除
                  </el-button>
                </template>
              </el-popconfirm>
            </template>
            <span v-else class="readonly-tag">只读</span>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建知识库弹窗 -->
    <el-dialog v-model="kbDialogVisible" title="新建知识库" width="420">
      <el-form label-width="80px" @submit.prevent>
        <el-form-item label="名称" required>
          <el-input v-model="newKbName" placeholder="例如：研发资料库" maxlength="64" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="newKbDesc" type="textarea" :rows="2" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="kbDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreateKb">创建</el-button>
      </template>
    </el-dialog>

    <!-- 移动 folder 弹窗 -->
    <el-dialog v-model="moveDialogVisible" title="移动文件夹" width="480">
      <el-form label-width="80px" @submit.prevent>
        <el-form-item label="待移动">
          <span class="move-source">{{ movingFolder?.name }}</span>
        </el-form-item>
        <el-form-item label="目标位置">
          <el-tree-select
            v-model="moveTargetFolderId"
            :data="moveTreeData"
            :props="{ label: 'label', value: 'value', children: 'children' }"
            node-key="value"
            check-strictly
            clearable
            placeholder="不选则移到 kb 根（成为顶级文件夹）"
            style="width: 100%"
          />
          <div class="move-hint">
            顶级 folder 可移动到另一顶级下；子 folder 移到顶级 → 升为顶级；后端会自动阻止超层与同名冲突
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="moveDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="store.uploading" @click="confirmMove">确认移动</el-button>
      </template>
    </el-dialog>

    <!-- 文件批量移动弹窗 -->
    <el-dialog v-model="fileMoveDialogVisible" title="移动文件" width="480">
      <el-form label-width="80px" @submit.prevent>
        <el-form-item label="待移动">
          <span class="move-source">已选 {{ selectedFiles.length }} 个文件</span>
        </el-form-item>
        <el-form-item label="目标位置">
          <el-tree-select
            v-model="fileMoveTargetFolderId"
            :data="fileMoveTreeData"
            :props="{ label: 'label', value: 'value', children: 'children' }"
            node-key="value"
            check-strictly
            clearable
            placeholder="选择目标文件夹"
            style="width: 100%"
          />
          <div class="move-hint">
            仅限当前知识库内移动；目标文件夹存在同名文件时，该文件将被拒绝
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="fileMoveDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmMoveFiles">确认移动</el-button>
      </template>
    </el-dialog>
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

.mixed-table {
  flex: 1;
  min-height: 0;
}

.mixed-table :deep(.is-selected-row) {
  background-color: var(--el-color-primary-light-9) !important;
}

/* ============ folder 行 ============ */
.folder-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
}

.expand-btn {
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 0;
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-regular);
}

.expand-icon {
  display: inline-block;
  font-size: 10px;
  transition: transform 0.15s ease;
}

.expand-icon.is-expanded {
  transform: rotate(90deg);
}

.folder-icon {
  font-size: 16px;
}

.folder-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.folder-meta {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  padding: 1px 8px;
  border-radius: 8px;
}

.folder-meta-sub {
  opacity: 0.7;
}

/* ============ file 行 ============ */
.file-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
}

.file-icon {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  padding: 3px 6px;
  border-radius: 4px;
  color: #fff;
  min-width: 36px;
  text-align: center;
  flex-shrink: 0;
}

.ext-pdf {
  background: #e74c3c;
}
.ext-doc {
  background: #2c5fa3;
}
.ext-xls {
  background: #1d6f42;
}
.ext-ppt {
  background: #d24726;
}
.ext-txt {
  background: #6c757d;
}
.ext-md {
  background: #8b5cf6;
}
.ext-default {
  background: #94a3b8;
}

.file-name {
  font-weight: 500;
}

.folder-path-hint {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-left: 8px;
  padding: 0 6px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
}

.muted {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}

.readonly-tag {
  font-size: 12px;
  color: var(--text-secondary, #9ca3af);
}

/* 让 el-table 树形展开缩进对齐自定义展开按钮：
   - 隐藏自带 el-table__expand-icon（用自定义 ▶ 按钮）
   - 隐藏内置 indent span，让 cellStyle 的 paddingLeft 完全控制层级缩进
   - cell 的 left padding 归零（cellStyle 接管） */
.mixed-table :deep(.el-table__expand-icon) {
  display: none !important;
}
.mixed-table :deep(.el-table__indent) {
  display: none !important;
}
.mixed-table :deep(td.el-table__cell:first-child .cell) {
  padding-left: 0 !important;
}
/* 勾选列 td 提升层级：checkbox 随行缩进（cellStyle paddingLeft）后落在相邻列区域内，
   必须保证勾选框本身可点击、不被名称列 td 覆盖 */
.mixed-table :deep(td.el-table-column--selection) {
  z-index: 2;
}

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