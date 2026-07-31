import React from 'react'
import { NavLink } from 'react-router-dom'
import {
  Home,
  TrendingUp,
  Cloud,
  Sun,
  Wind,
  Activity,
  BarChart3,
  X,
  Zap,
} from 'lucide-react'

interface SidebarProps {
  open: boolean
  onClose: () => void
}

interface MenuItem {
  name: string
  href: string
  icon: React.ReactNode
  description: string
}

interface MenuGroup {
  label: string
  items: MenuItem[]
}

// ── 按功能逻辑分组 ──
const menuGroups: MenuGroup[] = [
  {
    label: '总览',
    items: [
      {
        name: '总览仪表板',
        href: '/',
        icon: <Home className="w-5 h-5" />,
        description: '系统概览与实时监控',
      },
    ],
  },
  {
    label: '监控',
    items: [
      {
        name: '气象监控',
        href: '/weather-monitor',
        icon: <Cloud className="w-5 h-5" />,
        description: '实时气象数据采集',
      },
    ],
  },
  {
    label: '预测',
    items: [
      {
        name: '负荷预测',
        href: '/load-forecast',
        icon: <TrendingUp className="w-5 h-5" />,
        description: '24小时负荷预测分析',
      },
      {
        name: '光伏发电',
        href: '/solar-generation',
        icon: <Sun className="w-5 h-5" />,
        description: '光伏发电量估算',
      },
      {
        name: '风电预测',
        href: '/wind-generation',
        icon: <Wind className="w-5 h-5" />,
        description: '风电功率物理模型估算',
      },
    ],
  },
  {
    label: '分析',
    items: [
      {
        name: '历史分析',
        href: '/historical-analysis',
        icon: <BarChart3 className="w-5 h-5" />,
        description: '历史数据对比分析',
      },
    ],
  },
  {
    label: '系统',
    items: [
      {
        name: '系统状态',
        href: '/system-status',
        icon: <Activity className="w-5 h-5" />,
        description: '模型与系统监控',
      },
    ],
  },
]

const Sidebar: React.FC<SidebarProps> = ({ open, onClose }) => {
  const handleNavClick = () => {
    onClose()
  }

  return (
    <>
      {/* 移动端遮罩层 */}
      {open && (
        <div
          className="fixed inset-0 bg-black/60 z-40 lg:hidden backdrop-blur-sm animate-fade-in"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* 侧边栏 - 赛博朋克 HUD 风格 */}
      <aside
        className={`
        fixed top-0 left-0 z-50 w-64 h-full transform transition-transform duration-300 ease-out
        ${open ? 'translate-x-0' : '-translate-x-full'}
        lg:relative lg:translate-x-0
      `}
        style={{
          background: 'rgba(5, 8, 16, 0.92)',
          backdropFilter: 'blur(20px) saturate(140%)',
          WebkitBackdropFilter: 'blur(20px) saturate(140%)',
          borderRight: '1px solid rgba(0, 240, 255, 0.08)',
          boxShadow: '4px 0 24px rgba(0, 0, 0, 0.4)',
        }}
        aria-label="主导航"
      >
        <div className="flex flex-col h-full">
          {/* 头部 - 品牌 */}
          <div
            className="flex items-center justify-between px-5 py-5"
            style={{ borderBottom: '1px solid rgba(0, 240, 255, 0.06)' }}
          >
            <div className="flex items-center gap-3">
              <div
                className="p-2.5 rounded-xl neon-border"
                style={{ background: 'rgba(0, 240, 255, 0.06)' }}
              >
                <Zap
                  className="w-6 h-6 text-white"
                  aria-hidden="true"
                  style={{ filter: 'drop-shadow(0 0 4px rgba(0, 240, 255, 0.6))' }}
                />
              </div>
              <div>
                <h2 className="text-base font-bold text-white tracking-tight font-cyber">
                  Smart Grid
                </h2>
                <p className="text-xs" style={{ color: 'rgba(0, 240, 255, 0.4)' }}>
                  负荷预测系统
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-lg transition-colors lg:hidden cursor-pointer min-h-[40px] min-w-[40px] flex items-center justify-center"
              style={{ background: 'rgba(0, 240, 255, 0.04)' }}
              aria-label="关闭菜单"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* 导航菜单 - 按分组渲染 */}
          <nav className="flex-1 px-3 py-4 overflow-y-auto" aria-label="页面导航">
            {menuGroups.map((group, groupIndex) => (
              <div key={group.label} className={groupIndex > 0 ? 'mt-5' : ''}>
                {/* 分组标签 */}
                <div className="px-3 mb-1.5">
                  <span
                    className="text-[11px] font-semibold uppercase tracking-wider font-mono"
                    style={{ color: 'rgba(0, 240, 255, 0.3)' }}
                  >
                    {group.label}
                  </span>
                </div>
                {/* 分组菜单项 */}
                <ul className="space-y-0.5">
                  {group.items.map((item, index) => (
                    <li
                      key={item.href}
                      className={`stagger-item stagger-${(groupIndex * 2 + index + 1) % 8 || 8}`}
                    >
                      <NavLink
                        to={item.href}
                        onClick={handleNavClick}
                        className={({ isActive }) => `
                          relative flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 group cursor-pointer
                          ${isActive ? 'text-white' : 'hover:text-white'}
                        `}
                        style={({ isActive }) =>
                          isActive
                            ? {
                                background: 'rgba(0, 240, 255, 0.08)',
                                boxShadow: 'inset 0 0 12px rgba(0, 240, 255, 0.05)',
                              }
                            : undefined
                        }
                      >
                        {({ isActive }) => (
                          <>
                            {/* 左侧激活指示条 - 霓虹双色渐变 */}
                            <span
                              className={`absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-7 rounded-r-full transition-all duration-200 ${
                                isActive ? 'opacity-100' : 'opacity-0'
                              }`}
                              style={{
                                background: isActive
                                  ? 'linear-gradient(180deg, #00F0FF, #FF2D95)'
                                  : 'transparent',
                                boxShadow: isActive
                                  ? '0 0 8px rgba(0, 240, 255, 0.5)'
                                  : 'none',
                              }}
                            />
                            <div
                              className={`transition-transform duration-200 group-hover:scale-110 ${
                                isActive ? 'text-cyan-400' : ''
                              }`}
                              style={
                                isActive
                                  ? { filter: 'drop-shadow(0 0 4px rgba(0, 240, 255, 0.5))' }
                                  : undefined
                              }
                            >
                              {item.icon}
                            </div>
                            <div className="flex-1 text-left min-w-0">
                              <div className="font-medium text-[15px] leading-tight">
                                {item.name}
                              </div>
                              <div className="text-[13px] opacity-60 mt-0.5 truncate font-mono">
                                {item.description}
                              </div>
                            </div>
                          </>
                        )}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>

          {/* 底部信息 */}
          <div
            className="px-3 py-4 space-y-3"
            style={{ borderTop: '1px solid rgba(0, 240, 255, 0.06)' }}
          >
            {/* 系统运行状态 */}
            <div
              className="flex items-center justify-between px-3 py-2.5 rounded-lg"
              style={{
                background: 'rgba(0, 240, 255, 0.03)',
                border: '1px solid rgba(0, 240, 255, 0.06)',
              }}
            >
              <div className="flex items-center gap-2.5">
                <span className="status-indicator status-online"></span>
                <span className="text-sm font-medium text-white">系统运行中</span>
              </div>
              <span
                className="text-xs font-mono"
                style={{ color: 'rgba(0, 240, 255, 0.4)' }}
              >
                v1.0.0
              </span>
            </div>

            {/* 功能描述 */}
            <div className="px-3">
              <p
                className="text-xs leading-relaxed font-mono"
                style={{ color: 'rgba(0, 240, 255, 0.25)' }}
              >
                实时负荷预测 · 气象监控 · 光伏+风电
              </p>
              <p
                className="text-[11px] mt-1 font-mono"
                style={{ color: 'rgba(255, 255, 255, 0.15)' }}
              >
                毕业设计项目
              </p>
            </div>
          </div>
        </div>
      </aside>
    </>
  )
}

export default Sidebar
