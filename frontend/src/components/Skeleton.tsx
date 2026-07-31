import React from 'react'

// 骨架屏 - 卡片
export const CardSkeleton: React.FC<{ lines?: number }> = ({ lines = 3 }) => (
  <div className="card animate-fade-in">
    <div className="skeleton h-6 w-48 mb-4"></div>
    {Array.from({ length: lines }).map((_, i) => (
      <div key={i} className="flex items-center gap-4 mb-3">
        <div className="skeleton h-4 w-24"></div>
        <div className="skeleton h-4 flex-1"></div>
      </div>
    ))}
  </div>
)

// 骨架屏 - 指标卡片
export const MetricCardSkeleton: React.FC = () => (
  <div className="metric-card animate-fade-in">
    <div className="flex items-start justify-between mb-2">
      <div className="flex-1">
        <div className="skeleton h-3 w-20 mb-2"></div>
        <div className="skeleton h-8 w-32"></div>
      </div>
      <div className="skeleton h-10 w-10 rounded-lg"></div>
    </div>
    <div className="mt-3 pt-3 border-t border-dark-700/60">
      <div className="skeleton h-3 w-28"></div>
    </div>
  </div>
)

// 骨架屏 - 图表
export const ChartSkeleton: React.FC<{ height?: number }> = ({ height = 300 }) => (
  <div className="flex items-center justify-center w-full animate-fade-in" style={{ height }}>
    <div className="w-full px-8">
      <div className="flex items-end justify-between gap-2" style={{ height: height - 40 }}>
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            className="skeleton flex-1 rounded-t"
            style={{ height: `${30 + Math.sin(i) * 20 + 40}%` }}
          ></div>
        ))}
      </div>
    </div>
  </div>
)

// 骨架屏 - 表格行
export const TableSkeleton: React.FC<{ rows?: number; cols?: number }> = ({ rows = 5, cols = 5 }) => (
  <div className="animate-fade-in">
    <div className="flex gap-4 mb-4 pb-2 border-b border-dark-600">
      {Array.from({ length: cols }).map((_, i) => (
        <div key={i} className="skeleton h-4 flex-1"></div>
      ))}
    </div>
    {Array.from({ length: rows }).map((_, r) => (
      <div key={r} className="flex gap-4 py-3 border-b border-dark-700/60">
        {Array.from({ length: cols }).map((_, c) => (
          <div key={c} className="skeleton h-4 flex-1"></div>
        ))}
      </div>
    ))}
  </div>
)

// 通用加载旋转器
export const Spinner: React.FC<{ size?: 'sm' | 'md' | 'lg'; className?: string }> = ({
  size = 'md',
  className = '',
}) => {
  const sizeClass = size === 'lg' ? 'h-12 w-12' : size === 'sm' ? 'h-6 w-6' : 'h-8 w-8'
  return (
    <div className={`flex items-center justify-center py-8 ${className}`}>
      <div
        className={`animate-spin rounded-full border-2 border-dark-600 border-t-primary-500 ${sizeClass}`}
        role="status"
        aria-label="加载中"
      ></div>
    </div>
  )
}

// 空状态
export const EmptyState: React.FC<{
  icon: React.ReactNode
  title: string
  description?: string
}> = ({ icon, title, description }) => (
  <div className="text-center py-12 text-dark-400 animate-fade-in">
    <div className="flex justify-center mb-3 opacity-40">{icon}</div>
    <p className="text-base font-medium">{title}</p>
    {description && <p className="text-sm mt-2 text-dark-500">{description}</p>}
  </div>
)

// 错误提示
export const ErrorBanner: React.FC<{ message: string; onRetry?: () => void }> = ({
  message,
  onRetry,
}) => (
  <div
    className="p-4 bg-danger-500/10 border border-danger-500/30 rounded-xl flex items-center gap-3 animate-fade-in backdrop-blur-sm"
    role="alert"
  >
    <svg
      className="w-5 h-5 text-danger-400 flex-shrink-0"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 9v2m0 4h.01M5.07 19h13.86c1.54 0 2.5-1.67 1.73-3L13.73 4a2 2 0 00-3.46 0L3.34 16c-.77 1.33.19 3 1.73 3z"
      />
    </svg>
    <span className="text-danger-300 text-sm flex-1">{message}</span>
    {onRetry && (
      <button
        onClick={onRetry}
        className="text-xs px-3 py-1.5 bg-danger-500/20 hover:bg-danger-500/30 text-danger-300 rounded-lg transition-colors cursor-pointer min-h-[36px] flex items-center"
      >
        重试
      </button>
    )}
  </div>
)
