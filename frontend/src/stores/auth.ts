// 认证 store：token 持久化 / 当前用户 / 登录登出 / 401 自动跳转
//
// 设计：token 存 localStorage，刷新页面后从 localStorage 恢复并拉 /auth/me 验证。
// http 拦截器通过 setTokenGetter 取 token，401 时通过 setUnauthorizedHandler 触发登出。

import { ref } from 'vue'
import { defineStore } from 'pinia'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { LoginRequest, User } from '../types/api'
import * as authApi from '../api/auth'
import { setTokenGetter, setUnauthorizedHandler } from '../api/http'

const TOKEN_KEY = 'kb_auth_token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const currentUser = ref<User | null>(null)
  const loading = ref(false)
  const initialized = ref(false)

  // 注入 http 拦截器所需的回调（只做一次）
  setTokenGetter(() => token.value)
  setUnauthorizedHandler(() => {
    // 401：清 token 跳登录
    if (token.value) {
      token.value = null
      currentUser.value = null
      localStorage.removeItem(TOKEN_KEY)
      ElMessage.warning('登录已过期，请重新登录')
      const router = useRouter()
      router.push('/login')
    }
  })

  async function login(payload: LoginRequest): Promise<boolean> {
    loading.value = true
    try {
      const res = await authApi.login(payload)
      token.value = res.token
      currentUser.value = res.user
      localStorage.setItem(TOKEN_KEY, res.token)
      return true
    } catch (e) {
      ElMessage.error((e as Error).message || '登录失败')
      return false
    } finally {
      loading.value = false
    }
  }

  function logout() {
    token.value = null
    currentUser.value = null
    localStorage.removeItem(TOKEN_KEY)
  }

  async function fetchCurrentUser(): Promise<boolean> {
    if (!token.value) return false
    try {
      currentUser.value = await authApi.me()
      return true
    } catch {
      // token 无效，清理
      token.value = null
      currentUser.value = null
      localStorage.removeItem(TOKEN_KEY)
      return false
    }
  }

  // 页面加载时初始化：有 token 则拉用户信息验证
  async function init() {
    if (initialized.value) return
    if (token.value) {
      await fetchCurrentUser()
    }
    initialized.value = true
  }

  // 角色判断辅助
  function isAdmin(): boolean {
    return currentUser.value?.role === 'admin'
  }

  function isEditor(): boolean {
    const role = currentUser.value?.role
    return role === 'admin' || role === 'editor'
  }

  function canEditDocuments(): boolean {
    return isEditor()
  }

  return {
    token,
    currentUser,
    loading,
    initialized,
    login,
    logout,
    fetchCurrentUser,
    init,
    isAdmin,
    isEditor,
    canEditDocuments,
  }
})
