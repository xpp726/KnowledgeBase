import { ref } from 'vue'
import { confirmDialog, notify as ElMessage } from '../services/feedback'
import type { MixedFileNode } from '../types/documents'

interface DocumentBatchActionContext {
  getSelectedFiles: () => MixedFileNode[]
  removeDocs: (docIds: string[]) => Promise<void>
  reprocessDocs: (docIds: string[]) => Promise<void>
  clearSelection: () => void
}

/** 文档批量操作的确认、loading 和选中态收尾。 */
export function useDocumentBatchActions(ctx: DocumentBatchActionContext) {
  const batchDeleting = ref(false)
  const batchReprocessing = ref(false)

  async function handleBatchDelete() {
    const ids = ctx.getSelectedFiles().map((file) => file.doc_id)
    if (ids.length === 0) return
    batchDeleting.value = true
    try {
      await ctx.removeDocs(ids)
      ctx.clearSelection()
    } catch {
      // Store 已提示错误。
    } finally {
      batchDeleting.value = false
    }
  }

  async function handleBatchReprocess() {
    const rows = ctx.getSelectedFiles()
    if (rows.length === 0) return
    const actionable = rows.filter((file) => file.status === 'done' || file.status === 'failed')
    if (actionable.length === 0) {
      ElMessage.info('选中的文档均已完成或正在处理，无需重新解析')
      return
    }
    const skipped = rows.length - actionable.length
    const tip = skipped > 0
      ? `将重新解析 ${actionable.length} 个文档（另有 ${skipped} 个正在处理，将跳过）？解析为异步执行。`
      : `将重新解析选中的 ${actionable.length} 个文档？解析为异步执行。`
    try {
      await confirmDialog(tip, '批量解析', {
        confirmButtonText: '确认解析',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
    batchReprocessing.value = true
    try {
      await ctx.reprocessDocs(actionable.map((file) => file.doc_id))
    } catch {
      // Store 已提示错误。
    } finally {
      batchReprocessing.value = false
    }
  }

  return {
    batchDeleting,
    batchReprocessing,
    handleBatchDelete,
    handleBatchReprocess,
  }
}
