/**
 * 认证授权相关类型定义
 * 与后端 schemas/auth.py 保持一致
 */

export interface User {
  id: number
  username: string
  email: string
  full_name: string | null
  department: string | null
  phone: string | null
  is_active: boolean
  is_verified: boolean
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string | null
  token_type: string
  expires_in: number
  user: User
}

export interface LoginRequest {
  username: string
  password: string
  remember_me: boolean
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
  full_name?: string
  department?: string
  phone?: string
}

