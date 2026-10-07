import React, { useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'
import { Home, TrendingUp, Cloud, Sun, Activity, BarChart3, Gauge, DollarSign, X } from 'lucide-react'
import { useApi } from '../contexts/ApiContext'

interface SidebarProps { open: boolean; onClose: () => void }
interface MenuItem { name: string; href: string; icon: React.ReactNode }
interface MenuGroup { label: string; items: MenuItem[] }

const menuGroups: MenuGroup[] = [
  { label: '运行总览', items: [{ name: '综合总览', href: '/', icon: <Home className="h-4 w-4" /> }] },
  { label: '预测分析', items: [
    { name: '负荷预测', href: '/load-forecast', icon: <TrendingUp className="h-4 w-4" /> },
    { name: '电价预测', href: '/price-forecast', icon: <DollarSign className="h-4 w-4" /> },
    { name: '光伏预测', href: '/solar-generation', icon: <Sun className="h-4 w-4" /> },
    { name: '历史分析', href: '/historical-analysis', icon: <BarChart3 className="h-4 w-4" /> },
  ] },
  { label: '运行监测', items: [
    { name: '气象监测', href: '/weather-monitor', icon: <Cloud className="h-4 w-4" /> },
    { name: '运行态势', href: '/operation-situation', icon: <Gauge className="h-4 w-4" /> },
  ] },
  { label: '系统管理', items: [{ name: '系统状态', href: '/system-status', icon: <Activity className="h-4 w-4" /> }] },
]

const Sidebar: React.FC<SidebarProps> = ({ open, onClose }) => {
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const { systemStatus, errors } = useApi()
  const sysOnline = !errors.systemStatus && systemStatus?.status === 'healthy'
  const sysDegraded = !errors.systemStatus && systemStatus?.status === 'degraded'
  const statusLabel = sysOnline ? '模型服务在线' : sysDegraded ? '模型服务降级' : '模型服务未连接'
  const statusClass = sysOnline ? 'status-online' : sysDegraded ? 'status-warning' : 'status-offline'

  useEffect(() => {
    if (!open) return
    closeButtonRef.current?.focus()
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-slate-950/45 lg:hidden" onClick={onClose} aria-hidden="true" />}
      <aside className={`formal-sidebar fixed left-0 top-0 z-50 h-full w-[232px] flex-col border-r border-white/10 bg-[#132B45] text-white transition-transform duration-200 ${open ? 'flex translate-x-0' : 'hidden -translate-x-full'} lg:flex lg:relative lg:translate-x-0`} aria-label="主导航">
        <div className="sidebar-brand flex min-h-[78px] items-center justify-between border-b border-white/15 px-4 py-4">
          <div className="flex items-center gap-3">
            <div className="formal-brand-mark flex h-9 w-9 shrink-0 items-center justify-center rounded border border-white/25 text-white" aria-hidden="true">
              <BarChart3 className="h-5 w-5" strokeWidth={1.7} />
            </div>
            <div>
              <h2 className="text-[15px] font-semibold leading-tight tracking-wide text-white">电网预测系统</h2>
              <p className="sidebar-brand-subtitle mt-1.5 text-[11px] text-slate-300">区域预测与运行分析</p>
            </div>
          </div>
          <button ref={closeButtonRef} onClick={onClose} className="flex min-h-[32px] min-w-[32px] items-center justify-center rounded text-slate-200 hover:bg-white/10 lg:hidden" aria-label="关闭菜单">
            <X className="h-5 w-5" />
          </button>
        </div>
        <nav className="sidebar-nav flex-1 space-y-5 overflow-y-auto px-3 py-5" aria-label="页面导航">
          {menuGroups.map(group => (
            <div key={group.label} className="sidebar-menu-group">
              <div className="formal-sidebar-group px-3 pb-2 text-[11px] text-slate-300">{group.label}</div>
              <ul className="space-y-1">
                {group.items.map(item => (
                  <li key={item.href}>
                    <NavLink to={item.href} onClick={onClose} className={({ isActive }) => `sidebar-nav-link flex min-h-[42px] items-center gap-3 rounded px-3 py-2.5 text-sm transition-colors ${isActive ? 'formal-sidebar-active bg-white/15 font-medium text-white' : 'text-slate-200 hover:bg-white/10 hover:text-white'}`}>
                      <span className="sidebar-nav-icon shrink-0" aria-hidden="true">{item.icon}</span>
                      <span>{item.name}</span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer border-t border-white/15 px-5 py-4">
          <div className="flex items-center gap-2">
            <span className={`status-indicator ${statusClass}`} />
            <span className="text-xs text-slate-200">{statusLabel}</span>
          </div>
          <p className="mt-2 text-[11px] text-slate-300">本地运行 · 美国东部时间</p>
        </div>
      </aside>
    </>
  )
}

export default Sidebar
