import React, { useState, useMemo } from 'react'
import { useApi } from '../contexts/ApiContext'
import MetricCard from '../components/MetricCard'
import LoadForecastChart from '../components/LoadForecastChart'
import { ErrorBanner, MetricCardSkeleton } from '../components/Skeleton'
import { AnimatedNumber, StaggerReveal } from '../components/ui/Animations'
import { RefreshButton } from '../components/ui/MicroInteractions'
import ParticleField from '../components/ui/ParticleField'
import {
  TrendingUp,
  Zap,
  Sun,
  BarChart3,
  Clock,
  Download,
  Calendar,
  Target,
  Cpu,
  Activity,
  Search,
  ChevronLeft,
  ChevronRight,
  Sun as SunIcon,
  Moon,
} from 'lucide-react'

// ── 右侧面板 Tab 类型 ──
type PanelTab = 'weights' | 'details' | 'status'

const LoadForecast: React.FC = () => {
  const { prediction, isLoading, isInitialLoad, errors, loadPrediction } = useApi()
  const [selectedTimeRange, setSelectedTimeRange] = useState('24h')
  const [forecastMode, setForecastMode] = useState('ensemble')
  const [panelTab, setPanelTab] = useState<PanelTab>('weights')

  // 表格分页 & 搜索
  const [currentPage, setCurrentPage] = useState(1)
  const pageSize = 12
  const [searchQuery, setSearchQuery] = useState('')

  const timeRanges = [
    { value: '24h', label: '24小时' },
    { value: '48h', label: '48小时' },
    { value: '7d', label: '7天' },
  ]

  const forecastModes = [
    { value: 'ensemble', label: '集成预测' },
    { value: 'lstm', label: 'LSTM模型' },
    { value: 'bigru', label: 'BiGRU模型' },
    { value: 'tcn', label: 'TCN模型' },
    { value: 'transformer', label: 'Transformer' },
  ]

  const handleExport = () => {
    if (!prediction?.predictions) return
    const csvContent = [
      ['小时', '时间戳', '负荷预测(MW)', '光伏发电(MW)', '净负荷(MW)'],
      ...prediction.predictions.map((p) => [p.hour, p.timestamp, p.load_forecast_mw, p.pv_estimation_mw, p.net_load_mw]),
    ].map((row) => row.join(',')).join('\n')

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `负荷预测_${new Date().toISOString().split('T')[0]}.csv`
    link.click()
    URL.revokeObjectURL(link.href)
  }

  const metrics = useMemo(() => {
    if (!prediction?.predictions?.length) return null
    const loads = prediction.predictions.map((p) => p.load_forecast_mw)
    const pv = prediction.predictions.map((p) => p.pv_estimation_mw)
    const netLoads = prediction.predictions.map((p) => p.net_load_mw)

    return {
      peakLoad: Math.max(...loads),
      minLoad: Math.min(...loads),
      avgLoad: loads.reduce((sum, load) => sum + load, 0) / loads.length,
      totalPV: pv.reduce((sum, p) => sum + p, 0),
      peakNetLoad: Math.max(...netLoads),
      avgNetLoad: netLoads.reduce((sum, load) => sum + load, 0) / netLoads.length,
    }
  }, [prediction])

  // 表格数据筛选 & 分页
  const filteredPredictions = useMemo(() => {
    if (!prediction?.predictions) return []
    if (!searchQuery.trim()) return prediction.predictions
    const q = searchQuery.toLowerCase()
    return prediction.predictions.filter((p) => {
      const timeStr = new Date(p.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      return String(p.hour).includes(q) || timeStr.includes(q) || String(p.load_forecast_mw).includes(q)
    })
  }, [prediction?.predictions, searchQuery])

  const totalPages = Math.ceil(filteredPredictions.length / pageSize)
  const paginatedPredictions = filteredPredictions.slice((currentPage - 1) * pageSize, currentPage * pageSize)

  const handlePageChange = (dir: 'prev' | 'next') => {
    if (dir === 'prev' && currentPage > 1) setCurrentPage(currentPage - 1)
    if (dir === 'next' && currentPage < totalPages) setCurrentPage(currentPage + 1)
  }

  // 模型权重环形图数据
  const weightData = useMemo(() => {
    if (!prediction?.ensemble_weights) return []
    return Object.entries(prediction.ensemble_weights).map(([name, weight], i) => ({
      name,
      value: weight * 100,
      color: ['#3B82F6', '#10B981', '#F59E0B', '#A855F7'][i % 4],
    }))
  }, [prediction?.ensemble_weights])

  return (
    <div className="space-y-6 page-transition relative">
      {/* 粒子背景 */}
      <ParticleField count={30} opacity={0.25} />

      {/* 页面标题 — 居中 */}
      <div className="page-header-centered relative z-10">
        <h1>负荷预测分析</h1>
        <p>基于深度学习的24小时智能电网负荷预测</p>
        <div className="header-decoration" />
      </div>

      <div className="flex items-center justify-center gap-3 flex-wrap relative z-10">
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-dark-400" aria-hidden="true" />
            <select value={selectedTimeRange} onChange={(e) => setSelectedTimeRange(e.target.value)} className="select-dark" aria-label="选择时间范围">
              {timeRanges.map((range) => <option key={range.value} value={range.value}>{range.label}</option>)}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <Target className="w-4 h-4 text-dark-400" aria-hidden="true" />
            <select value={forecastMode} onChange={(e) => setForecastMode(e.target.value)} className="select-dark" aria-label="选择预测模型">
              {forecastModes.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
            </select>
          </div>

          <RefreshButton onClick={() => loadPrediction(true)} isLoading={isLoading.prediction} className="btn-primary" />

          <button onClick={handleExport} disabled={!prediction} className="btn btn-success" aria-label="导出CSV数据">
            <Download className="w-4 h-4" aria-hidden="true" />
            <span className="hidden sm:inline">导出数据</span>
          </button>
      </div>

      {/* 预测指标卡片 — 合并为4个，两行布局 */}
      {isInitialLoad.prediction && isLoading.prediction ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)}
        </div>
      ) : metrics ? (
        <StaggerReveal className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4" stagger={80}>
          {/* 卡片1: 峰值负荷 & 峰值净负荷 合并对比 */}
          <div className="hover-lift">
            <MetricCard
              title="峰值负荷 / 净负荷"
              value={<AnimatedNumber value={metrics.peakLoad} decimals={1} />}
              unit="MW"
              icon={<TrendingUp className="w-5 h-5 text-primary-400" />}
              trendValue={`净负荷峰值 ${metrics.peakNetLoad.toFixed(0)}`}
              className="bg-gradient-to-br from-primary-500/10 to-blue-500/10 border-primary-500/20"
            />
          </div>

          {/* 卡片2: 最低负荷 */}
          <div className="hover-lift">
            <MetricCard
              title="最低负荷"
              value={<AnimatedNumber value={metrics.minLoad} decimals={1} />}
              unit="MW"
              icon={<BarChart3 className="w-5 h-5 text-load-400" />}
              className="bg-gradient-to-br from-load-500/10 to-load-600/10 border-load-500/20"
            />
          </div>

          {/* 卡片3: 平均负荷 & 平均净负荷 合并 */}
          <div className="hover-lift">
            <MetricCard
              title="平均负荷 / 净负荷"
              value={<AnimatedNumber value={metrics.avgLoad} decimals={1} />}
              unit="MW"
              icon={<Zap className="w-5 h-5 text-success-400" />}
              trendValue={`净负荷均值 ${metrics.avgNetLoad.toFixed(0)}`}
              className="bg-gradient-to-br from-success-500/10 to-green-500/10 border-success-500/20"
            />
          </div>

          {/* 卡片4: 总光伏发电 */}
          <div className="hover-lift">
            <MetricCard
              title="总光伏发电"
              value={<AnimatedNumber value={metrics.totalPV} decimals={0} />}
              unit="MW·h"
              icon={<Sun className="w-5 h-5 text-solar-400" />}
              className="bg-gradient-to-br from-solar-500/10 to-solar-600/10 border-solar-500/20"
            />
          </div>
        </StaggerReveal>
      ) : null}

      {/* 主图表 + 右侧面板 — 7:3 布局 */}
      <div className="grid grid-cols-1 xl:grid-cols-10 gap-6">
        {/* 预测图表 — 占7列 */}
        <div className="xl:col-span-7">
          <div className="card h-full tech-grid-bg">
            <div className="card-header">
              <div className="card-header-icon bg-primary-500/15">
                <TrendingUp className="w-5 h-5 text-primary-400 icon-zoom" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h2 className="card-header-title">负荷预测趋势</h2>
                <p className="card-header-subtitle">多模型集成预测结果对比</p>
              </div>
            </div>

            <LoadForecastChart
              data={prediction}
              isLoading={isInitialLoad.prediction && isLoading.prediction}
              isRefreshing={isLoading.prediction && !isInitialLoad.prediction}
              height={450}
            />

            {errors.prediction && (
              <div className="mt-4">
                <ErrorBanner message={errors.prediction} />
              </div>
            )}
          </div>
        </div>

        {/* 右侧信息面板 — 占3列，Tab 切换 */}
        <div className="xl:col-span-3">
          <div className="card h-full tech-grid-bg">
            {/* Tab 切换栏 */}
            <div className="tab-bar-enhanced mb-4">
              <button
                onClick={() => setPanelTab('weights')}
                className={`tab-item-enhanced ${panelTab === 'weights' ? 'tab-item-active' : ''}`}
              >
                <Cpu className="w-4 h-4" />
                <span className="hidden sm:inline">模型权重</span>
                {panelTab === 'weights' && <span className="tab-indicator-glow" />}
              </button>
              <button
                onClick={() => setPanelTab('details')}
                className={`tab-item-enhanced ${panelTab === 'details' ? 'tab-item-active' : ''}`}
              >
                <BarChart3 className="w-4 h-4" />
                <span className="hidden sm:inline">预测详情</span>
                {panelTab === 'details' && <span className="tab-indicator-glow" />}
              </button>
              <button
                onClick={() => setPanelTab('status')}
                className={`tab-item-enhanced ${panelTab === 'status' ? 'tab-item-active' : ''}`}
              >
                <Activity className="w-4 h-4" />
                <span className="hidden sm:inline">实时状态</span>
                {panelTab === 'status' && <span className="tab-indicator-glow" />}
              </button>
            </div>

            {/* Tab 内容 */}
            <div className="animate-fade-in">
              {panelTab === 'weights' && (
                <div className="space-y-4">
                  {/* 环形图 */}
                  {weightData.length > 0 && (
                    <div className="flex justify-center mb-4">
                      <div className="relative w-32 h-32">
                        <svg width="128" height="128" className="-rotate-90">
                          {(() => {
                            const total = weightData.reduce((sum, w) => sum + w.value, 0)
                            let offset = 0
                            const radius = 48
                            const circumference = 2 * Math.PI * radius
                            return weightData.map((w, i) => {
                              const pct = w.value / total
                              const dash = circumference * pct
                              const el = (
                                <circle
                                  key={i}
                                  cx="64" cy="64" r={radius}
                                  fill="none"
                                  stroke={w.color}
                                  strokeWidth="10"
                                  strokeDasharray={`${dash} ${circumference - dash}`}
                                  strokeDashoffset={-offset}
                                  style={{ transition: 'stroke-dashoffset 600ms ease-out' }}
                                />
                              )
                              offset += dash
                              return el
                            })
                          })()}
                        </svg>
                        <div className="absolute inset-0 flex flex-col items-center justify-center">
                          <span className="text-xs text-dark-400">集成</span>
                          <span className="text-lg font-bold text-white">100%</span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* 模型权重水平进度条 */}
                  {prediction?.ensemble_weights ? (
                    <div className="space-y-3">
                      {Object.entries(prediction.ensemble_weights).map(([model, weight], i) => (
                        <div key={model} className="space-y-1.5">
                          <div className="flex justify-between text-sm">
                            <span className="text-dark-300">{model}</span>
                            <span className="text-white font-medium tabular-nums">
                              <AnimatedNumber value={weight * 100} decimals={0} suffix="%" />
                            </span>
                          </div>
                          <div className="progress-bar-enhanced" style={{ height: '6px' }}>
                            <div
                              className="progress-bar-fill transition-all duration-500"
                              style={{
                                width: `${weight * 100}%`,
                                background: `linear-gradient(90deg, ${weightData[i]?.color || '#3B82F6'}, ${weightData[i]?.color || '#3B82F6'}dd)`,
                              }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-dark-400 text-sm text-center py-8">暂无模型权重信息</p>
                  )}

                  {/* 推理时间移至此处 */}
                  {prediction && (
                    <div className="pt-3 border-t border-dark-700">
                      <div className="flex justify-between items-center">
                        <span className="text-dark-400 text-sm flex items-center gap-2">
                          <Clock className="w-4 h-4" />
                          推理时间
                        </span>
                        <span className="text-white font-mono font-medium tabular-nums">
                          {prediction.inference_time_ms}ms
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {panelTab === 'details' && (
                <div className="space-y-3">
                  {prediction ? (
                    <>
                      <div className="flex justify-between py-2 px-3 bg-dark-700/30 rounded-lg">
                        <span className="text-dark-400 text-sm">数据源</span>
                        <span className="text-white text-sm font-medium">{prediction.data_source}</span>
                      </div>
                      <div className="flex justify-between py-2 px-3 bg-dark-700/30 rounded-lg">
                        <span className="text-dark-400 text-sm">预测时间</span>
                        <span className="text-white text-sm font-medium tabular-nums">
                          {new Date(prediction.timestamp).toLocaleString('zh-CN')}
                        </span>
                      </div>
                      <div className="flex justify-between py-2 px-3 bg-dark-700/30 rounded-lg">
                        <span className="text-dark-400 text-sm">预测范围</span>
                        <span className="text-white text-sm font-medium tabular-nums">
                          {prediction.predictions?.length || 0} 小时
                        </span>
                      </div>
                      <div className="flex justify-between py-2 px-3 bg-dark-700/30 rounded-lg">
                        <span className="text-dark-400 text-sm">模型数量</span>
                        <span className="text-white text-sm font-medium tabular-nums">
                          {prediction.model_info?.length || 0} 个
                        </span>
                      </div>
                      <div className="flex justify-between py-2 px-3 bg-dark-700/30 rounded-lg">
                        <span className="text-dark-400 text-sm">推理时间</span>
                        <span className="text-primary-400 text-sm font-mono font-medium tabular-nums">
                          {prediction.inference_time_ms}ms
                        </span>
                      </div>
                    </>
                  ) : (
                    <p className="text-dark-400 text-sm text-center py-8">等待预测数据...</p>
                  )}
                </div>
              )}

              {panelTab === 'status' && (
                <div className="space-y-3 text-sm">
                  <div className="flex justify-between py-2 px-3 bg-dark-700/30 rounded-lg">
                    <span className="text-dark-400">预测状态</span>
                    <span className={`font-medium ${isLoading.prediction ? 'text-warning-400' : prediction ? 'text-success-400' : 'text-warning-400'}`}>
                      {isLoading.prediction ? '计算中...' : prediction ? '已完成' : '等待中'}
                    </span>
                  </div>
                  <div className="flex justify-between py-2 px-3 bg-dark-700/30 rounded-lg">
                    <span className="text-dark-400">API连接</span>
                    <span className={`font-medium ${!errors.prediction ? 'text-success-400' : 'text-danger-400'}`}>
                      {!errors.prediction ? '正常' : '异常'}
                    </span>
                  </div>
                  <div className="flex justify-between py-2 px-3 bg-dark-700/30 rounded-lg">
                    <span className="text-dark-400">更新频率</span>
                    <span className="text-white font-medium tabular-nums">5分钟</span>
                  </div>
                  <div className="flex justify-between py-2 px-3 bg-dark-700/30 rounded-lg">
                    <span className="text-dark-400">推理设备</span>
                    <span className="text-white font-medium">--</span>
                  </div>
                  <div className="flex justify-between py-2 px-3 bg-dark-700/30 rounded-lg">
                    <span className="text-dark-400">最后更新</span>
                    <span className="text-white font-mono text-xs tabular-nums">
                      {new Date().toLocaleTimeString('zh-CN')}
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 预测数据表格 — 分页 + 搜索 + 固定表头 + 时段徽标 */}
      {prediction?.predictions && (
        <div className="card tech-grid-bg">
          <div className="card-header">
            <div className="card-header-icon bg-primary-500/15">
              <BarChart3 className="w-5 h-5 text-primary-400 icon-zoom" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h3 className="card-header-title">详细预测数据</h3>
              <p className="card-header-subtitle">逐小时预测与发电估算</p>
            </div>

            {/* 搜索框 */}
            <div className="relative ml-auto">
              <Search className="w-4 h-4 text-dark-400 absolute left-3 top-1/2 -translate-y-1/2" aria-hidden="true" />
              <input
                type="text"
                placeholder="搜索时间/数值..."
                value={searchQuery}
                onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1) }}
                className="select-dark !pl-9 !py-1.5 w-48"
                aria-label="搜索预测数据"
              />
            </div>
          </div>

          <div className="overflow-x-auto rounded-lg max-h-[500px] overflow-y-auto">
            <table className="w-full text-sm table-zebra">
              <thead className="sticky top-0 z-10 bg-dark-800/95">
                <tr className="text-dark-400 border-b border-dark-600">
                  <th scope="col" className="text-left py-3 px-4 font-medium">时间</th>
                  <th scope="col" className="text-right py-3 px-4 font-medium">负荷预测</th>
                  <th scope="col" className="text-right py-3 px-4 font-medium">光伏发电</th>
                  <th scope="col" className="text-right py-3 px-4 font-medium">净负荷</th>
                  <th scope="col" className="text-center py-3 px-4 font-medium">时段</th>
                </tr>
              </thead>
              <tbody>
                {paginatedPredictions.map((pred, index) => {
                  const hour = new Date(pred.timestamp).getHours()
                  const isDaytime = hour >= 6 && hour < 18
                  return (
                    <tr key={index} className="border-b border-dark-700">
                      <td className="py-2.5 px-4">
                        <div className="flex items-center gap-2">
                          <span className="text-white font-medium tabular-nums">{pred.hour}时</span>
                          <span className="text-dark-400 text-xs tabular-nums">
                            {new Date(pred.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                      </td>
                      <td className="text-right py-2.5 px-4">
                        <span className="text-primary-300 font-medium tabular-nums">
                          {pred.load_forecast_mw.toLocaleString()}
                        </span>
                        <span className="text-dark-400 text-xs ml-1">MW</span>
                      </td>
                      <td className="text-right py-2.5 px-4">
                        <span className={`font-medium tabular-nums ${isDaytime ? 'text-success-400' : 'text-dark-500'}`}>
                          {pred.pv_estimation_mw.toLocaleString()}
                        </span>
                        <span className="text-dark-400 text-xs ml-1">MW</span>
                      </td>
                      <td className="text-right py-2.5 px-4">
                        <span className="text-primary-300 font-medium tabular-nums">
                          {pred.net_load_mw.toLocaleString()}
                        </span>
                        <span className="text-dark-400 text-xs ml-1">MW</span>
                      </td>
                      <td className="text-center py-2.5 px-4">
                        <span className={`badge ${isDaytime ? 'badge-warning' : 'badge-success'}`}>
                          {isDaytime ? <SunIcon className="w-3 h-3" /> : <Moon className="w-3 h-3" />}
                          {isDaytime ? '日间' : '夜间'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* 分页控制 */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4 pt-4 border-t border-dark-700">
              <span className="text-sm text-dark-400">
                第 {currentPage} / {totalPages} 页 · 共 {filteredPredictions.length} 条
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handlePageChange('prev')}
                  disabled={currentPage <= 1}
                  className="btn btn-ghost !py-1.5 !px-3 disabled:opacity-30 disabled:cursor-not-allowed"
                  aria-label="上一页"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                {Array.from({ length: Math.min(totalPages, 5) }).map((_, i) => {
                  const pageNum = i + 1
                  return (
                    <button
                      key={pageNum}
                      onClick={() => setCurrentPage(pageNum)}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                        currentPage === pageNum
                          ? 'bg-primary-500/20 text-primary-300 border border-primary-500/30'
                          : 'text-dark-400 hover:bg-dark-700/50'
                      }`}
                    >
                      {pageNum}
                    </button>
                  )
                })}
                <button
                  onClick={() => handlePageChange('next')}
                  disabled={currentPage >= totalPages}
                  className="btn btn-ghost !py-1.5 !px-3 disabled:opacity-30 disabled:cursor-not-allowed"
                  aria-label="下一页"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default LoadForecast
