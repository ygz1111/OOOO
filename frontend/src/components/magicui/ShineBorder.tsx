/**
 * ShineBorder - Magic UI 风格发光边框
 * 纯 CSS mask 动画，实现沿边框流动的渐变光效
 * 移植自 Magic UI (https://magicui.design/docs/components/shine-border)
 */
import React from 'react'

export interface ShineBorderProps {
  borderWidth?: number
  duration?: number
  shineColor?: string | string[]
  className?: string
  children?: React.ReactNode
}

export const ShineBorder: React.FC<ShineBorderProps> = ({
  borderWidth = 1,
  duration = 14,
  shineColor = '#3B82F6',
  className = '',
  children,
}) => {
  const colorStr = Array.isArray(shineColor) ? shineColor.join(',') : shineColor

  return (
    <div className={`relative rounded-[inherit] ${className}`}>
      {/* 发光边框层 */}
      <div
        className="pointer-events-none absolute inset-0 rounded-[inherit] motion-safe:animate-shine-border will-change-[background-position]"
        style={
          {
            backgroundImage: `radial-gradient(transparent, transparent, ${colorStr}, transparent, transparent)`,
            backgroundSize: '300% 300%',
            mask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
            WebkitMask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
            WebkitMaskComposite: 'xor',
            maskComposite: 'exclude',
            padding: `${borderWidth}px`,
            animationDuration: `${duration}s`,
          } as React.CSSProperties
        }
        aria-hidden="true"
      />
      {children}
    </div>
  )
}
