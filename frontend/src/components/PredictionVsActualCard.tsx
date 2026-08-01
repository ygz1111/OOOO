import React, { useState, useEffect, useCallback } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { Activity, TrendingUp, AlertTriangle } from 'lucide-react'
import apiService from '../services/api'
import { PredictionVsActualResponse } from '../types'
import { RefreshButton } from './ui/MicroInteractions'
import { Spinner, ErrorBanner } from './Skeleton'

/**
 * 预测 vs 实际负荷对比卡片
 *
 * 显示最近 N 小时（默认 48h）的预测负荷 vs 真实实际负荷（ISO-NE 数据）
 * 曲线对比 + 误差统计（MAE/MAPE/RMSE + 最新小时误差）。
 *
 * 实际负荷由后台任务每小时从 ISO-NE 同步，故本卡片挂载时加载一次 + 手动刷新，
 * 不参与全局 10s 轮询。
 */
const PredictionVsActualCard: React.FC<{ hours?: number }> = ({ hours = 48 }) => {
  const [data, setData] = useState<PredictionVsActualResponse['data'] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiService.getPredictionVsActual(hours)
      setData(res.data)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载预测对比失败')
    } finally {
      setLoading(false)
    }
  }, [hours])

  useEffect(() => {
    load()
  }, [load])

  const summary = data?.summary
  const pairs = data?.pairs ?? []
  const hasData = pairs.length > 0 && pairs.some(p => p.actual_load_mw != null)

  // 图表数据：格式化时间标签
  const chartData = pairs.map(p => ({
    time: p.target_timestamp.slice(5, 16), // MM-DDTHH:mm
    ...p,
  }))

  const latest = pairs[pairs.length - 1]

  return (
    <div className="card tech-grid-bg">
      <div className="card-header">
        <div className="card-header-icon bg-emerald-500/15">
          <Activity className="w-5 h-5 text-emerald-400" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <h2 className="card-header-title">预测 vs 实际负荷</h2>
          <p className="card-header-subtitle">真实实际负荷（ISO-NE）与模型预测对比</p>
        </div>
        <div className="flex items-center gap-2 ml-auto">
          {summary && (
            <span className="text-[11px] text-emerald-400/80 font-mono">
              数据源: {summary.data_source}
            </span>
          )}
          <RefreshButton onClick={load} isLoading={loading} />
        </div>
      </div>

      {error ? (
        <div className="p-4">
          <ErrorBanner message={error} onRetry={load} />
        </div>
      ) : loading && !data ? (
        <div className="p-8 flex justify-center"><Spinner size="lg" /></div>
      ) : !hasData ? (
        <div className="p-8 text-center text-dark-400">
          <AlertTriangle className="w-10 h-10 mx-auto mb-2 text-warning-500" />
          <p>暂无实际负荷对比数据</p>
          <p className="text-xs mt-1">后台每小时从 ISO-NE 同步真实负荷，数据积累后自动显示</p>
        </div>
      ) : (
        <>
          {/* 误差统计 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 pt-4">
            <div className="bg-dark-700/50 rounded-lg p-3 border border-dark-600">
              <p className="text-dark-400 text-[11px] mb-1">样本数</p>
              <p className="text-lg font-bold text-white">{summary?.count ?? 0} 小时</p>
            </div>
            <div className="bg-dark-700/50 rounded-lg p-3 border border-dark-600">
              <p className="text-dark-400 text-[11px] mb-1">MAE</p>
              <p className="text-lg font-bold text-warning-400">{summary?.mae_mw ?? '--'} MW</p>
            </div>
            <div className="bg-dark-700/50 rounded-lg p-3 border border-dark-600">
              <p className="text-dark-400 text-[11px] mb-1">MAPE</p>
              <p className="text-lg font-bold text-primary-400">
                {summary?.mape != null ? `${summary.mape}%` : '--'}
              </p>
            </div>
            <div className="bg-dark-700/50 rounded-lg p-3 border border-dark-600">
              <p className="text-dark-400 text-[11px] mb-1">RMSE</p>
              <p className="text-lg font-bold text-danger-400">{summary?.rmse_mw ?? '--'} MW</p>
            </div>
          </div>

          {/* 最新小时误差 */}
          {latest && (
            <div className="px-4 pt-3 flex items-center gap-2 text-xs text-dark-300">
              <TrendingUp className="w-3.5 h-3.5 text-cyan-400" />
              <span>
                最近小时（{latest.target_timestamp.slice(5, 16)}）：
                预测 <b className="text-white">{latest.load_forecast_mw} MW</b>，
                实际 <b className="text-emerald-400">{latest.actual_load_mw} MW</b>，
                误差 <b className={latest.absolute_error_mw > 2000 ? 'text-danger-400' : 'text-warning-400'}>
                  {latest.absolute_error_mw} MW
                </b>
                {latest.percentage_error != null && `（${latest.percentage_error}%）`}
              </span>
            </div>
          )}

          {/* 对比曲线 */}
          <div className="px-4 pb-4 pt-3">
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="time" stroke="#64748b" fontSize={10} angle={-30} textAnchor="end" height={50} interval="preserveStartEnd" />
                <YAxis stroke="#64748b" fontSize={11} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
                <Tooltip
                  contentStyle={{ background: '#111827', border: '1px solid #1F2937', borderRadius: '8px' }}
                  labelStyle={{ color: '#cbd5e1' }}
                  formatter={(value: any, name: string) => [
                    `${Number(value).toFixed(1)} MW`,
                    name === 'load_forecast_mw' ? '预测负荷' : name === 'actual_load_mw' ? '实际负荷' : name,
                  ]}
                />
                <Legend wrapperStyle={{ paddingTop: '10px' }} />
                <Line type="monotone" dataKey="load_forecast_mw" name="预测负荷" stroke="#3B82F6" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="actual_load_mw" name="实际负荷" stroke="#10B981" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  )
}

export default PredictionVsActualCard
