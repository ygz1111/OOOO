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

  login: (credentials: LoginRequest) => Promise<void>
  register: (data: RegisterRequest) => Promise<void>
  logout: () => Promise<void>
  clearAuth: () => void
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

  // 从 localStorage 恢复认证状态
  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_KEY)
    const storedUser = localStorage.getItem(USER_KEY)

    if (storedToken && storedUser) {
      try {
        const parsedUser = JSON.parse(storedUser) as User
        setToken(storedToken)
        setUser(parsedUser)
        apiService.setAuthToken(storedToken)
      } catch {
        localStorage.removeItem(TOKEN_KEY)
        localStorage.removeItem(REFRESH_TOKEN_KEY)
        localStorage.removeItem(USER_KEY)
      }
    }
    setIsLoading(false)
  }, [])

  const login = useCallback(async (credentials: LoginRequest) => {
    const response = await apiService.login(credentials)

    localStorage.setItem(TOKEN_KEY, response.access_token)
    if (response.refresh_token) {
      localStorage.setItem(REFRESH_TOKEN_KEY, response.refresh_token)
    }
    localStorage.setItem(USER_KEY, JSON.stringify(response.user))

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
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(REFRESH_TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      setToken(null)
      setUser(null)
      apiService.setAuthToken(null)
    }
  }, [token])

  const clearAuth = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    setToken(null)
    setUser(null)
    apiService.setAuthToken(null)
  }, [])

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
