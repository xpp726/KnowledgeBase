// axios 实例：统一 baseURL / 超时 / 错误归一化 / token 注入 / 401 跳转
import axios from 'axios'

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
      return Promise.reject(new Error('登录已过期，请重新登录'))
    }
    const message =
      detail ?? (status ? `请求失败（HTTP ${status}）` : '网络连接失败')
    return Promise.reject(new Error(message))
  },
)
