import { notify as ElMessage, promptDialog } from '../services/feedback'
import type { Folder, MixedFolderNode } from '../types/documents'

interface DocumentFolderDialogContext {
  currentFolderId: () => string | null
  expandedKeys: string[]
  getFolderName: (folderId: string) => string | undefined
  createFolder: (parentId: string | null, name: string) => Promise<Folder>
  renameFolder: (folderId: string, name: string) => Promise<Folder>
  confirmDeleteFolder: (folderId: string) => Promise<void>
  expandAll: () => void
}

/** 页面级文件夹交互：确认框属于 UI，实际变更仍委托给文档 Store。 */
export function useDocumentFolderDialogs(ctx: DocumentFolderDialogContext) {
  async function handleCreateTopFolder() {
    let name = ''
    try {
      const result = await promptDialog(
        '输入新文件夹名（kb 顶级）',
        '新建文件夹',
        { inputPlaceholder: '例如：研发资料', confirmButtonText: '创建', cancelButtonText: '取消' },
      )
      name = result.value
    } catch {
      return
    }
    try {
      await ctx.createFolder(null, name.trim())
      ctx.expandAll()
    } catch {
      // Store 已提示错误。
    }
  }

  async function handleCreateSubFolder() {
    const parentId = ctx.currentFolderId()
    if (!parentId) {
      ElMessage.warning('请先选中一个文件夹，再新建子文件夹')
      return
    }
    let name = ''
    try {
      const result = await promptDialog(
        `在「${ctx.getFolderName(parentId) ?? '当前文件夹'}」下新建子文件夹`,
        '新建子文件夹',
        { inputPlaceholder: '例如：合同', confirmButtonText: '创建', cancelButtonText: '取消' },
      )
      name = result.value
    } catch {
      return
    }
    try {
      const newFolder = await ctx.createFolder(parentId, name.trim())
      const parentKey = `folder:${parentId}`
      if (!ctx.expandedKeys.includes(parentKey)) ctx.expandedKeys.push(parentKey)
      ctx.expandedKeys.push(`folder:${newFolder.folder_id}`)
    } catch {
      // Store 已提示错误。
    }
  }

  async function handleRenameFolder(node: MixedFolderNode) {
    let newName = ''
    try {
      const result = await promptDialog(
        `新名称（${node.is_system ? '默认文件夹可改名' : '重命名'}）`,
        '重命名文件夹',
        { inputValue: node.name, confirmButtonText: '确认', cancelButtonText: '取消' },
      )
      newName = result.value
    } catch {
      return
    }
    try {
      await ctx.renameFolder(node.folder_id, newName.trim())
    } catch {
      // Store 已提示错误。
    }
  }

  async function handleDeleteFolder(node: MixedFolderNode) {
    await ctx.confirmDeleteFolder(node.folder_id)
  }

  return {
    handleCreateTopFolder,
    handleCreateSubFolder,
    handleRenameFolder,
    handleDeleteFolder,
  }
}
