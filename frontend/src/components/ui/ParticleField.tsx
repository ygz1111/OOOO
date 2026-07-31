/**
 * 科技感粒子背景组件
 * 使用 Canvas 绘制粒子连线动画，轻量高效
 * 支持自适应屏幕尺寸和 prefers-reduced-motion
 *
 * 优化点：
 * 1. 修复 ctx.scale 累积 bug — 每次 resize 前重置变换矩阵
 * 2. 使用 requestAnimationFrame 精确控制帧率
 * 3. 不可见时暂停动画（IntersectionObserver）
 */
import React, { useEffect, useRef } from 'react'

interface ParticleFieldProps {
  /** 粒子数量（默认 30） */
  count?: number
  /** 粒子颜色（默认蓝色） */
  color?: string
  /** 连线最大距离（默认 120） */
  linkDistance?: number
  /** 粒子最大速度（默认 0.3） */
  speed?: number
  /** 背景透明度（默认 0.4） */
  opacity?: number
  className?: string
}

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
}

const ParticleField: React.FC<ParticleFieldProps> = ({
  count = 30,
  color = '#3B82F6',
  linkDistance = 120,
  speed = 0.3,
  opacity = 0.4,
  className = '',
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationRef = useRef<number>(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    // 尊重 prefers-reduced-motion — 不启动动画
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReducedMotion) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let particles: Particle[] = []
    let width = 0
    let height = 0
    let isVisible = true

    const resize = () => {
      const parent = canvas.parentElement
      if (!parent) return
      const rect = parent.getBoundingClientRect()
      width = rect.width
      height = rect.height
      const dpr = window.devicePixelRatio || 1
      canvas.width = width * dpr
      canvas.height = height * dpr
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`

      // 修复：先重置变换矩阵，再应用 DPR 缩放，避免累积
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.scale(dpr, dpr)

      // 根据面积调整粒子数量
      const area = width * height
      const adjustedCount = Math.min(count, Math.floor(area / 25000))
      particles = Array.from({ length: adjustedCount }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * speed * 2,
        vy: (Math.random() - 0.5) * speed * 2,
        radius: Math.random() * 1.5 + 0.5,
      }))
    }

    resize()
    const resizeObserver = new ResizeObserver(resize)
    if (canvas.parentElement) {
      resizeObserver.observe(canvas.parentElement)
    }

    // 不可见时暂停动画，节省 CPU/GPU 资源
    const visibilityObserver = new IntersectionObserver(
      ([entry]) => {
        isVisible = entry.isIntersecting
      },
      { threshold: 0 }
    )
    if (canvas.parentElement) {
      visibilityObserver.observe(canvas.parentElement)
    }

    const draw = () => {
      animationRef.current = requestAnimationFrame(draw)

      // 不可见时跳过绘制
      if (!isVisible) return

      ctx.clearRect(0, 0, width, height)

      // 更新和绘制粒子
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i]
        p.x += p.vx
        p.y += p.vy

        // 边界反弹
        if (p.x < 0 || p.x > width) p.vx *= -1
        if (p.y < 0 || p.y > height) p.vy *= -1

        // 绘制粒子
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
        ctx.fillStyle = `${color}${Math.round(opacity * 255).toString(16).padStart(2, '0')}`
        ctx.fill()
      }

      // 绘制连线
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x
          const dy = particles[i].y - particles[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)

          if (dist < linkDistance) {
            const alpha = (1 - dist / linkDistance) * opacity * 0.5
            ctx.beginPath()
            ctx.moveTo(particles[i].x, particles[i].y)
            ctx.lineTo(particles[j].x, particles[j].y)
            ctx.strokeStyle = `${color}${Math.round(alpha * 255).toString(16).padStart(2, '0')}`
            ctx.lineWidth = 0.5
            ctx.stroke()
          }
        }
      }
    }

    draw()

    return () => {
      cancelAnimationFrame(animationRef.current)
      resizeObserver.disconnect()
      visibilityObserver.disconnect()
    }
  }, [count, color, linkDistance, speed, opacity])

  return (
    <canvas
      ref={canvasRef}
      className={`pointer-events-none absolute inset-0 z-0 ${className}`}
      aria-hidden="true"
    />
  )
}

export default React.memo(ParticleField)
