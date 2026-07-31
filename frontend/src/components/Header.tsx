import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { RefreshCw, Menu, Activity, Cpu, LogOut, ChevronDown, User as UserIcon } from 'lucide-react'
import { useApi } from '../contexts/ApiContext'
import { useAuth } from '../contexts/AuthContext'

interface HeaderProps {
  onMenuClick: () => void
}

const Header: React.FC<HeaderProps> = ({ onMenuClick }) => {
  const { refreshAll, systemStatus, isLoading } = useApi()
  const { user, logout } = useAuth()
  const [now, setNow] = useState(new Date())
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const userMenuRef = useRef<HTMLDivElement>(null)

  // 实时更新时钟
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  // 点击外部关闭用户菜单
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const getStatusColor = useMemo(() => {
    if (!systemStatus) return 'text-gray-400'
    switch (systemStatus.status) {
      case 'healthy':
        return 'text-green-400'
      case 'degraded':
        return 'text-yellow-400'
      case 'error':
        return 'text-red-400'
      default:
        return 'text-gray-400'
    }
  }, [systemStatus])

  const getStatusText = useMemo(() => {
    if (!systemStatus) return '离线'
    switch (systemStatus.status) {
      case 'healthy':
        return '系统正常'
      case 'degraded':
        return '系统降级'
      case 'error':
        return '系统错误'
      default:
        return '未知'
    }
  }, [systemStatus])

  const isRefreshing = isLoading.prediction || isLoading.weather

  const handleLogout = useCallback(async () => {
    setIsLoggingOut(true)
    try {
      await logout()
    } finally {
      setIsLoggingOut(false)
      setUserMenuOpen(false)
    }
  }, [logout])

  // 获取用户显示名称 — useMemo 稳定引用
  const displayName = useMemo(() => user?.full_name || user?.username || '用户', [user])
  const initials = useMemo(() => displayName.charAt(0).toUpperCase(), [displayName])

  return (
    <header
      className="px-6 py-4 sticky top-0 z-30"
      style={{
        background: 'rgba(5, 8, 16, 0.85)',
        backdropFilter: 'blur(20px) saturate(140%)',
        WebkitBackdropFilter: 'blur(20px) saturate(140%)',
        borderBottom: '1px solid rgba(0, 240, 255, 0.08)',
      }}
    >
      <div className="flex items-center justify-between">
        {/* 左侧 - 菜单按钮和标题 */}
        <div className="flex items-center gap-4">
          <button
            onClick={onMenuClick}
            className="p-2 rounded-lg transition-colors lg:hidden cursor-pointer min-h-[40px] min-w-[40px] flex items-center justify-center"
            style={{ background: 'rgba(0, 240, 255, 0.04)' }}
            aria-label="打开菜单"
          >
            <Menu className="w-5 h-5" />
          </button>

          <div className="flex items-center gap-3">
            <div
              className="p-2 rounded-lg neon-border"
              style={{ background: 'rgba(0, 240, 255, 0.06)' }}
            >
              <Activity
                className="w-6 h-6"
                aria-hidden="true"
                style={{ color: '#00F0FF', filter: 'drop-shadow(0 0 4px rgba(0, 240, 255, 0.5))' }}
              />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white tracking-tight font-cyber">
                智能电网负荷预测系统
              </h1>
              <p className="text-sm font-mono" style={{ color: 'rgba(0, 240, 255, 0.3)' }}>
                实时电网监控与预测平台
              </p>
            </div>
          </div>
        </div>

        {/* 右侧 - 状态和操作 */}
        <div className="flex items-center gap-4">
          {/* 系统状态 */}
          <div
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
            style={{
              background: 'rgba(0, 240, 255, 0.03)',
              border: '1px solid rgba(0, 240, 255, 0.06)',
            }}
            role="status"
            aria-live="polite"
          >
            <span
              className={`status-indicator ${
                systemStatus?.status === 'healthy'
                  ? 'status-online'
                  : systemStatus?.status === 'degraded'
                    ? 'status-warning'
                    : 'status-offline'
              }`}
            ></span>
            <span className={`text-sm font-medium ${getStatusColor}`}>{getStatusText}</span>
          </div>

          {/* 模型状态 */}
          {systemStatus && (
            <div className="hidden md:flex items-center gap-2 text-sm" title="已加载模型数">
              <Cpu
                className="w-4 h-4"
                aria-hidden="true"
                style={{ color: 'rgba(0, 240, 255, 0.4)' }}
              />
              <span
                className="tabular-nums font-mono"
                style={{ color: 'rgba(148, 163, 184, 0.7)' }}
              >
                {systemStatus.models_loaded}/4 模型已加载
              </span>
            </div>
          )}

          {/* 刷新按钮 */}
          <button
            onClick={() => refreshAll(true)}
            disabled={isRefreshing}
            className="btn btn-primary !px-3 !py-2"
            aria-label="刷新所有数据"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} aria-hidden="true" />
            <span className="hidden sm:inline">刷新</span>
          </button>

          {/* 当前时间 */}
          <div className="hidden lg:block text-right" aria-label="当前时间">
            <div className="text-sm font-medium text-white tabular-nums font-mono">
              {now.toLocaleTimeString('zh-CN', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
              })}
            </div>
            <div
              className="text-xs tabular-nums font-mono"
              style={{ color: 'rgba(0, 240, 255, 0.3)' }}
            >
              {now.toLocaleDateString('zh-CN')}
            </div>
          </div>

          {/* 用户菜单 */}
          <div className="relative" ref={userMenuRef}>
            <button
              onClick={() => setUserMenuOpen(!userMenuOpen)}
              className="flex items-center gap-2 px-2 py-1.5 rounded-lg transition-colors cursor-pointer min-h-[40px]"
              style={{ background: 'rgba(0, 240, 255, 0.03)' }}
              aria-label="用户菜单"
              aria-expanded={userMenuOpen}
              aria-haspopup="true"
            >
              {/* 头像 - 赛博朋克霓虹圆形 */}
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold font-cyber"
                style={{
                  background: 'linear-gradient(135deg, rgba(0, 240, 255, 0.2), rgba(255, 45, 149, 0.2))',
                  border: '1px solid rgba(0, 240, 255, 0.3)',
                  boxShadow: '0 0 8px rgba(0, 240, 255, 0.15)',
                }}
              >
                {initials}
              </div>
              <div className="hidden md:block text-left">
                <div className="text-sm font-medium text-white leading-tight">{displayName}</div>
                <div
                  className="text-xs leading-tight font-mono"
                  style={{ color: 'rgba(0, 240, 255, 0.3)' }}
                >
                  {user?.department || '用户'}
                </div>
              </div>
              <ChevronDown
                className={`w-4 h-4 transition-transform ${userMenuOpen ? 'rotate-180' : ''}`}
                style={{ color: 'rgba(0, 240, 255, 0.4)' }}
                aria-hidden="true"
              />
            </button>

            {/* 下拉菜单 */}
            {userMenuOpen && (
              <div
                className="absolute right-0 top-full mt-2 w-64 rounded-xl shadow-2xl overflow-hidden animate-scale-in origin-top-right"
                style={{
                  background: 'rgba(5, 8, 16, 0.95)',
                  backdropFilter: 'blur(20px) saturate(140%)',
                  WebkitBackdropFilter: 'blur(20px) saturate(140%)',
                  border: '1px solid rgba(0, 240, 255, 0.12)',
                  boxShadow: '0 0 24px rgba(0, 240, 255, 0.08), 0 8px 32px rgba(0, 0, 0, 0.5)',
                }}
                role="menu"
              >
                {/* 用户信息头部 */}
                <div
                  className="p-4"
                  style={{ borderBottom: '1px solid rgba(0, 240, 255, 0.06)' }}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className="w-10 h-10 rounded-full flex items-center justify-center text-white font-bold font-cyber"
                      style={{
                        background:
                          'linear-gradient(135deg, rgba(0, 240, 255, 0.2), rgba(255, 45, 149, 0.2))',
                        border: '1px solid rgba(0, 240, 255, 0.3)',
                      }}
                    >
                      {initials}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-white truncate">{displayName}</div>
                      <div
                        className="text-xs truncate font-mono"
                        style={{ color: 'rgba(0, 240, 255, 0.3)' }}
                      >
                        {user?.email}
                      </div>
                    </div>
                  </div>
                  {user?.department && (
                    <div
                      className="mt-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono"
                      style={{ background: 'rgba(0, 240, 255, 0.05)', color: 'rgba(0, 240, 255, 0.5)' }}
                    >
                      <UserIcon className="w-3 h-3" aria-hidden="true" />
                      {user.department}
                    </div>
                  )}
                </div>

                {/* 菜单项 */}
                <div className="p-2">
                  <button
                    onClick={handleLogout}
                    disabled={isLoggingOut}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer disabled:opacity-50"
                    style={{ color: '#FF2D95' }}
                    role="menuitem"
                  >
                    <LogOut className="w-4 h-4" aria-hidden="true" />
                    {isLoggingOut ? '登出中...' : '退出登录'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 快速状态栏 */}
      {systemStatus && (
        <div
          className="flex items-center justify-between mt-4 pt-4 flex-wrap gap-2"
          style={{ borderTop: '1px solid rgba(0, 240, 255, 0.06)' }}
        >
          <div className="flex items-center gap-6 text-sm flex-wrap">
            <div className="flex items-center gap-2">
              <span style={{ color: 'rgba(0, 240, 255, 0.3)' }}>推理设备:</span>
              <span className="text-white font-medium font-mono">{systemStatus.device}</span>
            </div>
            <div className="flex items-center gap-2">
              <span style={{ color: 'rgba(0, 240, 255, 0.3)' }}>平均响应时间:</span>
              <span className="text-white font-medium tabular-nums font-mono">
                {systemStatus.average_inference_time_ms?.toFixed(1)}ms
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span style={{ color: 'rgba(0, 240, 255, 0.3)' }}>总推理次数:</span>
              <span className="text-white font-medium tabular-nums font-mono">
                {systemStatus.total_inferences?.toLocaleString()}
              </span>
            </div>
          </div>

          <div className="text-sm flex items-center gap-2">
            <span style={{ color: 'rgba(0, 240, 255, 0.3)' }}>运行时间:</span>
            <span className="text-white font-medium tabular-nums font-mono">
              {Math.floor(systemStatus.uptime_seconds / 3600)}h{' '}
              {Math.floor((systemStatus.uptime_seconds % 3600) / 60)}m
            </span>
          </div>
        </div>
      )}
    </header>
  )
}

export default Header
