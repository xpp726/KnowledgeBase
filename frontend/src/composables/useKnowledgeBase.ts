import { ref, type Ref } from 'vue'
import { notify as ElMessage } from '../services/feedback'
import * as kbApi from '../api/kb'
import type { KnowledgeBase } from '../types/documents'

interface KnowledgeBaseContext {
  kbs: Ref<KnowledgeBase[]>
  currentKbId: Ref<string>
  currentFolderId: Ref<string | null>
  currentNodeKey: Ref<string | null>
  expandedKeys: Ref<string[]>
  invalidateAllFolders: () => void
  loadFolderTree: () => Promise<void>
}

/** 知识库列表、创建和当前知识库切换。 */
export function useKnowledgeBase(ctx: KnowledgeBaseContext) {
  const loading = ref(false)

  async function loadKbs() {
    loading.value = true
    try {
      ctx.kbs.value = await kbApi.list()
      if (!ctx.kbs.value.some((kb) => kb.kb_id === ctx.currentKbId.value)) {
        ctx.currentKbId.value = ctx.kbs.value[0]?.kb_id ?? 'default'
      }
    } catch (error) {
      ElMessage.error((error as Error).message || '知识库列表加载失败')
    } finally {
      loading.value = false
    }
  }

  async function createKb(name: string, description = '') {
    const kb = await kbApi.create({ name, description })
    await loadKbs()
    ctx.currentKbId.value = kb.kb_id
    ctx.currentFolderId.value = null
    ctx.currentNodeKey.value = null
    ctx.expandedKeys.value = []
    ctx.invalidateAllFolders()
    await ctx.loadFolderTree()
    return kb
  }

  async function setCurrentKb(kbId: string) {
    if (kbId === ctx.currentKbId.value) return
    ctx.currentKbId.value = kbId
    ctx.currentFolderId.value = null
    ctx.currentNodeKey.value = null
    ctx.expandedKeys.value = []
    ctx.invalidateAllFolders()
    await ctx.loadFolderTree()
  }

  return {
    loading,
    loadKbs,
    createKb,
    setCurrentKb,
  }
}
