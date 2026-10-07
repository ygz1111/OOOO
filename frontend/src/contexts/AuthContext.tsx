import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { apiService } from '../services/api'
import { User, LoginRequest, RegisterRequest } from '../types/auth'

const TOKEN_KEY = 'smartgrid_access_token'
const REFRESH_TOKEN_KEY = 'smartgrid_refresh_token'
const USER_KEY = 'smartgrid_user'

interface AuthContextType {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean

  login: (credentials: LoginRequest, rememberMe?: boolean) => Promise<void>
  register: (data: RegisterRequest) => Promise<void>
  logout: () => Promise<void>
  clearAuth: () => void
}

// 2026-08 优化："记住我"真实生效：
//   勾选 → localStorage（跨会话持久）
//   不勾选 → sessionStorage（仅当前浏览器会话，关闭即失效）
// 此前无论勾选与否都无条件写入 localStorage，"记住我"形同虚设。
const persist = {
  get(key: string): string | null {
    return localStorage.getItem(key) ?? sessionStorage.getItem(key)
  },
  set(key: string, value: string, remember: boolean): void {
    if (remember) {
      localStorage.setItem(key, value)
    } else {
      sessionStorage.setItem(key, value)
    }
  },
  remove(key: string): void {
    localStorage.removeItem(key)
    sessionStorage.removeItem(key)
  },
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

interface AuthProviderProps {
  children: ReactNode
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const clearAuth = useCallback(() => {
    persist.remove(TOKEN_KEY)
    persist.remove(REFRESH_TOKEN_KEY)
    persist.remove(USER_KEY)
    setToken(null)
    setUser(null)
    apiService.setAuthToken(null)
  }, [])

  // 从 localStorage/sessionStorage 恢复认证状态
  useEffect(() => {
    // 注册 401 自动处理：token 过期时 apiService 会先用 refresh token 刷新并重试；
    // 刷新也失败（refresh token 失效）才登出
    apiService.setOnUnauthorized(() => {
      clearAuth()
    })
    apiService.setOnTokenRefreshed((newToken) => {
      setToken(newToken)
    })

    const storedToken = persist.get(TOKEN_KEY)
    const storedUser = persist.get(USER_KEY)

    if (storedToken && storedUser) {
      try {
        const parsedUser = JSON.parse(storedUser) as User
        setToken(storedToken)
        setUser(parsedUser)
        apiService.setAuthToken(storedToken)
      } catch {
        persist.remove(TOKEN_KEY)
        persist.remove(REFRESH_TOKEN_KEY)
        persist.remove(USER_KEY)
      }
    }
    setIsLoading(false)
  }, [clearAuth])

  const login = useCallback(async (credentials: LoginRequest, rememberMe: boolean = true) => {
    const response = await apiService.login(credentials)

    // 勾选"记住我"→ 持久存储；否则仅当前会话（sessionStorage）
    persist.set(TOKEN_KEY, response.access_token, rememberMe)
    if (response.refresh_token) {
      persist.set(REFRESH_TOKEN_KEY, response.refresh_token, rememberMe)
    }
    persist.set(USER_KEY, JSON.stringify(response.user), rememberMe)

    setToken(response.access_token)
    setUser(response.user)
    apiService.setAuthToken(response.access_token)
  }, [])

  const register = useCallback(async (data: RegisterRequest) => {
    await apiService.register(data)
  }, [])

  const logout = useCallback(async () => {
    try {
      if (token) {
        await apiService.logout()
      }
    } catch {
      // 即使后端登出失败也清除本地状态
    } finally {
      persist.remove(TOKEN_KEY)
      persist.remove(REFRESH_TOKEN_KEY)
      persist.remove(USER_KEY)
      setToken(null)
      setUser(null)
      apiService.setAuthToken(null)
    }
  }, [token])

  const value: AuthContextType = {
    user,
    token,
    isAuthenticated: !!token && !!user,
    isLoading,
    login,
    register,
    logout,
    clearAuth,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
