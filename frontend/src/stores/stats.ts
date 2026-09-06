// 数据统计 store：时间范围 / 口径筛选 + 单接口聚合数据 + 手动刷新
//
// 与日志页不同，统计页无实时性需求：进入加载 + 手动刷新，不设自动轮询。
// 默认口径 = kb（知识库问答），通用问答可手动切换查看。

import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import type { StatsSummary } from '../types/api'
import * as statsApi from '../api/stats'

export const useStatsStore = defineStore('stats', () => {
  // ==================== state ====================
  const days = ref<number | null>(30) // null=全部
  const mode = ref('kb') // kb / general / all
  const summary = ref<StatsSummary | null>(null)
  const loading = ref(false)

  // ==================== actions ====================

  async function reload() {
    loading.value = true
    try {
      summary.value = await statsApi.summary({ days: days.value, mode: mode.value })
    } catch (e) {
      ElMessage.error((e as Error).message || '统计数据加载失败')
    } finally {
      loading.value = false
    }
  }

  function setDays(value: number | null) {
    if (value === days.value) return
    days.value = value
    void reload()
  }

  function setMode(value: string) {
    if (value === mode.value) return
    mode.value = value
    void reload()
  }

  return {
    days,
    mode,
    summary,
    loading,
    reload,
    setDays,
    setMode,
  }
})
