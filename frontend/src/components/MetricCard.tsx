import React from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { MetricCardProps } from '../types'

const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  unit,
  trend,
  trendValue,
  icon,
  className = '',
}) => {
  // 格式化数值用于 aria-label，确保屏幕阅读器正确朗读
  const ariaValue = typeof value === 'number' ? value.toLocaleString() : typeof value === 'string' ? value : '数值'
  const getTrendIcon = () => {
    switch (trend) {
      case 'up':
        return <TrendingUp className="w-4 h-4 text-solar-500" aria-hidden="true" />
      case 'down':
        return <TrendingDown className="w-4 h-4 text-danger-500" aria-hidden="true" />
      case 'stable':
        return <Minus className="w-4 h-4 text-dark-400" aria-hidden="true" />
      default:
        return null
    }
  }

  const getTrendColor = () => {
    switch (trend) {
      case 'up':
        return 'text-solar-500'
      case 'down':
        return 'text-danger-500'
      case 'stable':
        return 'text-dark-400'
      default:
        return 'text-dark-400'
    }
  }

  return (
    <div
      className={`metric-card group h-full flex flex-col ${className}`}
      role="region"
      aria-label={`${title}: ${ariaValue}${unit ? ' ' + unit : ''}`}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1 min-w-0">
          <p className="text-dark-400 text-xs uppercase tracking-wider mb-1.5 truncate font-medium">
            {title}
          </p>
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-bold text-white tabular-nums leading-tight">
              {typeof value === 'number' ? value.toLocaleString() : value}
            </span>
            {unit && <span className="text-dark-400 text-sm flex-shrink-0">{unit}</span>}
          </div>
        </div>
        {icon && (
          <div
            className="p-2 bg-primary-500/15 rounded-lg flex-shrink-0 transition-transform duration-200 group-hover:scale-110"
            aria-hidden="true"
          >
            {icon}
          </div>
        )}
      </div>

      {/* 趋势区域 — 始终占位以保证所有卡片高度一致 */}
      <div className="flex items-center justify-between mt-auto pt-3 border-t border-dark-700/60">
        <div className="flex items-center gap-1.5">
          {getTrendIcon()}
          {trendValue && (
            <span className={`text-xs font-medium ${getTrendColor()}`}>{trendValue}</span>
          )}
        </div>
      </div>
    </div>
  )
}

// React.memo 优化：纯展示组件，props 稳定时避免不必要的重渲染
export default React.memo(MetricCard)
