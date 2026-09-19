// axios 实例：统一 baseURL / 超时 / 错误归一化 / token 注入 / 401 跳转
import axios from 'axios'
import { ApiError } from './errors'

export const http = axios.create({
  baseURL: '/api',
  timeout: 30_000,
})

// token 来源（由 auth store 注入，避免循环依赖）
let tokenGetter: (() => string | null) | null = null
let unauthorizedHandler: (() => void) | null = null

export function setTokenGetter(fn: () => string | null) {
  tokenGetter = fn
}

export function setUnauthorizedHandler(fn: () => void) {
  unauthorizedHandler = fn
}

/** 给不经过 Axios 的请求（例如 SSE）复用同一套 Token 来源。 */
export function getToken(): string | null {
  return tokenGetter?.() ?? null
}

export function getAuthHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// 请求拦截：自动带 Authorization header
http.interceptors.request.use((config) => {
  const token = tokenGetter?.()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：401 触发登出跳转，其余归一化错误
http.interceptors.response.use(
  (res) => res,
  (err: unknown) => {
    const status = (err as { response?: { status?: number; data?: { detail?: string } } })
      .response?.status
    const detail = (err as { response?: { data?: { detail?: string } } }).response?.data
      ?.detail
    if (status === 401) {
      unauthorizedHandler?.()
      return Promise.reject(new ApiError('登录已过期，请重新登录', 'http', status))
    }
    const axiosCode = (err as { code?: string }).code
    const kind = axiosCode === 'ECONNABORTED' || axiosCode === 'ETIMEDOUT'
      ? 'timeout'
      : status
        ? 'http'
        : 'network'
    const message = detail ?? (status ? `请求失败（HTTP ${status}）` : '网络连接失败')
    return Promise.reject(new ApiError(message, kind, status))
  },
)
