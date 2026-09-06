// 运行日志 API：文件列表 / 倒序分页条目 / 下载
import { http } from './http'
import type { LogEntriesResult, LogFile } from '../types/api'

export async function listFiles(): Promise<LogFile[]> {
  const { data } = await http.get<LogFile[]>('/logs/files')
  return data
}

export async function entries(params: {
  file: string
  level?: string
  search?: string
  end_line?: number
  limit?: number
}): Promise<LogEntriesResult> {
  const { data } = await http.get<LogEntriesResult>('/logs/entries', {
    params: {
      file: params.file,
      level: params.level || undefined,
      search: params.search || undefined,
      end_line: params.end_line ?? undefined,
      limit: params.limit ?? 100,
    },
  })
  return data
}

/** 下载日志文件（浏览器直接导航触发，无需解析响应） */
export function downloadUrl(file: string): string {
  return `/api/logs/download?file=${encodeURIComponent(file)}`
}
