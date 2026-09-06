// axios 实例：统一 baseURL / 超时 / 错误归一化
import axios from 'axios'

export const http = axios.create({
  baseURL: '/api',
  timeout: 30_000,
})

http.interceptors.response.use(
  (res) => res,
  (err: unknown) => {
    const status = (err as { response?: { status?: number; data?: { detail?: string } } })
      .response?.status
    const detail = (err as { response?: { data?: { detail?: string } } }).response?.data
      ?.detail
    const message =
      detail ?? (status ? `请求失败（HTTP ${status}）` : '网络连接失败')
    return Promise.reject(new Error(message))
  },
)
