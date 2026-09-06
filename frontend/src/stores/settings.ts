// 系统设置 store：系统信息 / 参数白名单 / 连通性诊断 / 保存并自动重启
//
// 保存链路：确认框 → PUT /config/params（写 .env）→ 后端延迟 1.5s spawn 新进程并退出自身
// → 前端轮询 /config/system，直到新进程接管（uptime 重置）→ 重新拉取参数确认新值生效。

import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import type {
  ConfigDiagnostics,
  ConfigEditableParam,
  ConfigInfraParam,
  ConfigSystemInfo,
} from '../types/api'
import * as configApi from '../api/config'

const POLL_INTERVAL_MS = 1000
const POLL_MAX = 30 // 最多等 30s（新进程 wait_port 默认 120s，取 30s 足够覆盖重启窗口）

export const useSettingsStore = defineStore('settings', () => {
  // ==================== state ====================
  const systemInfo = ref<ConfigSystemInfo | null>(null)
  const editable = ref<ConfigEditableParam[]>([])
  const infra = ref<ConfigInfraParam[]>([])
  const diagnostics = ref<ConfigDiagnostics | null>(null)

  const loadingSystem = ref(false)
  const loadingParams = ref(false)
  const saving = ref(false)
  const diagnosticsLoading = ref(false)

  // ==================== actions ====================

  async function loadSystem() {
    loadingSystem.value = true
    try {
      systemInfo.value = await configApi.systemInfo()
    } catch (e) {
      ElMessage.error((e as Error).message || '系统信息加载失败')
    } finally {
      loadingSystem.value = false
    }
  }

  async function loadParams() {
    loadingParams.value = true
    try {
      const snapshot = await configApi.params()
      editable.value = snapshot.editable
      infra.value = snapshot.infra
    } catch (e) {
      ElMessage.error((e as Error).message || '参数加载失败')
    } finally {
      loadingParams.value = false
    }
  }

  async function loadAll() {
    await Promise.all([loadSystem(), loadParams()])
  }

  async function runDiagnostics() {
    diagnosticsLoading.value = true
    diagnostics.value = null
    try {
      diagnostics.value = await configApi.diagnostics()
    } catch (e) {
      ElMessage.error((e as Error).message || '诊断失败')
    } finally {
      diagnosticsLoading.value = false
    }
  }

  /** 等待新进程接管：uptime 重置为很小的值即视为重启完成。 */
  async function waitForRestart(): Promise<boolean> {
    for (let i = 0; i < POLL_MAX; i++) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
      try {
        const info = await configApi.systemInfo()
        if (info.uptime_seconds < 15) {
          systemInfo.value = info
          return true
        }
      } catch {
        // 重启窗口内请求可能短暂失败，继续轮询
      }
    }
    return false
  }

  async function save(payload: Record<string, unknown>): Promise<boolean> {
    try {
      await ElMessageBox.confirm(
        '保存后服务将自动重启，正在进行的问答请求可能被中断。确定保存？',
        '保存参数',
        { confirmButtonText: '保存并重启', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return false // 用户取消
    }

    saving.value = true
    try {
      const result = await configApi.saveParams(payload)
      if (result.needs_restart) {
        ElMessage.warning('参数已保存，但自动重启未触发，请手动重启服务生效')
        await loadAll()
        return true
      }
      ElMessage.success('参数已保存，服务自动重启中…')
      const restarted = await waitForRestart()
      if (restarted) {
        ElMessage.success('服务已重启，新参数已生效')
      } else {
        ElMessage.warning('未确认到新进程接管，请刷新页面后核对参数是否生效')
      }
      await loadAll()
      return restarted
    } catch (e) {
      ElMessage.error((e as Error).message || '保存失败')
      return false
    } finally {
      saving.value = false
    }
  }

  return {
    systemInfo,
    editable,
    infra,
    diagnostics,
    loadingSystem,
    loadingParams,
    saving,
    diagnosticsLoading,
    loadAll,
    loadSystem,
    loadParams,
    runDiagnostics,
    save,
  }
})
