import React from 'react'
import { CHART_COLORS } from '../../utils/chartTheme'
import {
  Check, AlertCircle, AlertTriangle,
  ChevronUp, ChevronDown, ChevronsUpDown,
  Gauge as GaugeIcon, Database as DatabaseIcon, BarChart3 as BarChartIcon,
  TrendingUp as TrendingUpIcon, Target as TargetIcon, Activity as ActivityIcon,
  CalendarDays as CalendarDaysIcon,
} from 'lucide-react'
import { formatEasternISO, ET_FULL } from '../../utils/time'

// ========================================
// Tab 定义
// ========================================
export type AnalysisTab = 'overview' | 'history' | 'models' | 'trends' | 'errors' | 'drift' | 'backtest'

export const TABS: { id: AnalysisTab; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: '概览', icon: <GaugeIcon /> },
  { id: 'history', label: '历史记录', icon: <DatabaseIcon /> },
  { id: 'models', label: '模型对比', icon: <BarChartIcon /> },
  { id: 'trends', label: '趋势分析', icon: <TrendingUpIcon /> },
  { id: 'errors', label: '误差分布', icon: <TargetIcon /> },
  { id: 'drift', label: '模型漂移', icon: <ActivityIcon /> },
  { id: 'backtest', label: '日期回测', icon: <CalendarDaysIcon /> },
]

export const MODEL_COLORS = [CHART_COLORS.forecast, CHART_COLORS.replay, CHART_COLORS.solar, CHART_COLORS.actual, CHART_COLORS.error, 'var(--chart-purple)']

export const getModelColor = (model: string, index = 0): string => {
  if (model === 'tf_split_v1') return CHART_COLORS.forecast
  if (model === 'tf_v2') return CHART_COLORS.replay
  if (model === 'tf_pv_v2' || model === 'pv_v2') return CHART_COLORS.solar
  return MODEL_COLORS[index % MODEL_COLORS.length]
}

// ── 排序类型 ──
export type SortDirection = 'asc' | 'desc' | null
export type SortField = string | null

// ── 耗时颜色映射 ──
export const getInferenceColor = (ms: number): string => {
  if (ms < 100) return 'text-success-700'
  if (ms < 500) return 'text-warning-700'
  return 'text-danger-700'
}

// ── 模型标签 ──
export const ModelTag: React.FC<{ model: string }> = ({ model }) => {
  const label = model === 'tf_split_v1'
    ? '当前 TensorFlow 负荷模型（tf_load_split_v1）'
    : model === 'tf_v2'
      ? '归档 TensorFlow 联合模型（tf_v2）'
    : model === 'ensemble'
      ? '归档历史记录（ensemble）'
    : model === 'tf_pv_v2' || model === 'pv_v2'
      ? 'TensorFlow tf_pv_v2'
      : model
  return (
    <span className="model-tag" title={model}>
      {label}
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
    <th scope="col" className={`th-sortable py-2 px-3 font-medium ${alignClass} ${isActive ? 'text-blue-700' : 'text-ink-muted'}`}>
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
    // 后端时间戳为 naive 新英格兰墙钟时间，统一按 ET 显示
    return formatEasternISO(isoStr, ET_FULL)
  } catch {
    return isoStr
  }
}
