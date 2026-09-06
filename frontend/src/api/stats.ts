// 数据统计 API：问答统计聚合（单接口一次返回全部）
import { http } from './http'
import type { StatsSummary } from '../types/api'

export async function summary(params: {
  days?: number | null
  mode?: string
}): Promise<StatsSummary> {
  const { data } = await http.get<StatsSummary>('/stats/summary', {
    params: {
      days: params.days ?? undefined,
      mode: params.mode ?? 'kb',
    },
  })
  return data
}
