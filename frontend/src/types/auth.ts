// 认证与用户管理后端契约类型。

export type UserRole = 'admin' | 'editor' | 'viewer'

export interface User {
  id: string
  username: string
  display_name: string
  role: UserRole
  is_active: boolean
  created_at: string
  updated_at: string
  last_login_at: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  token: string
  user: User
}

export interface UserCreate {
  username: string
  password: string
  display_name?: string
  role: UserRole
}

export interface UserUpdate {
  role?: UserRole
  is_active?: boolean
  display_name?: string
  reset_password?: string
}

export interface UserListResponse {
  users: User[]
}
