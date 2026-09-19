import { ref, type Ref } from 'vue'
import { notify as ElMessage } from '../services/feedback'
import * as docApi from '../api/documents'
import * as folderApi from '../api/folders'
import type {
  DocumentItem,
  Folder,
  FolderTreeNode,
  MoveDocumentResult,
} from '../types/documents'

interface DocumentActionsContext {
  currentKbId: Ref<string>
  currentFolderId: Ref<string | null>
  currentNodeKey: Ref<string | null>
  expandedKeys: Ref<string[]>
  folderTree: Ref<FolderTreeNode[]>
  folderDocs: Ref<Map<string, DocumentItem[]>>
  searchResults: Ref<DocumentItem[] | null>
  loadFolderTree: (opts?: { silent?: boolean }) => Promise<void>
  loadFolderFiles: (
    folderId: string,
    opts?: { force?: boolean; silent?: boolean },
  ) => Promise<DocumentItem[] | null>
  refreshCounts: () => Promise<void>
  invalidateFolder: (folderId: string | null | undefined) => void
  invalidateFolderSubtree: (folderId: string) => void
  startPolling: () => void
}

/** 文档和文件夹的变更用例，统一处理变更后的缓存刷新。 */
export function useDocumentActions(ctx: DocumentActionsContext) {
  const deletingIds = ref<Set<string>>(new Set())
  const reprocessingIds = ref<Set<string>>(new Set())
  const deletingFolderIds = ref<Set<string>>(new Set())

  async function moveDocs(
    docIds: string[],
    targetFolderId: string,
  ): Promise<MoveDocumentResult[]> {
    const result = await docApi.move(docIds, targetFolderId)
    const moved = result.filter((item) => item.status === 'moved').length
    const rejected = result.filter((item) => item.status === 'rejected')
    if (rejected.length > 0) {
      const sample = rejected
        .slice(0, 3)
        .map((item) => item.error || item.doc_id)
        .join('；')
      ElMessage.warning(
        `已移动 ${moved} 个文件，${rejected.length} 个失败：${sample}${
          rejected.length > 3 ? '…' : ''
        }`,
      )
    } else if (moved > 0) {
      ElMessage.success(`已移动 ${moved} 个文件`)
    }

    const touched = new Set<string>()
    for (const [folderId, docs] of ctx.folderDocs.value) {
      if (docs.some((doc) => docIds.includes(doc.doc_id))) touched.add(folderId)
    }
    touched.add(targetFolderId)
    for (const folderId of touched) {
      ctx.invalidateFolder(folderId)
      await ctx.loadFolderFiles(folderId)
    }
    await ctx.loadFolderTree({ silent: true })
    return result
  }

  async function removeDoc(docId: string) {
    deletingIds.value.add(docId)
    try {
      await docApi.remove(docId)
      if (ctx.searchResults.value !== null) {
        ctx.searchResults.value = ctx.searchResults.value.filter((doc) => doc.doc_id !== docId)
      }

      let affectedFolderId: string | null = null
      for (const [folderId, docs] of ctx.folderDocs.value) {
        if (docs.some((doc) => doc.doc_id === docId)) {
          ctx.folderDocs.value.set(
            folderId,
            docs.filter((doc) => doc.doc_id !== docId),
          )
          affectedFolderId = folderId
          break
        }
      }
      if (affectedFolderId) {
        ctx.invalidateFolder(affectedFolderId)
        await ctx.loadFolderFiles(affectedFolderId)
      }
      if (ctx.currentNodeKey.value === `doc:${docId}`) {
        ctx.currentNodeKey.value = null
        ctx.currentFolderId.value = null
      }
      await ctx.refreshCounts()
      ElMessage.success('已删除')
    } catch (error) {
      ElMessage.error((error as Error).message || '删除失败')
      throw error
    } finally {
      deletingIds.value.delete(docId)
    }
  }

  async function removeDocs(docIds: string[]) {
    const ids = [...new Set(docIds)]
    if (ids.length === 0) return
    for (const id of ids) deletingIds.value.add(id)
    const failed: string[] = []
    try {
      await Promise.all(
        ids.map(async (id) => {
          try {
            await docApi.remove(id)
          } catch {
            failed.push(id)
          }
        }),
      )
      if (ctx.searchResults.value !== null) {
        ctx.searchResults.value = ctx.searchResults.value.filter(
          (doc) => !ids.includes(doc.doc_id),
        )
      }

      const affected = new Set<string>()
      for (const [folderId, docs] of ctx.folderDocs.value) {
        const rest = docs.filter((doc) => !ids.includes(doc.doc_id))
        if (rest.length !== docs.length) {
          ctx.folderDocs.value.set(folderId, rest)
          affected.add(folderId)
        }
      }
      for (const folderId of affected) ctx.invalidateFolder(folderId)
      await Promise.all([...affected].map((folderId) => ctx.loadFolderFiles(folderId)))
      if (ctx.currentNodeKey.value?.startsWith('doc:')) {
        const currentId = ctx.currentNodeKey.value.slice('doc:'.length)
        if (ids.includes(currentId)) {
          ctx.currentNodeKey.value = null
          ctx.currentFolderId.value = null
        }
      }
      await ctx.refreshCounts()
      if (failed.length > 0) {
        ElMessage.error(`删除失败 ${failed.length} 个，其余已删除`)
      } else {
        ElMessage.success(`已删除 ${ids.length} 个文件`)
      }
    } catch (error) {
      ElMessage.error((error as Error).message || '批量删除失败')
      throw error
    } finally {
      for (const id of ids) deletingIds.value.delete(id)
    }
  }

  async function reprocessDocs(docIds: string[]) {
    const ids = [...new Set(docIds)]
    if (ids.length === 0) return
    for (const id of ids) reprocessingIds.value.add(id)
    const failed: string[] = []
    try {
      await Promise.all(
        ids.map(async (id) => {
          try {
            await docApi.reprocess(id)
          } catch {
            failed.push(id)
          }
        }),
      )
      const affected = new Set<string>()
      for (const [folderId, docs] of ctx.folderDocs.value) {
        if (docs.some((doc) => ids.includes(doc.doc_id))) {
          ctx.invalidateFolder(folderId)
          affected.add(folderId)
        }
      }
      await Promise.all([...affected].map((folderId) => ctx.loadFolderFiles(folderId)))
      ctx.startPolling()
      if (failed.length > 0) {
        ElMessage.error(`解析调度失败 ${failed.length} 个，其余已加入队列`)
      } else {
        ElMessage.success(`已调度 ${ids.length} 个文档解析，请稍候`)
      }
    } catch (error) {
      ElMessage.error((error as Error).message || '批量解析调度失败')
      throw error
    } finally {
      for (const id of ids) reprocessingIds.value.delete(id)
    }
  }

  async function reprocessDoc(docId: string) {
    reprocessingIds.value.add(docId)
    try {
      await docApi.reprocess(docId)
      ElMessage.success('已调度解析，请稍候')
      for (const [folderId, docs] of ctx.folderDocs.value) {
        if (docs.some((doc) => doc.doc_id === docId)) {
          ctx.invalidateFolder(folderId)
          await ctx.loadFolderFiles(folderId)
          break
        }
      }
      ctx.startPolling()
    } catch (error) {
      ElMessage.error((error as Error).message || '调度失败')
      throw error
    } finally {
      reprocessingIds.value.delete(docId)
    }
  }

  async function createFolder(parentId: string | null, name: string): Promise<Folder> {
    const folder = await folderApi.create({
      kb_id: ctx.currentKbId.value,
      parent_id: parentId,
      name,
    })
    ElMessage.success(`已创建：${folder.name}`)
    await ctx.loadFolderTree({ silent: true })
    return folder
  }

  async function renameFolder(folderId: string, newName: string): Promise<Folder> {
    const folder = await folderApi.rename(folderId, newName)
    ElMessage.success(`已重命名为：${folder.name}`)
    ctx.invalidateFolderSubtree(folderId)
    await ctx.loadFolderTree({ silent: true })
    return folder
  }

  async function moveFolderToParent(folderId: string, parentId: string | null): Promise<Folder> {
    const folder = await folderApi.move(folderId, parentId)
    ctx.invalidateFolderSubtree(folderId)
    await ctx.loadFolderTree({ silent: true })
    return folder
  }

  async function deleteFolder(folderId: string) {
    deletingFolderIds.value.add(folderId)
    try {
      const result = await folderApi.remove(folderId)
      ElMessage.success(result.detail || '文件夹已删除')
      if (ctx.currentFolderId.value === folderId) ctx.currentFolderId.value = null
      if (ctx.currentNodeKey.value === `folder:${folderId}`) ctx.currentNodeKey.value = null
      const key = `folder:${folderId}`
      ctx.expandedKeys.value = ctx.expandedKeys.value.filter((item) => item !== key)
      ctx.invalidateFolderSubtree(folderId)
      await ctx.refreshCounts()
    } catch (error) {
      ElMessage.error((error as Error).message || '删除失败')
      throw error
    } finally {
      deletingFolderIds.value.delete(folderId)
    }
  }

  return {
    deletingIds,
    reprocessingIds,
    deletingFolderIds,
    moveDocs,
    removeDoc,
    removeDocs,
    reprocessDoc,
    reprocessDocs,
    createFolder,
    renameFolder,
    moveFolderToParent,
    deleteFolder,
  }
}
