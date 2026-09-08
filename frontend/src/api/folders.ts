// 文件夹管理 API：CRUD + 树构建 + 拖拽 + 上传（文件 / 目录）
import { http } from './http'
import type {
  DirectoryUploadResult,
  DocumentUploadResult,
  Folder,
  FolderCreatePayload,
  FolderMovePayload,
  FolderTreeResult,
  OkResponse,
} from '../types/api'

export async function getTree(kbId: string): Promise<FolderTreeResult> {
  const { data } = await http.get<FolderTreeResult>('/folders', {
    params: { kb_id: kbId },
  })
  return data
}

export async function create(payload: FolderCreatePayload): Promise<Folder> {
  const { data } = await http.post<Folder>('/folders', payload)
  return data
}

export async function rename(folderId: string, name: string): Promise<Folder> {
  const { data } = await http.patch<Folder>(`/folders/${folderId}`, { name })
  return data
}

export async function move(folderId: string, parentId: string | null): Promise<Folder> {
  const { data } = await http.post<Folder>(`/folders/${folderId}/move`, {
    parent_id: parentId,
  } as FolderMovePayload)
  return data
}

export async function remove(folderId: string): Promise<OkResponse> {
  const { data } = await http.delete<OkResponse>(`/folders/${folderId}`)
  return data
}

/** 上传多个文件到指定 folder。同 folder 内同名 → 该文件 rejected。 */
export async function uploadFiles(
  folderId: string,
  files: File[],
): Promise<DocumentUploadResult[]> {
  const form = new FormData()
  for (const f of files) form.append('files', f, f.name)
  const { data } = await http.post<DocumentUploadResult[]>(
    `/folders/${folderId}/upload`,
    form,
    { timeout: 180_000 },
  )
  return data
}

/**
 * 递归目录上传：files + paths（每个文件对应的相对路径）。
 * 前端用 `<input webkitdirectory>` 获取 File.webkitRelativePath。
 */
export async function uploadDirectory(
  folderId: string,
  files: File[],
  paths: string[],
): Promise<DirectoryUploadResult> {
  const form = new FormData()
  for (const f of files) form.append('files', f, f.name)
  form.append('paths', JSON.stringify(paths))
  const { data } = await http.post<DirectoryUploadResult>(
    `/folders/${folderId}/upload-directory`,
    form,
    { timeout: 300_000 }, // 目录上传慢（递归 + 多文件），给 5 分钟
  )
  return data
}