import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import { RefreshCw, Menu, Cpu, LogOut, ChevronDown, User as UserIcon, BarChart3, LayoutDashboard, Monitor } from 'lucide-react'
import { useApi } from '../contexts/ApiContext'
import { useAuth } from '../contexts/AuthContext'
import { formatEastern, ET_TIME, ET_DATE } from '../utils/time'
import { predictionHealth } from '../utils/predictionHealth'
import { useWorkspaceTheme } from '../contexts/ThemeContext'

interface HeaderProps { onMenuClick: () => void }

const Header: React.FC<HeaderProps> = ({ onMenuClick }) => {
  const { refreshAll, systemStatus, prediction, errors, isLoading } = useApi()
  const { user, logout } = useAuth()
  const { theme, setTheme } = useWorkspaceTheme()
  const [now, setNow] = useState(new Date())
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const userMenuRef = useRef<HTMLDivElement>(null)
  const userMenuButtonRef = useRef<HTMLButtonElement>(null)
  const location = useLocation()

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    setUserMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!userMenuOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) setUserMenuOpen(false)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setUserMenuOpen(false)
      userMenuButtonRef.current?.focus()
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [userMenuOpen])

  const health = predictionHealth(errors.systemStatus ? null : systemStatus, prediction, errors.prediction, now.getTime())
  const healthColor = health.indicator === 'status-online' ? 'header-health-ready' : health.indicator === 'status-warning' ? 'header-health-warning' : 'header-health-offline'
  const isRefreshing = Object.values(isLoading).some(Boolean)
  const displayName = useMemo(() => user?.full_name || user?.username || '用户', [user])
  const handleLogout = useCallback(async () => {
    setIsLoggingOut(true)
    try { await logout() } finally { setIsLoggingOut(false); setUserMenuOpen(false) }
  }, [logout])

  return (
    <header className="app-header formal-header sticky top-0 z-30 px-3 py-3 md:px-6">
      <div className="header-inner flex min-h-[48px] items-center justify-between gap-2 md:gap-4">
        <div className="header-brand flex min-w-0 items-center gap-2 md:gap-3">
          <button onClick={onMenuClick} className="header-menu-trigger flex min-h-[36px] min-w-[36px] items-center justify-center rounded lg:hidden" aria-label="打开菜单">
            <Menu className="h-5 w-5" />
          </button>
          <div className="header-brand-mark hidden h-9 w-9 shrink-0 items-center justify-center sm:flex" aria-hidden="true">
            <BarChart3 className="h-6 w-6" strokeWidth={1.7} />
          </div>
          <div className="min-w-0">
            <h1 className="header-brand-title truncate text-sm font-semibold tracking-wide md:text-lg">智能电网负荷预测系统</h1>
            <p className="header-brand-subtitle mt-1 hidden text-xs sm:block">新英格兰区域 · 负荷、电价及光伏预测</p>
          </div>
        </div>
        <div className="header-actions flex shrink-0 items-center gap-1.5 md:gap-3">
          <div className="system-health-chip formal-header-status hidden items-center gap-2 text-xs xl:flex" role="status" aria-live="polite">
            <span className={`status-indicator ${health.indicator}`} />
            <span className={healthColor}>{health.text}</span>
          </div>
          {systemStatus && (
            <div className="header-model-count model-count-chip hidden items-center gap-1.5 pl-3 text-xs 2xl:flex" title="已加载模型数，预测数据状态单独显示">
              <Cpu className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="tabular-nums">模型 {systemStatus.models_loaded}/{systemStatus.models_total ?? 3}</span>
            </div>
          )}
          <div className="workspace-theme-switch flex shrink-0 items-center" role="group" aria-label="工作台主题">
            <button type="button" onClick={() => setTheme('business')} aria-pressed={theme === 'business'} aria-label="正式工作台" title="正式工作台" className={`theme-option flex min-h-[36px] items-center gap-1.5 px-2 text-xs md:px-3 ${theme === 'business' ? 'is-active' : ''}`}>
              <LayoutDashboard className="hidden h-3.5 w-3.5 md:block" aria-hidden="true" />
              <span className="hidden sm:inline">正式工作台</span><span className="sm:hidden">正式</span>
            </button>
            <button type="button" onClick={() => setTheme('monitor')} aria-pressed={theme === 'monitor'} aria-label="深色监控" title="深色监控" className={`theme-option flex min-h-[36px] items-center gap-1.5 px-2 text-xs md:px-3 ${theme === 'monitor' ? 'is-active' : ''}`}>
              <Monitor className="hidden h-3.5 w-3.5 md:block" aria-hidden="true" />
              <span className="hidden sm:inline">深色监控</span><span className="sm:hidden">监控</span>
            </button>
          </div>
          <button onClick={() => refreshAll()} disabled={isRefreshing} className="header-refresh flex min-h-[36px] min-w-[36px] items-center justify-center gap-2 rounded px-2 text-xs md:px-3" aria-label="刷新所有数据">
            <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? 'animate-spin' : ''}`} aria-hidden="true" />
            <span className="hidden md:inline">刷新数据</span>
          </button>
          <div className="header-clock hidden pl-3 text-right xl:block" aria-label="当前时间（新英格兰）">
            <div className="header-clock-time text-xs font-medium tabular-nums leading-tight">{formatEastern(now, ET_TIME)}</div>
            <div className="header-clock-date mt-0.5 text-[11px] tabular-nums">{formatEastern(now, ET_DATE)} ET</div>
          </div>
          <div className="relative" ref={userMenuRef}>
            <button ref={userMenuButtonRef} onClick={() => setUserMenuOpen(!userMenuOpen)} className="header-user-trigger user-menu-trigger flex min-h-[36px] min-w-[36px] items-center justify-center gap-2 rounded px-2 py-1.5 md:px-2.5" aria-label="用户菜单" aria-expanded={userMenuOpen} aria-haspopup="menu" aria-controls={userMenuOpen ? 'account-menu' : undefined}>
              <UserIcon className="h-4 w-4" aria-hidden="true" />
              <span className="hidden max-w-[96px] truncate text-xs md:block">{displayName}</span>
              <ChevronDown className={`hidden h-3.5 w-3.5 transition-transform md:block ${userMenuOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
            </button>
            {userMenuOpen && (
              <div id="account-menu" className="formal-user-menu absolute right-0 top-full z-50 mt-2 w-60 overflow-hidden rounded border border-edge bg-surface-raised shadow-lg" role="menu">
                <div className="border-b border-edge bg-surface-muted px-4 py-3">
                  <div className="truncate text-sm font-medium text-ink">{displayName}</div>
                  {user?.email && <div className="mt-1 truncate text-xs text-muted">{user.email}</div>}
                  {user?.department && <div className="mt-1 text-xs text-muted">{user.department}</div>}
                </div>
                <div className="p-1.5">
                  <button onClick={handleLogout} disabled={isLoggingOut} className="flex w-full items-center gap-2 rounded px-3 py-2 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50" role="menuitem">
                    <LogOut className="h-4 w-4" aria-hidden="true" />
                    {isLoggingOut ? '正在退出...' : '退出登录'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}

export default Header
