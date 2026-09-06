// auth store 测试：token 持久化 / 登录登出 / 角色判断 / 401 清理
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '../auth'

// mock localStorage（vitest node 环境无 localStorage）
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v },
    removeItem: (k: string) => { delete store[k] },
    clear: () => { store = {} },
  }
})()
vi.stubGlobal('localStorage', localStorageMock)

// mock api/auth
vi.mock('../../api/auth', () => ({
  login: vi.fn(),
  me: vi.fn(),
  changePassword: vi.fn(),
}))

// mock api/http（避免真实拦截器）
vi.mock('../../api/http', () => ({
  http: {
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  setTokenGetter: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}))

// mock element-plus（避免 DOM 依赖）
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn() },
}))

import * as authApi from '../../api/auth'

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('初始状态无 token 无用户', () => {
    const store = useAuthStore()
    expect(store.token).toBeNull()
    expect(store.currentUser).toBeNull()
    expect(store.isAdmin()).toBe(false)
    expect(store.isEditor()).toBe(false)
  })

  it('登录成功后保存 token 和用户', async () => {
    const mockUser = {
      id: 'u_1', username: 'admin', display_name: '管理员',
      role: 'admin' as const, is_active: true, created_at: 0, updated_at: 0, last_login_at: 0,
    }
    vi.mocked(authApi.login).mockResolvedValue({ token: 'test-token', user: mockUser })

    const store = useAuthStore()
    const ok = await store.login({ username: 'admin', password: 'admin' })

    expect(ok).toBe(true)
    expect(store.token).toBe('test-token')
    expect(store.currentUser).toEqual(mockUser)
    expect(localStorage.getItem('kb_auth_token')).toBe('test-token')
    expect(store.isAdmin()).toBe(true)
    expect(store.isEditor()).toBe(true)
    expect(store.canEditDocuments()).toBe(true)
  })

  it('登录失败不保存 token', async () => {
    vi.mocked(authApi.login).mockRejectedValue(new Error('用户名或密码错误'))

    const store = useAuthStore()
    const ok = await store.login({ username: 'admin', password: 'wrong' })

    expect(ok).toBe(false)
    expect(store.token).toBeNull()
    expect(localStorage.getItem('kb_auth_token')).toBeNull()
  })

  it('登出清除 token 和用户', () => {
    const store = useAuthStore()
    store.token = 'some-token'
    store.currentUser = { id: 'u_1', username: 'x', display_name: 'X', role: 'viewer' as const, is_active: true, created_at: 0, updated_at: 0, last_login_at: 0 }
    localStorage.setItem('kb_auth_token', 'some-token')

    store.logout()

    expect(store.token).toBeNull()
    expect(store.currentUser).toBeNull()
    expect(localStorage.getItem('kb_auth_token')).toBeNull()
  })

  it('editor 角色判断正确', () => {
    const store = useAuthStore()
    store.currentUser = { id: 'u_2', username: 'ed', display_name: '编辑', role: 'editor' as const, is_active: true, created_at: 0, updated_at: 0, last_login_at: 0 }
    expect(store.isAdmin()).toBe(false)
    expect(store.isEditor()).toBe(true)
    expect(store.canEditDocuments()).toBe(true)
  })

  it('viewer 角色判断正确', () => {
    const store = useAuthStore()
    store.currentUser = { id: 'u_3', username: 'v', display_name: '查看', role: 'viewer' as const, is_active: true, created_at: 0, updated_at: 0, last_login_at: 0 }
    expect(store.isAdmin()).toBe(false)
    expect(store.isEditor()).toBe(false)
    expect(store.canEditDocuments()).toBe(false)
  })

  it('fetchCurrentUser 成功时设置用户', async () => {
    const mockUser = { id: 'u_1', username: 'admin', display_name: '管理员', role: 'admin' as const, is_active: true, created_at: 0, updated_at: 0, last_login_at: 0 }
    vi.mocked(authApi.me).mockResolvedValue(mockUser)

    const store = useAuthStore()
    store.token = 'valid-token'
    const ok = await store.fetchCurrentUser()

    expect(ok).toBe(true)
    expect(store.currentUser).toEqual(mockUser)
  })

  it('fetchCurrentUser 失败时清理 token', async () => {
    vi.mocked(authApi.me).mockRejectedValue(new Error('401'))

    const store = useAuthStore()
    store.token = 'invalid-token'
    localStorage.setItem('kb_auth_token', 'invalid-token')
    const ok = await store.fetchCurrentUser()

    expect(ok).toBe(false)
    expect(store.token).toBeNull()
    expect(localStorage.getItem('kb_auth_token')).toBeNull()
  })
})
