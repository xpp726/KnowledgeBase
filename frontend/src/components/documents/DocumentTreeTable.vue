<script setup lang="ts">
import { ref } from 'vue'
import type { TableInstance } from 'element-plus'
import type {
  DocStatus,
  MixedFileNode,
  MixedFolderNode,
  MixedNode,
} from '../../types/documents'
import { formatBytes, formatDateTime } from '../../utils/format'

const props = defineProps<{
  loading: boolean
  nodes: MixedNode[]
  expandedKeys: string[]
  currentNodeKey: string | null
  loadingFolderIds: Set<string>
  deletingFolderIds: Set<string>
  deletingIds: Set<string>
  reprocessingIds: Set<string>
  downloadingIds: Set<string>
  canEdit: boolean
}>()

const emit = defineEmits<{
  (event: 'row-click', row: MixedNode): void
  (event: 'selection-change', rows: MixedNode[]): void
  (event: 'update-expand-keys', keys: string[]): void
  (event: 'create-sub-folder'): void
  (event: 'rename-folder', row: MixedFolderNode): void
  (event: 'move-folder', row: MixedFolderNode): void
  (event: 'delete-folder', row: MixedFolderNode): void
  (event: 'preview', row: MixedFileNode): void
  (event: 'download', row: MixedFileNode): void
  (event: 'reprocess', row: MixedFileNode): void
  (event: 'delete-doc', row: MixedFileNode): void
}>()

const tableRef = ref<TableInstance>()

defineExpose({
  clearSelection: () => tableRef.value?.clearSelection(),
})

const STATUS_META: Record<DocStatus, { text: string; type: 'info' | 'primary' | 'success' | 'danger' }> = {
  pending: { text: '排队中', type: 'info' },
  ingesting: { text: '解析中', type: 'primary' },
  embedding: { text: '向量化中', type: 'primary' },
  done: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
}

const INDENT_PX = 24

function isFileSelectable(row: MixedNode): boolean {
  return row.node_type === 'file'
}

function rowClassName({ row }: { row: MixedNode }) {
  return row.node_id === props.currentNodeKey ? 'is-selected-row' : ''
}

function cellStyle({
  row,
  column,
}: {
  row: MixedNode
  column: unknown
  rowIndex: number
  columnIndex: number
}) {
  if (!column) return {}
  const c = column as { label?: string; type?: string }
  if (c.label !== '名称' && c.type !== 'selection') return {}
  const depth = row.node_type === 'folder' ? row.depth : row._depth
  return { paddingLeft: `${depth * INDENT_PX}px` }
}

function onSelectionChange(rows: MixedNode[]) {
  emit('selection-change', rows)
}

function onRowClick(row: MixedNode) {
  emit('row-click', row)
}

function onToggleExpand(row: MixedNode) {
  if (row.node_type !== 'folder') return
  const nextKeys = props.expandedKeys.includes(row.node_id)
    ? props.expandedKeys.filter((key) => key !== row.node_id)
    : [...props.expandedKeys, row.node_id]
  emit('update-expand-keys', nextKeys)
}

const PREVIEW_EXTS = new Set([
  '.pdf',
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
  '.bmp',
  '.txt',
])

function isPreviewable(ext: string): boolean {
  return PREVIEW_EXTS.has((ext || '').toLowerCase())
}

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
</script>

<template>
  <el-table
    ref="tableRef"
    v-loading="loading"
    :data="nodes"
    class="mixed-table"
    row-key="node_id"
    :tree-props="{ children: 'children' }"
    :expand-row-keys="expandedKeys"
    :row-class-name="rowClassName"
    :cell-style="cellStyle"
    :default-expand-all="false"
    empty-text="暂无文件夹与文件"
    @row-click="onRowClick"
    @selection-change="onSelectionChange"
    @update:expand-row-keys="(keys: string[]) => emit('update-expand-keys', keys)"
  >
    <el-table-column
      v-if="canEdit"
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
              :aria-label="expandedKeys.includes(row.node_id) ? '折叠' : '展开'"
              @click.stop="onToggleExpand(row)"
            >
              <span class="expand-icon" :class="{ 'is-expanded': expandedKeys.includes(row.node_id) }">▶</span>
            </button>
            <span class="folder-icon">📁</span>
            <span class="folder-name">{{ row.name }}</span>
            <el-tag v-if="row.is_system" size="small" type="warning" effect="plain">默认</el-tag>
            <span class="folder-meta">
              <template v-if="row._hit_count !== undefined">
                {{ row._hit_count }} 个命中
              </template>
              <template v-else>
                {{ row.total_doc_count }} 个文档
                <span v-if="row.direct_doc_count !== row.total_doc_count" class="folder-meta-sub">
                  （直属 {{ row.direct_doc_count }}）
                </span>
              </template>
            </span>
            <span v-if="loadingFolderIds.has(row.folder_id)" class="folder-loading">加载中…</span>
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
        <template v-if="row.node_type === 'folder'"><span class="muted">文件夹</span></template>
        <template v-else>{{ formatBytes(row.file_size) }}</template>
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
        <template v-if="row.node_type === 'file'">{{ row.chunk_count || '-' }}</template>
        <span v-else class="muted">-</span>
      </template>
    </el-table-column>

    <el-table-column label="页数" width="70" align="right">
      <template #default="{ row }: { row: MixedNode }">
        <template v-if="row.node_type === 'file'">{{ row.page_count || '-' }}</template>
        <span v-else class="muted">-</span>
      </template>
    </el-table-column>

    <el-table-column label="更新时间" width="170">
      <template #default="{ row }: { row: MixedNode }">
        <template v-if="row.node_type === 'file'">{{ formatDateTime(row.updated_at) }}</template>
        <span v-else class="muted">-</span>
      </template>
    </el-table-column>

    <el-table-column label="操作" width="320" fixed="right">
      <template #default="{ row }: { row: MixedNode }">
        <template v-if="row.node_type === 'folder'">
          <template v-if="canEdit">
            <el-button link type="primary" size="small" @click.stop="emit('create-sub-folder')">
              +子文件夹
            </el-button>
            <el-button link type="primary" size="small" @click.stop="emit('rename-folder', row)">
              重命名
            </el-button>
            <el-button link type="primary" size="small" @click.stop="emit('move-folder', row)">
              移动到...
            </el-button>
            <el-button
              link
              type="danger"
              size="small"
              :disabled="deletingFolderIds.has(row.folder_id)"
              @click.stop="emit('delete-folder', row)"
            >
              {{ deletingFolderIds.has(row.folder_id) ? '删除中' : '删除' }}
            </el-button>
          </template>
          <span v-else class="readonly-tag">只读</span>
        </template>
        <template v-else>
          <el-button
            v-if="isPreviewable(row.file_ext)"
            link
            type="primary"
            size="small"
            @click.stop="emit('preview', row)"
          >
            预览
          </el-button>
          <el-button
            link
            type="primary"
            size="small"
            :loading="downloadingIds.has(row.doc_id)"
            @click.stop="emit('download', row)"
          >
            下载
          </el-button>
          <template v-if="canEdit">
            <el-button
              v-if="row.status === 'done'"
              link
              type="primary"
              size="small"
              :loading="reprocessingIds.has(row.doc_id)"
              @click.stop="emit('reprocess', row)"
            >
              重新解析
            </el-button>
            <el-button
              v-else-if="row.status === 'failed'"
              link
              type="warning"
              size="small"
              :loading="reprocessingIds.has(row.doc_id)"
              @click.stop="emit('reprocess', row)"
            >
              重试
            </el-button>
            <el-button v-else link type="info" size="small" disabled>处理中</el-button>
            <el-popconfirm
              title="删除后向量、文件与记录一并移除，确认删除？"
              width="220"
              confirm-button-text="删除"
              cancel-button-text="取消"
              @confirm.stop="emit('delete-doc', row)"
            >
              <template #reference>
                <el-button
                  link
                  type="danger"
                  size="small"
                  :loading="deletingIds.has(row.doc_id)"
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
</template>

<style scoped>
.mixed-table {
  flex: 1;
  min-height: 0;
}

.mixed-table :deep(.is-selected-row) {
  background-color: var(--el-color-primary-light-9) !important;
}

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

.folder-loading {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-color-primary);
  animation: kb-loading-blink 1s ease-in-out infinite;
}

@keyframes kb-loading-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

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

.ext-pdf { background: #e74c3c; }
.ext-doc { background: #2c5fa3; }
.ext-xls { background: #1d6f42; }
.ext-ppt { background: #d24726; }
.ext-txt { background: #6c757d; }
.ext-md { background: #8b5cf6; }
.ext-default { background: #94a3b8; }

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

.mixed-table :deep(.el-table__expand-icon) {
  display: none !important;
}

.mixed-table :deep(.el-table__indent) {
  display: none !important;
}

.mixed-table :deep(.el-table__placeholder) {
  display: none !important;
}

.mixed-table :deep(td.el-table__cell:first-child .cell) {
  padding-left: 0 !important;
}

.mixed-table :deep(td.el-table-column--selection) {
  z-index: 2;
}
</style>
