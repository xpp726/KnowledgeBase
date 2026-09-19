// 文档、知识库、文件夹及前端混合树类型。

export type DocStatus = 'pending' | 'ingesting' | 'embedding' | 'done' | 'failed'

export interface KnowledgeBase {
  kb_id: string
  name: string
  description: string
  doc_count: number
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseCreate {
  name: string
  description?: string
}

export interface DocumentItem {
  doc_id: string
  kb_id: string
  folder_id: string | null
  folder_path: string
  file_name: string
  file_ext: string
  file_size: number
  page_count: number
  chunk_count: number
  table_chunks: number
  status: DocStatus
  error: string
  created_at: string
  updated_at: string
}

export interface DocumentListResult {
  items: DocumentItem[]
  total: number
  page: number
  page_size: number
}

export interface DocumentSummary {
  total: number
  pending: number
  ingesting: number
  embedding: number
  done: number
  failed: number
  in_progress: number
}

export interface DocumentUploadResult {
  doc_id: string
  file_name: string
  folder_id: string | null
  status: DocStatus | 'rejected'
  duplicated: boolean
  error?: string
  path?: string
}

export interface DocumentListQuery {
  kb_id?: string
  folder_id?: string | null
  status?: DocStatus | ''
  search?: string
  page?: number
  page_size?: number
}

export interface MoveDocumentsPayload {
  doc_ids: string[]
  target_folder_id: string
}

export interface MoveDocumentResult {
  doc_id: string
  status: 'moved' | 'rejected'
  error?: string
}

export interface Folder {
  folder_id: string
  kb_id: string
  parent_id: string | null
  name: string
  depth: number
  is_system: boolean
  created_at: string
  updated_at: string
}

export interface FolderTreeNode extends Folder {
  children: FolderTreeNode[]
  doc_count: number
}

export function totalDocCount(node: FolderTreeNode): number {
  return node.doc_count + node.children.reduce((sum, child) => sum + totalDocCount(child), 0)
}

export interface FolderTreeResult {
  items: FolderTreeNode[]
}

export interface FolderCreatePayload {
  kb_id: string
  parent_id: string | null
  name: string
}

export interface FolderMovePayload {
  parent_id: string | null
}

export interface DirectoryUploadResult {
  uploaded: DocumentUploadResult[]
  rejected: Array<{
    file_name: string
    path?: string
    folder_id?: string
    status: 'rejected'
    error: string
  }>
  summary: {
    uploaded_count: number
    rejected_count: number
    created_folder_ids: string[]
  }
}

// 前端合并 folder + file 后用于 el-table 的树节点，不属于后端契约。
export interface MixedFolderNode {
  node_type: 'folder'
  node_id: string
  folder_id: string
  parent_id: string | null
  name: string
  depth: number
  is_system: boolean
  direct_doc_count: number
  total_doc_count: number
  _hit_count?: number
  created_at: string
  updated_at: string
  children: MixedNode[]
}

export interface MixedFileNode {
  node_type: 'file'
  node_id: string
  doc_id: string
  folder_id: string
  folder_path: string
  file_name: string
  file_ext: string
  file_size: number
  page_count: number
  chunk_count: number
  status: DocStatus
  error: string
  _depth: number
  _show_path: boolean
  created_at: string
  updated_at: string
}

export type MixedNode = MixedFolderNode | MixedFileNode

export function isFolderNode(node: MixedNode): node is MixedFolderNode {
  return node.node_type === 'folder'
}

export function isFileNode(node: MixedNode): node is MixedFileNode {
  return node.node_type === 'file'
}

export function mixedTotalDocCount(node: MixedFolderNode): number {
  return (
    node.direct_doc_count +
    node.children
      .filter((child): child is MixedFolderNode => child.node_type === 'folder')
      .reduce((sum, child) => sum + mixedTotalDocCount(child), 0)
  )
}
