// 用户管理接口（admin 专属）：列表 / 创建 / 修改
import { http } from './http'
import type { User, UserCreate, UserListResponse, UserUpdate } from '../types/api'

export async function listUsers(): Promise<User[]> {
  const { data } = await http.get<UserListResponse>('/users')
  return data.users
}

export async function createUser(payload: UserCreate): Promise<User> {
  const { data } = await http.post<{ user: User }>('/users', payload)
  return data.user
}

export async function updateUser(userId: string, payload: UserUpdate): Promise<User> {
  const { data } = await http.put<{ user: User }>(`/users/${userId}`, payload)
  return data.user
}
