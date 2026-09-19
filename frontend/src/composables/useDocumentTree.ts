import type { Ref } from 'vue'
import { notify as ElMessage } from '../services/feedback'
import * as docApi from '../api/documents'
import * as folderApi from '../api/folders'
import type {
  DocStatus,
  DocumentItem,
  FolderTreeNode,
} from '../types/documents'

const FULL_PAGE_SIZE = 5_000

interface DocumentTreeContext {
  currentKbId: Ref<string>
  folderTree: Ref<FolderTreeNode[]>
  folderDocs: Ref<Map<string, DocumentItem[]>>
  folderLoaded: Ref<Set<string>>
  loadingFolderIds: Ref<Set<string>>
  searchResults: Ref<DocumentItem[] | null>
  statusFilter: Ref<DocStatus | ''>
  search: Ref<string>
  loading: Ref<boolean>
}

/** 文件夹树、文档懒加载、搜索结果和缓存失效边界。 */
export function useDocumentTree(ctx: DocumentTreeContext) {
  async function loadFolderTree(opts?: { silent?: boolean }) {
    if (!opts?.silent) ctx.loading.value = true
    try {
      const result = await folderApi.getTree(ctx.currentKbId.value)
      ctx.folderTree.value = result.items
    } catch (error) {
      ElMessage.error((error as Error).message || '文件夹树加载失败')
    } finally {
      if (!opts?.silent) ctx.loading.value = false
    }
  }

  async function loadFolderFiles(
    folderId: string,
    opts?: { force?: boolean; silent?: boolean },
  ): Promise<DocumentItem[] | null> {
    if (!folderId) return null
    if (!opts?.force && ctx.folderLoaded.value.has(folderId)) {
      return ctx.folderDocs.value.get(folderId) ?? []
    }
    ctx.loadingFolderIds.value.add(folderId)
    try {
      const result = await docApi.list({
        kb_id: ctx.currentKbId.value,
        folder_id: folderId,
        status: '',
        search: '',
        page: 1,
        page_size: FULL_PAGE_SIZE,
      })
      ctx.folderDocs.value.set(folderId, result.items)
      ctx.folderLoaded.value.add(folderId)
      return result.items
    } catch (error) {
      ElMessage.error((error as Error).message || '文件夹文件加载失败')
      return null
    } finally {
      ctx.loadingFolderIds.value.delete(folderId)
    }
  }

  function collectAllFolderIds(nodes: FolderTreeNode[]): string[] {
    return nodes.flatMap((node) => [node.folder_id, ...collectAllFolderIds(node.children ?? [])])
  }

  async function loadAllDocs(opts?: { silent?: boolean }) {
    for (const folderId of collectAllFolderIds(ctx.folderTree.value)) {
      await loadFolderFiles(folderId, { force: true, silent: opts?.silent })
    }
  }

  async function loadSearchResults() {
    if (!ctx.search.value && !ctx.statusFilter.value) {
      ctx.searchResults.value = null
      return
    }
    try {
      const result = await docApi.list({
        kb_id: ctx.currentKbId.value,
        folder_id: null,
        status: ctx.statusFilter.value,
        search: ctx.search.value,
        page: 1,
        page_size: FULL_PAGE_SIZE,
      })
      ctx.searchResults.value = result.items
    } catch (error) {
      ElMessage.error((error as Error).message || '搜索失败')
    }
  }

  function invalidateFolder(folderId: string | null | undefined) {
    if (!folderId) return
    ctx.folderDocs.value.delete(folderId)
    ctx.folderLoaded.value.delete(folderId)
  }

  function collectSubtreeFolderIds(roots: FolderTreeNode[], folderId: string): string[] {
    for (const node of roots) {
      if (node.folder_id === folderId) {
        return [
          node.folder_id,
          ...(node.children ?? []).flatMap((child) =>
            collectSubtreeFolderIds([child], child.folder_id),
          ),
        ]
      }
      const nested = collectSubtreeFolderIds(node.children ?? [], folderId)
      if (nested.length > 0) return nested
    }
    return []
  }

  function invalidateFolderSubtree(folderId: string) {
    for (const id of collectSubtreeFolderIds(ctx.folderTree.value, folderId)) {
      invalidateFolder(id)
    }
  }

  function invalidateAllFolders() {
    ctx.folderDocs.value = new Map()
    ctx.folderLoaded.value = new Set()
    ctx.searchResults.value = null
  }

  return {
    loadFolderTree,
    loadFolderFiles,
    loadAllDocs,
    loadSearchResults,
    invalidateFolder,
    invalidateFolderSubtree,
    invalidateAllFolders,
  }
}
