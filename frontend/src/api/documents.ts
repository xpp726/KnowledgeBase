// 文档管理 API：分页列表 / 多文件上传（登记即返回，解析异步）/ 删除 / 重试重解析
import { http } from './http'
import type {
  DocumentItem,
  DocumentListQuery,
  DocumentListResult,
  DocumentSummary,
  DocumentUploadResult,
  MoveDocumentResult,
  MoveDocumentsPayload,
  OkResponse,
} from '../types/api'

export async function list(params: DocumentListQuery): Promise<DocumentListResult> {
  const { data } = await http.get<DocumentListResult>('/documents', {
    params: {
      kb_id: params.kb_id || undefined,
      folder_id: params.folder_id ?? undefined,
      status: params.status || undefined,
      search: params.search || undefined,
      page: params.page ?? 1,
      page_size: params.page_size ?? 20,
    },
  })
  return data
}

/** 文档状态计数（轻量）：轮询时判断是否存在非终态文档，避免拉全量。 */
export async function summary(kbId?: string): Promise<DocumentSummary> {
  const { data } = await http.get<DocumentSummary>('/documents/summary', {
    params: { kb_id: kbId || undefined },
  })
  return data
}

export async function get(docId: string): Promise<DocumentItem | null> {
  const { data } = await http.get<DocumentListResult>('/documents', {
    params: { search: docId, page_size: 1 },
  })
  return data.items[0] ?? null
}

/**
 * 上传到默认 folder（kb 的"默认文件夹"），无 folder_id 透传。
 * @param files 文件列表
 * @param kbId 可选知识库 id
 */
export async function upload(files: File[], kbId?: string): Promise<DocumentUploadResult[]> {
  const form = new FormData()
  for (const f of files) form.append('files', f, f.name)
  if (kbId) form.append('kb_id', kbId)
  const { data } = await http.post<DocumentUploadResult[]>('/documents', form, {
    timeout: 180_000, // 大文件上传放宽；登记后立即返回，解析不阻塞请求
  })
  return data
}

export async function remove(docId: string): Promise<OkResponse> {
  const { data } = await http.delete<OkResponse>(`/documents/${docId}`)
  return data
}

/** 重试（failed）或重新解析（done）：后端调度异步执行，前端轮询状态 */
export async function reprocess(docId: string): Promise<{ doc_id: string; status: string }> {
  const { data } = await http.post<{ doc_id: string; status: string }>(
    `/documents/${docId}/reprocess`,
  )
  return data
}

/** 批量移动文档到目标文件夹（同 kb、同名拒绝、逐文件错误隔离）。 */
export async function move(
  docIds: string[],
  targetFolderId: string,
): Promise<MoveDocumentResult[]> {
  const { data } = await http.post<MoveDocumentResult[]>('/documents/move', {
    doc_ids: docIds,
    target_folder_id: targetFolderId,
  } as MoveDocumentsPayload)
  return data
}

/** 内嵌预览：返回原始文件 Blob（PDF/图片/TXT），带登录 token。 */
export async function previewBlob(docId: string): Promise<Blob> {
  const { data } = await http.get<Blob>(`/documents/${docId}/preview`, {
    responseType: 'blob',
  })
  return data
}

/** 下载原始文件：返回 Blob（文件名由后端 Content-Disposition 提供，前端用原始文件名落盘）。 */
export async function downloadBlob(docId: string): Promise<Blob> {
  const { data } = await http.get<Blob>(`/documents/${docId}/download`, {
    responseType: 'blob',
  })
  return data
}
