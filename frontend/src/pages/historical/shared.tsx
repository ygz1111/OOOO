import React from 'react'
import { format } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import {
  Check, AlertCircle, AlertTriangle,
  ChevronUp, ChevronDown, ChevronsUpDown,
  Gauge as GaugeIcon, Database as DatabaseIcon, BarChart3 as BarChartIcon,
  TrendingUp as TrendingUpIcon, Target as TargetIcon, Activity as ActivityIcon,
} from 'lucide-react'

// ========================================
// Tab 定义
// ========================================
export type AnalysisTab = 'overview' | 'history' | 'models' | 'trends' | 'errors' | 'drift'

export const TABS: { id: AnalysisTab; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: '概览', icon: <GaugeIcon /> },
  { id: 'history', label: '历史记录', icon: <DatabaseIcon /> },
  { id: 'models', label: '模型对比', icon: <BarChartIcon /> },
  { id: 'trends', label: '趋势分析', icon: <TrendingUpIcon /> },
  { id: 'errors', label: '误差分布', icon: <TargetIcon /> },
  { id: 'drift', label: '模型漂移', icon: <ActivityIcon /> },
]

export const MODEL_COLORS = ['#3B82F6', '#10B981', '#f59e0b', '#a855f7', '#ec4899', '#14b8a6']

// ── 排序类型 ──
export type SortDirection = 'asc' | 'desc' | null
export type SortField = string | null

// ── 耗时颜色映射 ──
export const getInferenceColor = (ms: number): string => {
  if (ms < 100) return 'text-success-400'
  if (ms < 500) return 'text-warning-400'
  return 'text-danger-400'
}

// ── 模型标签 ──
export const ModelTag: React.FC<{ model: string }> = ({ model }) => {
  const isEnsemble = model.toLowerCase().includes('ensemble')
  return (
    <span className={`model-tag ${isEnsemble ? 'model-tag-ensemble' : ''}`}>
      {model}
    </span>
  )
}

// ── 状态徽标 ──
export const StatusBadge: React.FC<{ type: 'success' | 'warning' | 'danger'; label: string }> = ({ type, label }) => {
  const icons = {
    success: <Check className="w-3 h-3" />,
    warning: <AlertCircle className="w-3 h-3" />,
    danger: <AlertTriangle className="w-3 h-3" />,
  }
  return (
    <span className={`badge badge-${type}`}>
      {icons[type]}
      {label}
    </span>
  )
}

// ── 排序表头组件 ──
interface SortableThProps {
  field: string
  currentField: SortField
  currentDir: SortDirection
  onSort: (field: string) => void
  children: React.ReactNode
  align?: 'left' | 'right' | 'center'
}

export const SortableTh: React.FC<SortableThProps> = ({ field, currentField, currentDir, onSort, children, align = 'left' }) => {
  const isActive = currentField === field
  const alignClass = align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'
  return (
    <th scope="col" className={`th-sortable py-2 px-3 font-medium ${alignClass} ${isActive ? 'text-blue-400' : 'text-dark-400'}`}>
      <span
        className="inline-flex items-center gap-1 cursor-pointer"
        onClick={() => onSort(field)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') onSort(field) }}
      >
        {children}
        {isActive ? (
          currentDir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronsUpDown className="w-3 h-3 opacity-40" />
        )}
      </span>
    </th>
  )
}

// ── 工具函数 ──
export const toNum = (val: any): number => {
  if (val === null || val === undefined) return 0
  const n = Number(val)
  return isNaN(n) ? 0 : n
}

export const formatNumber = (val: number | null | undefined, digits = 2): string => {
  if (val === null || val === undefined) return '--'
  const n = Number(val)
  if (isNaN(n)) return '--'
  return n.toFixed(digits)
}

export const formatTime = (isoStr: string): string => {
  try {
    return format(new Date(isoStr), 'MM-dd HH:mm:ss', { locale: zhCN })
  } catch {
    return isoStr
  }
}
