/**
 * 微交互工具组件
 * - RippleButton: 按钮点击涟漪效果
 * - RefreshButton: 刷新按钮带旋转动画
 * - useRipple: 涟漪效果 hook
 */
import React, { useCallback, useState } from 'react'
import { RefreshCw } from 'lucide-react'

// ── 涟漪效果 Hook ──
export function useRipple() {
  const [ripples, setRipples] = useState<Array<{ id: number; x: number; y: number; size: number }>>([])

  const createRipple = useCallback((event: React.MouseEvent<HTMLElement>) => {
    const target = event.currentTarget
    const rect = target.getBoundingClientRect()
    const size = Math.max(rect.width, rect.height)
    const x = event.clientX - rect.left - size / 2
    const y = event.clientY - rect.top - size / 2
    const id = Date.now()

    setRipples(prev => [...prev, { id, x, y, size }])
    setTimeout(() => {
      setRipples(prev => prev.filter(r => r.id !== id))
    }, 600)
  }, [])

  return { ripples, createRipple }
}

// ── 涟漪按钮组件 ──
interface RippleButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children: React.ReactNode
}

export const RippleButton: React.FC<RippleButtonProps> = ({ children, className = '', onClick, ...props }) => {
  const { ripples, createRipple } = useRipple()

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    createRipple(e)
    onClick?.(e)
  }

  return (
    <button
      className={`ripple-btn ${className}`}
      onClick={handleClick}
      {...props}
    >
      {ripples.map(ripple => (
        <span
          key={ripple.id}
          className="ripple-effect"
          style={{
            left: ripple.x,
            top: ripple.y,
            width: ripple.size,
            height: ripple.size,
          }}
        />
      ))}
      {children}
    </button>
  )
}

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
    className={`btn btn-ghost !py-1.5 !text-sm ${className}`}
  >
    <RefreshCw className={`w-4 h-4 btn-refresh ${isLoading ? 'spinning' : ''}`} />
    刷新
  </button>
)
