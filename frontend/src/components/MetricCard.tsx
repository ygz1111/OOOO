import React from 'react'
import { MetricCardProps } from '../types'

const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  unit,
  trendValue,
  icon,
  className = '',
}) => {
  // 格式化数值用于 aria-label，确保屏幕阅读器正确朗读
  const ariaValue = typeof value === 'number' ? value.toLocaleString() : typeof value === 'string' ? value : '数值'

  return (
    <div
      className={`metric-card h-full ${className}`}
      role="region"
      aria-label={`${title}: ${ariaValue}${unit ? ' ' + unit : ''}`}
    >
      <div className="metric-heading">
        <span className="metric-label">{title}</span>
        {icon && <div className="metric-icon" aria-hidden="true">{icon}</div>}
      </div>
      <div className="metric-reading">
        <span className="metric-value tabular-nums">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </span>
        {unit && <span className="metric-unit">{unit}</span>}
      </div>
      {trendValue && <p className="metric-note tabular-nums">{trendValue}</p>}
    </div>
  )
}

// React.memo 优化：纯展示组件，props 稳定时避免不必要的重渲染
export default React.memo(MetricCard)
