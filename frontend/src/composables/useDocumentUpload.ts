import { ref, type Ref } from 'vue'
import { notify as ElMessage } from '../services/feedback'
import * as docApi from '../api/documents'
import * as folderApi from '../api/folders'
import type {
  DocStatus,
  DocumentItem,
  DocumentUploadResult,
  FolderTreeNode,
} from '../types/documents'

const POLL_INTERVAL_MS = 3_000
const UPLOAD_CONCURRENCY = 3
const IN_PROGRESS: DocStatus[] = ['pending', 'ingesting', 'embedding']

interface DocumentUploadContext {
  currentKbId: Ref<string>
  currentFolderId: Ref<string | null>
  folderTree: Ref<FolderTreeNode[]>
  expandedKeys: Ref<string[]>
  searchResults: Ref<DocumentItem[] | null>
  allDocs: () => DocumentItem[]
  loadFolderFiles: (
    folderId: string,
    opts?: { force?: boolean; silent?: boolean },
  ) => Promise<DocumentItem[] | null>
  loadSearchResults: () => Promise<void>
  refreshCounts: () => Promise<void>
  invalidateFolder: (folderId: string | null | undefined) => void
}

/**
 * 文档登记后的上传反馈和异步状态轮询。
 *
 * 树、缓存和知识库选择仍由 document store 管理；这里仅通过回调触发刷新，
 * 避免 composable 复制缓存失效规则。
 */
export function useDocumentUpload(ctx: DocumentUploadContext) {
  const uploading = ref(false)
  const pollTimer = ref<ReturnType<typeof setInterval> | null>(null)

  function hasAnyInProgress(): boolean {
    return ctx.allDocs().some((doc) => IN_PROGRESS.includes(doc.status))
  }

  function resolveTargetFolderId(folderId: string | null): string | null {
    if (folderId) return folderId
    const defaultFolder = ctx.folderTree.value.find((folder) => folder.is_system)
    return defaultFolder?.folder_id ?? ctx.folderTree.value[0]?.folder_id ?? null
  }

  async function pollOnce() {
    try {
      const summary = await docApi.summary(ctx.currentKbId.value)
      const done = summary.in_progress === 0
      try {
        await ctx.refreshCounts()
        for (const key of ctx.expandedKeys.value) {
          if (key.startsWith('folder:')) {
            await ctx.loadFolderFiles(key.slice('folder:'.length), {
              force: true,
              silent: true,
            })
          }
        }
        if (ctx.searchResults.value !== null) await ctx.loadSearchResults()
      } catch {
        // 刷新失败不中断轮询，下一轮继续重试。
      }
      if (done) stopPolling()
    } catch {
      // summary 单次失败不中断轮询。
    }
  }

  function schedulePoll() {
    stopPolling()
    pollTimer.value = setInterval(() => void pollOnce(), POLL_INTERVAL_MS)
  }

  function startPolling() {
    if (!pollTimer.value) schedulePoll()
  }

  function stopPolling() {
    if (pollTimer.value) {
      clearInterval(pollTimer.value)
      pollTimer.value = null
    }
  }

  function summarizeUploadResults(results: DocumentUploadResult[]) {
    const rejected = results.filter((result) => result.status === 'rejected')
    const okCount = results.length - rejected.length
    if (rejected.length > 0) {
      ElMessage.warning(
        `已登记 ${okCount} 个文件，${rejected.length} 个失败：${rejected
          .map((result) => result.error || result.file_name)
          .join('；')}`,
      )
    } else if (okCount > 0) {
      ElMessage.success(`已提交 ${okCount} 个文件，解析进行中`)
    }
  }

  async function refreshAfterUpload(targetFolderId: string) {
    ctx.invalidateFolder(targetFolderId)
    await ctx.loadFolderFiles(targetFolderId)
    await ctx.refreshCounts()
    startPolling()
  }

  async function uploadFiles(files: File[]): Promise<DocumentUploadResult[]> {
    uploading.value = true
    const targetFolderId = resolveTargetFolderId(ctx.currentFolderId.value)
    if (!targetFolderId) {
      ElMessage.warning('当前 kb 没有可用文件夹，请先创建一个')
      uploading.value = false
      return []
    }
    const results: DocumentUploadResult[] = []
    try {
      for (let i = 0; i < files.length; i += UPLOAD_CONCURRENCY) {
        const batch = files.slice(i, i + UPLOAD_CONCURRENCY)
        results.push(...(await folderApi.uploadFiles(targetFolderId, batch)))
      }
      summarizeUploadResults(results)
      await refreshAfterUpload(targetFolderId)
      return results
    } catch (error) {
      ElMessage.error((error as Error).message || '上传失败')
      throw error
    } finally {
      uploading.value = false
    }
  }

  async function uploadDirectory(
    files: File[],
    paths: string[],
  ): Promise<DocumentUploadResult[]> {
    uploading.value = true
    const targetFolderId = resolveTargetFolderId(ctx.currentFolderId.value)
    if (!targetFolderId) {
      ElMessage.warning('当前 kb 没有可用文件夹，请先创建一个')
      uploading.value = false
      return []
    }
    try {
      const result = await folderApi.uploadDirectory(targetFolderId, files, paths)
      ElMessage.success(
        `目录上传完成：${result.summary.uploaded_count} 个成功，${result.summary.rejected_count} 个失败`,
      )
      if (result.rejected.length > 0) {
        const sample = result.rejected
          .slice(0, 3)
          .map((item) => `${item.file_name}：${item.error}`)
          .join('；')
        ElMessage.warning(
          `失败明细（前 3 条）：${sample}${result.rejected.length > 3 ? '…' : ''}`,
        )
      }
      await refreshAfterUpload(targetFolderId)
      return result.uploaded
    } catch (error) {
      ElMessage.error((error as Error).message || '目录上传失败')
      throw error
    } finally {
      uploading.value = false
    }
  }

  return {
    uploading,
    hasAnyInProgress,
    pollOnce,
    startPolling,
    stopPolling,
    uploadFiles,
    uploadDirectory,
  }
}
