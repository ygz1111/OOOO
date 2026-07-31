/**
 * NumberTicker - Magic UI 风格数字滚动动画
 * 使用 requestAnimationFrame 实现数字从 0 滚动到目标值
 * 移植自 Magic UI (https://magicui.design/docs/components/number-ticker)
 * 适配本项目: React 18 + TypeScript，无需 Framer Motion
 */
import React, { useEffect, useRef } from 'react'

export interface NumberTickerProps {
  value: number
  startValue?: number
  delay?: number
  decimalPlaces?: number
  className?: string
  suffix?: string
}

export const NumberTicker: React.FC<NumberTickerProps> = ({
  value,
  startValue = 0,
  delay = 0,
  decimalPlaces = 0,
  className = '',
  suffix = '',
}) => {
  const ref = useRef<HTMLSpanElement>(null)
  const hasAnimated = useRef(false)

  useEffect(() => {
    const element = ref.current
    if (!element || hasAnimated.current) return

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !hasAnimated.current) {
            hasAnimated.current = true
            const startTime = performance.now() + delay * 1000
            const duration = 1500

            const animate = (currentTime: number) => {
              if (currentTime < startTime) {
                requestAnimationFrame(animate)
                return
              }
              const elapsed = currentTime - startTime
              const progress = Math.min(elapsed / duration, 1)
              const eased = 1 - Math.pow(1 - progress, 3)
              const current = startValue + (value - startValue) * eased

              element.textContent =
                Intl.NumberFormat('en-US', {
                  minimumFractionDigits: decimalPlaces,
                  maximumFractionDigits: decimalPlaces,
                }).format(Number(current.toFixed(decimalPlaces))) + suffix

              if (progress < 1) requestAnimationFrame(animate)
            }
            requestAnimationFrame(animate)
          }
        })
      },
      { threshold: 0.1 }
    )

    observer.observe(element)
    return () => observer.disconnect()
  }, [value, startValue, delay, decimalPlaces, suffix])

  return (
    <span ref={ref} className={className}>
      {startValue}
      {suffix}
    </span>
  )
}
