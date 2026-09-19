import { ref } from 'vue'
import { notify as ElMessage } from '../services/feedback'
import { downloadBlob } from '../api/documents'
import type { MixedFileNode } from '../types/documents'

/** 文档预览选择与下载状态，供树表格和预览弹窗之间复用。 */
export function useDocumentFileActions() {
  const previewVisible = ref(false)
  const previewDoc = ref<MixedFileNode | null>(null)
  const downloadingIds = ref<Set<string>>(new Set())

  function handlePreview(row: MixedFileNode) {
    previewDoc.value = row
    previewVisible.value = true
  }

  async function handleDownload(row: MixedFileNode) {
    if (downloadingIds.value.has(row.doc_id)) return
    downloadingIds.value.add(row.doc_id)
    try {
      const blob = await downloadBlob(row.doc_id)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = row.file_name
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      ElMessage.error('下载失败')
    } finally {
      downloadingIds.value.delete(row.doc_id)
    }
  }

  return {
    previewVisible,
    previewDoc,
    downloadingIds,
    handlePreview,
    handleDownload,
  }
}
