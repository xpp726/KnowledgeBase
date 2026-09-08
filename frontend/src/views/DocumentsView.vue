<script setup lang="ts">
// 文档管理页（阶段 3）：
// kb 维度 UI（顶部切换 + 新建）→ 工具栏（搜索/状态筛选/上传）→ 列表（分页）→ 轮询进度
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile, UploadInstance, UploadUserFile } from 'element-plus'
import { useDocumentStore } from '../stores/document'
import { useAuthStore } from '../stores/auth'
import type { DocStatus, DocumentItem } from '../types/api'

const store = useDocumentStore()
const auth = useAuthStore()

// ==================== 上传 ====================
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
  // 同名文件重复上传：弹确认（后端同名覆盖，重新解析）
  const existingNames = new Set(store.documents.map((d) => d.file_name))
  const dupNames = files.map((f) => f.name).filter((n) => existingNames.has(n))
  if (dupNames.length > 0) {
    try {
      await ElMessageBox.confirm(
        `检测到同名文件：${dupNames.join('、')}。同名文件将重新解析，是否继续？`,
        '重复文件确认',
        { confirmButtonText: '继续上传', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return // 用户取消
    }
  }
  try {
    await store.uploadFiles(files)
    clearFiles()
  } catch {
    // store 已提示错误
  }
}

// ==================== 新建知识库 ====================
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

// ==================== 搜索（本地输入，回车/失焦/清空时才触发请求） ====================
const searchInput = ref('')

function applySearch() {
  store.setSearch(searchInput.value.trim())
}

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

async function handleDelete(doc: DocumentItem) {
  try {
    await store.removeDoc(doc.doc_id)
  } catch {
    // store 已提示
  }
}

async function handleReprocess(doc: DocumentItem) {
  try {
    await store.reprocessDoc(doc.doc_id)
  } catch {
    // store 已提示
  }
}

// ==================== 生命周期 ====================

onMounted(() => {
  void store.loadKbs()
  void store.reload()
})

onUnmounted(() => {
  store.stopPoll()
})
</script>

<template>
  <div class="documents-view">
    <!-- 顶部：知识库维度 -->
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
      <el-button v-if="auth.canEditDocuments()" class="kb-create" @click="kbDialogVisible = true">新建知识库</el-button>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-input
        v-model="searchInput"
        class="search-input"
        placeholder="按文件名搜索"
        clearable
        @clear="applySearch"
        @keyup.enter="applySearch"
        @change="applySearch"
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
      <template v-if="auth.canEditDocuments()">
        <el-upload
          ref="uploadRef"
          class="upload-btn"
          :auto-upload="false"
          :show-file-list="false"
          multiple
          accept=".pdf,.docx,.xlsx,.xlsm,.txt,.md,.markdown"
          :on-change="onFileChange"
        >
          <el-button type="primary" :loading="store.uploading">选择文件</el-button>
        </el-upload>
        <el-button
          type="primary"
          plain
          :disabled="pendingFiles.length === 0"
          :loading="store.uploading"
          @click="handleUpload"
        >
          上传（{{ pendingFiles.length }}）
        </el-button>
      </template>
    </div>

    <!-- 列表 -->
    <el-table v-loading="store.loading" :data="store.documents" class="doc-table">
      <el-table-column prop="file_name" label="文件名" min-width="260" show-overflow-tooltip>
        <template #default="{ row }: { row: DocumentItem }">
          <span class="file-name">{{ row.file_name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="100">
        <template #default="{ row }: { row: DocumentItem }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }: { row: DocumentItem }">
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
      </el-table-column>
      <el-table-column label="分块数" width="90" align="right">
        <template #default="{ row }: { row: DocumentItem }">
          {{ row.chunk_count || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="页数" width="80" align="right">
        <template #default="{ row }: { row: DocumentItem }">
          {{ row.page_count || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }: { row: DocumentItem }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }: { row: DocumentItem }">
          <template v-if="auth.canEditDocuments()">
            <el-button
              v-if="row.status === 'done'"
              link
              type="primary"
              :loading="store.reprocessingIds.has(row.doc_id)"
              @click="handleReprocess(row)"
            >
              重新解析
            </el-button>
            <el-button
              v-else-if="row.status === 'failed'"
              link
              type="warning"
              :loading="store.reprocessingIds.has(row.doc_id)"
              @click="handleReprocess(row)"
            >
              重试
            </el-button>
            <el-button v-else link type="info" disabled>处理中</el-button>
            <el-popconfirm
              title="删除后向量、文件与记录一并移除，确认删除？"
              width="220"
              confirm-button-text="删除"
              cancel-button-text="取消"
              @confirm="handleDelete(row)"
            >
              <template #reference>
                <el-button
                  link
                  type="danger"
                  :loading="store.deletingIds.has(row.doc_id)"
                >
                  删除
                </el-button>
              </template>
            </el-popconfirm>
          </template>
          <span v-else class="readonly-tag">只读</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 空态 -->
    <el-empty
      v-if="!store.loading && store.documents.length === 0"
      description="暂无文档，点击右上角选择文件上传"
    />

    <!-- 分页 -->
    <div class="pager">
      <el-pagination
        background
        layout="total, prev, pager, next, sizes"
        :total="store.total"
        :current-page="store.page"
        :page-size="store.pageSize"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="(p: number) => store.setPage(p)"
        @size-change="(s: number) => { store.pageSize = s; store.setPage(1) }"
      />
    </div>

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
  </div>
</template>

<style scoped>
.readonly-tag {
  font-size: 12px;
  color: var(--text-secondary, #9ca3af);
}

.documents-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 16px 20px;
  gap: 12px;
  box-sizing: border-box;
}

.kb-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.kb-select {
  width: 260px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.search-input {
  width: 280px;
}

.status-select {
  width: 140px;
}

.upload-btn {
  margin-left: auto;
}

.doc-table {
  flex: 1;
  min-height: 0;
}

.file-name {
  font-weight: 500;
}

.pager {
  display: flex;
  justify-content: flex-end;
}
</style>
