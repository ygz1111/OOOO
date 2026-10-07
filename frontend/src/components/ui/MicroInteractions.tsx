/**
 * 微交互工具组件
 * - RefreshButton: 刷新按钮带旋转动画
 */
import React from 'react'
import { RefreshCw } from 'lucide-react'

// ── 刷新按钮组件 ──
interface RefreshButtonProps {
  onClick: () => void
  isLoading?: boolean
  className?: string
}

export const RefreshButton: React.FC<RefreshButtonProps> = ({ onClick, isLoading = false, className = '' }) => (
  <button
    onClick={onClick}
    disabled={isLoading}
    className={`btn ${/(?:^|\s)btn-(?:primary|success|ghost)(?:\s|$)/.test(className) ? '' : 'btn-ghost'} !py-1.5 !text-sm ${className}`}
  >
    <RefreshCw className={`w-4 h-4 btn-refresh ${isLoading ? 'spinning' : ''}`} aria-hidden="true" />
    刷新
  </button>
)
