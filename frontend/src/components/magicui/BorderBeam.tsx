/**
 * BorderBeam - Magic UI 风格边框光束效果
 * 纯 CSS 实现，使用 offset-path 动画沿边框移动光束
 * 移植自 Magic UI (https://magicui.design/docs/components/border-beam)
 * 适配本项目: React 18 + TypeScript，无需 Framer Motion
 */
import React from 'react'

export interface BorderBeamProps {
  size?: number
  duration?: number
  delay?: number
  colorFrom?: string
  colorTo?: string
  borderWidth?: number
  className?: string
}

export const BorderBeam: React.FC<BorderBeamProps> = ({
  size = 200,
  duration = 8,
  delay = 0,
  colorFrom = '#3B82F6',
  colorTo = '#06B6D4',
  borderWidth = 1.5,
  className = '',
}) => {
  return (
    <div
      className={`pointer-events-none absolute inset-0 rounded-[inherit] ${className}`}
      aria-hidden="true"
    >
      <div
        className="absolute"
        style={{
          width: `${size}px`,
          aspectRatio: '1',
          offsetPath: `rect(0 auto auto 0 round ${size}px)`,
          animation: `border-beam-anim ${duration}s linear infinite`,
          animationDelay: `${delay}s`,
          background: `linear-gradient(to left, ${colorFrom}, ${colorTo}, transparent)`,
          borderRadius: 'inherit',
          filter: `blur(${borderWidth}px)`,
        }}
      />
    </div>
  )
}
