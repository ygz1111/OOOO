/**
 * 赛博朋克背景效果组件
 * - 粒子连线网络（青色/品红色双色）
 * - 脉冲波纹扩散
 * - 移动扫描线
 *
 * 性能优化：
 * 1. Canvas + requestAnimationFrame，不可见时暂停
 * 2. 尊重 prefers-reduced-motion
 * 3. 粒子数自适应屏幕面积
 */
import React, { useEffect, useRef } from 'react'

interface CyberBackgroundProps {
  /** 粒子数量倍率（默认 1.0） */
  intensity?: number
  /** 主色调 */
  primaryColor?: string
  /** 辅色调 */
  accentColor?: string
}

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  color: string
  pulsePhase: number
}

interface Pulse {
  x: number
  y: number
  radius: number
  maxRadius: number
  opacity: number
  color: string
}

const CyberBackground: React.FC<CyberBackgroundProps> = ({
  intensity = 1.0,
  primaryColor = '#00F0FF',
  accentColor = '#FF2D95',
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationRef = useRef<number>(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReducedMotion) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let particles: Particle[] = []
    let pulses: Pulse[] = []
    let width = 0
    let height = 0
    let isVisible = true
    let lastPulseTime = 0
    let scanlineY = 0

    const resize = () => {
      const parent = canvas.parentElement
      if (!parent) return
      const rect = parent.getBoundingClientRect()
      width = rect.width
      height = rect.height
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = width * dpr
      canvas.height = height * dpr
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`

      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.scale(dpr, dpr)

      const area = width * height
      const baseCount = Math.min(50, Math.floor(area / 18000) * intensity)
      const adjustedCount = Math.max(15, Math.floor(baseCount))

      particles = Array.from({ length: adjustedCount }, (_, i) => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        radius: Math.random() * 1.5 + 0.5,
        color: i % 4 === 0 ? accentColor : primaryColor,
        pulsePhase: Math.random() * Math.PI * 2,
      }))
    }

    resize()
    const resizeObserver = new ResizeObserver(resize)
    if (canvas.parentElement) {
      resizeObserver.observe(canvas.parentElement)
    }

    const visibilityObserver = new IntersectionObserver(
      ([entry]) => { isVisible = entry.isIntersecting },
      { threshold: 0 }
    )
    if (canvas.parentElement) {
      visibilityObserver.observe(canvas.parentElement)
    }

    const hexToRgb = (hex: string) => {
      const r = parseInt(hex.slice(1, 3), 16)
      const g = parseInt(hex.slice(3, 5), 16)
      const b = parseInt(hex.slice(5, 7), 16)
      return `${r}, ${g}, ${b}`
    }

    const primaryRgb = hexToRgb(primaryColor)
    const accentRgb = hexToRgb(accentColor)

    const draw = (timestamp?: number) => {
      animationRef.current = requestAnimationFrame(draw)
      if (!isVisible) return

      ctx.clearRect(0, 0, width, height)

      // 更新和绘制粒子
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i]
        p.x += p.vx
        p.y += p.vy
        p.pulsePhase += 0.02

        if (p.x < 0 || p.x > width) p.vx *= -1
        if (p.y < 0 || p.y > height) p.vy *= -1

        const pulseScale = 0.7 + Math.sin(p.pulsePhase) * 0.3
        const rgb = p.color === accentColor ? accentRgb : primaryRgb

        ctx.beginPath()
        ctx.arc(p.x, p.y, p.radius * pulseScale, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${rgb}, ${0.5 * pulseScale})`
        ctx.fill()

        // 粒子辉光
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.radius * 3, 0, Math.PI * 2)
        const gradient = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.radius * 3)
        gradient.addColorStop(0, `rgba(${rgb}, 0.08)`)
        gradient.addColorStop(1, `rgba(${rgb}, 0)`)
        ctx.fillStyle = gradient
        ctx.fill()
      }

      // 绘制粒子连线
      const linkDist = 130
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x
          const dy = particles[i].y - particles[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)

          if (dist < linkDist) {
            const alpha = (1 - dist / linkDist) * 0.15
            const useAccent = particles[i].color === accentColor || particles[j].color === accentColor
            const rgb = useAccent ? accentRgb : primaryRgb
            ctx.beginPath()
            ctx.moveTo(particles[i].x, particles[i].y)
            ctx.lineTo(particles[j].x, particles[j].y)
            ctx.strokeStyle = `rgba(${rgb}, ${alpha})`
            ctx.lineWidth = 0.5
            ctx.stroke()
          }
        }
      }

      // 周期性脉冲波纹
      const now = timestamp ?? performance.now()
      if (now - lastPulseTime > 3000) {
        lastPulseTime = now
        const px = Math.random() * width
        const py = Math.random() * height
        const useAccent = Math.random() > 0.5
        pulses.push({
          x: px,
          y: py,
          radius: 0,
          maxRadius: 150 + Math.random() * 100,
          opacity: 0.4,
          color: useAccent ? accentRgb : primaryRgb,
        })
      }

      // 更新和绘制脉冲
      pulses = pulses.filter((pulse) => {
        pulse.radius += 1.5
        pulse.opacity = Math.max(0, 0.4 * (1 - pulse.radius / pulse.maxRadius))

        if (pulse.radius < pulse.maxRadius) {
          ctx.beginPath()
          ctx.arc(pulse.x, pulse.y, pulse.radius, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${pulse.color}, ${pulse.opacity})`
          ctx.lineWidth = 1
          ctx.stroke()

          // 内圈
          ctx.beginPath()
          ctx.arc(pulse.x, pulse.y, pulse.radius * 0.6, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${pulse.color}, ${pulse.opacity * 0.5})`
          ctx.lineWidth = 0.5
          ctx.stroke()

          return true
        }
        return false
      })

      // 移动扫描线
      scanlineY += 0.5
      if (scanlineY > height) scanlineY = -20

      const scanGradient = ctx.createLinearGradient(0, scanlineY - 2, 0, scanlineY + 2)
      scanGradient.addColorStop(0, `rgba(${primaryRgb}, 0)`)
      scanGradient.addColorStop(0.5, `rgba(${primaryRgb}, 0.06)`)
      scanGradient.addColorStop(1, `rgba(${primaryRgb}, 0)`)
      ctx.fillStyle = scanGradient
      ctx.fillRect(0, scanlineY - 2, width, 4)
    }

    draw()

    return () => {
      cancelAnimationFrame(animationRef.current)
      resizeObserver.disconnect()
      visibilityObserver.disconnect()
    }
  }, [intensity, primaryColor, accentColor])

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 z-0"
      aria-hidden="true"
    />
  )
}

export default React.memo(CyberBackground)
