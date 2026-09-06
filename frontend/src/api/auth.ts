// 认证接口：登录 / 当前用户 / 修改密码
import { http } from './http'
import type { LoginRequest, LoginResponse, User } from '../types/api'

export async function login(payload: LoginRequest): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>('/auth/login', payload)
  return data
}

export async function me(): Promise<User> {
  const { data } = await http.get<User>('/auth/me')
  return data
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<{ ok: boolean }> {
  const { data } = await http.post<{ ok: boolean }>('/auth/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
  return data
}
