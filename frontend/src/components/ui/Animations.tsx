/**
 * 动画工具组件库
 * - AnimatedNumber: 数字滚动动画
 * - PageTransition: 页面切换过渡（fade + slide）
 * - StaggerReveal: 视口渐入动画（IntersectionObserver）
 */
import React, { useEffect, useRef, useState } from 'react'

// ── 数字滚动动画组件 ──
interface AnimatedNumberProps {
  value: number
  duration?: number
  decimals?: number
  prefix?: string
  suffix?: string
  className?: string
}

export const AnimatedNumber: React.FC<AnimatedNumberProps> = ({
  value,
  duration = 600,
  decimals = 0,
  prefix = '',
  suffix = '',
  className = '',
}) => {
  const [displayValue, setDisplayValue] = useState(0)
  const rafRef = useRef<number>(0)
  const prevValueRef = useRef(0)

  useEffect(() => {
    const startValue = prevValueRef.current
    const diff = value - startValue
    const startTime = performance.now()

    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)
      // easeOutCubic 缓动
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplayValue(startValue + diff * eased)

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate)
      } else {
        prevValueRef.current = value
      }
    }

    rafRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(rafRef.current)
  }, [value, duration])

  const formatted = displayValue.toLocaleString('zh-CN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })

  return (
    <span className={`counter-animate tabular-nums ${className}`} key={value}>
      {prefix}{formatted}{suffix}
    </span>
  )
}

// ── 页面切换过渡包装组件 ──
interface PageTransitionProps {
  children: React.ReactNode
  /** 用于触发重渲染的唯一 key（如路由路径） */
  pageKey?: string
}

export const PageTransition: React.FC<PageTransitionProps> = ({ children, pageKey }) => {
  return (
    <div key={pageKey} className="page-transition">
      {children}
    </div>
  )
}

// ── 视口渐入动画组件（IntersectionObserver）──
interface StaggerRevealProps {
  children: React.ReactNode
  className?: string
  /** 子元素交错延迟（ms） */
  stagger?: number
  /** 一次性触发还是每次进入都触发 */
  once?: boolean
  /** 根元素外边距，控制提前触发量 */
  rootMargin?: string
}

export const StaggerReveal: React.FC<StaggerRevealProps> = ({
  children,
  className = '',
  stagger = 80,
  once = true,
  rootMargin = '0px 0px -40px 0px',
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const [isVisible, setIsVisible] = useState(false)

  useEffect(() => {
    const node = containerRef.current
    if (!node) return

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true)
          if (once) observer.disconnect()
        } else if (!once) {
          setIsVisible(false)
        }
      },
      { rootMargin, threshold: 0.1 }
    )

    observer.observe(node)
    return () => observer.disconnect()
  }, [once, rootMargin])

  // 为直接子元素添加 stagger 延迟
  const childrenWithStagger = React.Children.map(children, (child, index) => {
    if (!React.isValidElement(child)) return child
    return React.cloneElement(child as React.ReactElement<{
      style?: React.CSSProperties
      className?: string
    }>, {
      style: {
        ...((child as React.ReactElement<{ style?: React.CSSProperties }>).props.style || {}),
        transitionDelay: `${index * stagger}ms`,
      },
      className: `${(child as React.ReactElement<{ className?: string }>).props.className || ''} ${isVisible ? 'reveal-visible' : 'reveal-hidden'}`,
    })
  })

  return (
    <div ref={containerRef} className={className}>
      {childrenWithStagger}
    </div>
  )
}

// ── 单元素视口渐入 Hook ──
export const useInView = (options?: IntersectionObserverInit) => {
  const ref = useRef<HTMLElement>(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return

    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setInView(true)
        observer.disconnect()
      }
    }, options || { threshold: 0.1 })

    observer.observe(node)
    return () => observer.disconnect()
  }, [options])

  return { ref, inView }
}
