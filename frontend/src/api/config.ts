// 系统设置 API：系统信息 / 参数白名单 / 保存 / 连通性诊断
import { http } from './http'
import type {
  ConfigDiagnostics,
  ConfigParamsSnapshot,
  ConfigSaveResult,
  ConfigSystemInfo,
} from '../types/api'

export async function systemInfo(): Promise<ConfigSystemInfo> {
  const { data } = await http.get<ConfigSystemInfo>('/config/system')
  return data
}

export async function params(): Promise<ConfigParamsSnapshot> {
  const { data } = await http.get<ConfigParamsSnapshot>('/config/params')
  return data
}

export async function saveParams(
  payload: Record<string, unknown>,
): Promise<ConfigSaveResult> {
  const { data } = await http.put<ConfigSaveResult>('/config/params', payload)
  return data
}

export async function diagnostics(): Promise<ConfigDiagnostics> {
  const { data } = await http.get<ConfigDiagnostics>('/config/diagnostics')
  return data
}
