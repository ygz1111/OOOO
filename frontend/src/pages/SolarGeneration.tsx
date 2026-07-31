import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { Sun, Battery, Zap, TrendingUp, BarChart3, Lightbulb, Cpu, Activity } from 'lucide-react'
import { useApi } from '../contexts/ApiContext'
import { apiService } from '../services/api'
import type { SolarGenerationResponse, SolarModelInfoResponse } from '../types'
import MetricCard from '../components/MetricCard'
import { MetricCardSkeleton } from '../components/Skeleton'

const SolarGeneration: React.FC = () => {
  const { prediction, weather } = useApi()
  const [solarData, setSolarData] = useState<SolarGenerationResponse | null>(null)
  const [modelInfo, setModelInfo] = useState<SolarModelInfoResponse | null>(null)
  const [solarLoading, setSolarLoading] = useState(false)
  const [solarError, setSolarError] = useState<string | null>(null)

  // 获取光伏 ML 预测数据
  const fetchSolarGeneration = useCallback(async (forceRefresh?: boolean) => {
    setSolarLoading(true)
    setSolarError(null)
    try {
      const [solarRes, modelRes] = await Promise.all([
        apiService.getSolarGeneration(forceRefresh),
        apiService.getSolarModelInfo(),
      ])
      setSolarData(solarRes)
      setModelInfo(modelRes)
    } catch (err) {
      setSolarError(err instanceof Error ? err.message : '光伏预测请求失败')
    } finally {
      setSolarLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSolarGeneration()
  }, [fetchSolarGeneration])

  // 计算光伏发电相关指标 — useMemo 避免每次渲染重计算
  const solarMetrics = useMemo(() => {
    // 优先使用 ML 预测数据
    if (solarData?.hourly_pv_mw?.length) {
      const pvData = solarData.hourly_pv_mw.filter((v) => v > 0)
      const totalGeneration = solarData.total_mwh || pvData.reduce((sum, val) => sum + val, 0)
      const peakGeneration = solarData.peak_mw || Math.max(...solarData.hourly_pv_mw)
      const averageGeneration = pvData.length ? totalGeneration / pvData.length : 0
      const daytimeHours = pvData.length
      const efficiency = solarData.capacity_factor ? solarData.capacity_factor * 100 : 0

      return { totalGeneration, peakGeneration, averageGeneration, efficiency, daytimeHours }
    }

    // 回退到负荷预测中的光伏估算
    if (!prediction?.predictions?.length) {
      return { totalGeneration: 0, peakGeneration: 0, averageGeneration: 0, efficiency: 0, daytimeHours: 0 }
    }

    const pvData = prediction.predictions.map((p) => p.pv_estimation_mw).filter((val) => val > 0)
    const totalGeneration = pvData.reduce((sum, val) => sum + val, 0)
    const peakGeneration = Math.max(...prediction.predictions.map((p) => p.pv_estimation_mw))
    const averageGeneration = pvData.length ? totalGeneration / pvData.length : 0
    const daytimeHours = pvData.length

    const avgRadiation = weather?.regional_average?.shortwave_radiation || 400
    const theoreticalMax = (avgRadiation / 1000) * 500 * 0.8
    const efficiency = theoreticalMax > 0 ? (averageGeneration / theoreticalMax) * 100 : 0

    return { totalGeneration, peakGeneration, averageGeneration, efficiency, daytimeHours }
  }, [solarData, prediction, weather])
  const isMLModel = solarData?.model_type === 'ml_ensemble'

  // 模型信息展示
  const modelEntries = modelInfo?.model_info
    ? Object.entries(modelInfo.model_info)
    : []

  // 训练指标
  const trainingResults = modelInfo?.training_metrics?.results
  const trainingDate = modelInfo?.training_metrics?.training_date

  // 光伏发电估算逻辑展示
  const estimationFactors = [
    {
      factor: '装机容量',
      value: '500 MW',
      description: '新英格兰地区公用事业级光伏总装机容量',
      impact: '直接影响最大发电潜力',
    },
    {
      factor: 'ML 模型集成',
      value: '4 模型',
      description: 'LSTM + BiGRU + TCN + Transformer 加权集成',
      impact: '比物理模型更精准的预测',
    },
    {
      factor: '特征维度',
      value: '21 维',
      description: 'GHI/DNI/DHI + 气象 + 时间编码',
      impact: '多维度捕获光伏发电规律',
    },
    {
      factor: '训练数据',
      value: '6 城市 × 6 年',
      description: 'PVLib 仿真数据 (2019-2024)',
      impact: '覆盖多种天气和季节模式',
    },
  ]

  return (
    <div className="space-y-6 animate-fade-in relative">
      {/* 粒子背景 */}

      {/* 页面标题 */}
      <div className="page-header-centered relative z-10">
        <h1>光伏发电预测</h1>
        <p>
          {isMLModel
            ? '基于深度学习 4 模型集成的光伏发电量预测系统'
            : '基于气象数据和物理模型的光伏发电量实时估算系统'}
        </p>
        <div className="header-decoration" />
      </div>

      {/* ML 模型状态标识 */}
      {isMLModel && (
        <div className="flex items-center justify-center gap-3 relative z-10">
          <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-yellow-500/10 border border-yellow-500/30">
            <Cpu className="w-4 h-4 text-yellow-400" />
            <span className="text-sm text-yellow-300 font-medium">
              ML 集成模型运行中
            </span>
            {solarData?.device && (
              <span className="text-xs text-dark-400">({solarData.device})</span>
            )}
            {solarData?.inference_time_ms && (
              <span className="text-xs text-dark-400">
                · {solarData.inference_time_ms.toFixed(1)}ms
              </span>
            )}
          </div>
          <button
            onClick={() => fetchSolarGeneration(true)}
            disabled={solarLoading}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-dark-700/50 border border-dark-600 hover:border-yellow-500/30 transition-colors text-sm text-dark-300"
          >
            <Activity className="w-4 h-4" />
            刷新预测
          </button>
        </div>
      )}

      {/* 核心指标 */}
      {solarLoading && !solarData ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <MetricCardSkeleton key={i} />
          ))}
        </div>
      ) : (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="stagger-item stagger-1">
        <MetricCard
          title="总发电量"
          value={solarMetrics.totalGeneration.toFixed(0)}
          unit="MW·h"
          icon={<Zap className="w-5 h-5 text-yellow-400" />}
          className="bg-gradient-to-br from-yellow-500/10 to-orange-500/10 border-yellow-500/20"
        />
        </div>

        <div className="stagger-item stagger-2">
        <MetricCard
          title="峰值功率"
          value={solarMetrics.peakGeneration.toFixed(1)}
          unit="MW"
          icon={<TrendingUp className="w-5 h-5 text-success-500" />}
        />
        </div>

        <div className="stagger-item stagger-3">
        <MetricCard
          title="平均功率"
          value={solarMetrics.averageGeneration.toFixed(1)}
          unit="MW"
          icon={<BarChart3 className="w-5 h-5 text-primary-500" />}
        />
        </div>

        <div className="stagger-item stagger-4">
        <MetricCard
          title="容量因子"
          value={solarMetrics.efficiency.toFixed(1)}
          unit="%"
          icon={<Lightbulb className="w-5 h-5 text-load-500" />}
        />
        </div>

        <div className="stagger-item stagger-5">
        <MetricCard
          title="有效发电时长"
          value={solarMetrics.daytimeHours}
          unit="小时"
          icon={<Sun className="w-5 h-5 text-orange-500" />}
        />
        </div>
      </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ML 模型信息 */}
        {isMLModel && modelEntries.length > 0 && (
        <div className="card stagger-item stagger-1">
          <div className="card-header">
            <div className="card-header-icon bg-yellow-500/15">
              <Cpu className="w-5 h-5 text-yellow-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">ML 模型详情</h2>
              <p className="card-header-subtitle">4 模型集成架构与权重</p>
            </div>
          </div>

          <div className="space-y-3">
            {modelEntries.map(([name, info]) => (
              <div
                key={name}
                className="bg-dark-700/50 rounded-lg p-3 border border-dark-600"
              >
                <div className="flex justify-between items-center mb-2">
                  <h3 className="font-medium text-white text-sm">{name}</h3>
                  <span className="text-yellow-400 font-semibold text-sm tabular-nums">
                    权重 {(info.weight * 100).toFixed(2)}%
                  </span>
                </div>
                <div className="text-xs text-dark-400 space-y-1">
                  <div>参数量: {info.num_params.toLocaleString()}</div>
                  {trainingResults?.[name]?.metrics && (
                    <div>
                      R²: {trainingResults[name].metrics.R2?.toFixed(4)}
                      {' · '}
                      MAE: {trainingResults[name].metrics.MAE?.toFixed(1)} kW
                    </div>
                  )}
                </div>
                {/* 权重条 */}
                <div className="mt-2 h-1.5 bg-dark-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-yellow-500 to-orange-500 rounded-full"
                    style={{ width: `${info.weight * 100}%` }}
                  />
                </div>
              </div>
            ))}

            {trainingDate && (
              <div className="text-xs text-dark-400 pt-2 border-t border-dark-600">
                训练时间: {trainingDate}
                {modelInfo?.training_metrics?.gpu_name && ` · ${modelInfo.training_metrics.gpu_name}`}
              </div>
            )}
          </div>
        </div>
        )}

        {/* 影响因素 */}
        <div className={isMLModel ? "card stagger-item stagger-2" : "card stagger-item stagger-1"}>
          <div className="card-header">
            <div className="card-header-icon bg-success-500/15">
              <BarChart3 className="w-5 h-5 text-success-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">系统参数</h2>
              <p className="card-header-subtitle">光伏预测系统关键参数</p>
            </div>
          </div>

          <div className="space-y-3">
            {estimationFactors.map((factor, index) => (
              <div
                key={index}
                className="bg-dark-700/50 rounded-lg p-3 border border-dark-600 hover:border-dark-500 transition-colors"
              >
                <div className="flex justify-between items-start mb-2">
                  <h3 className="font-medium text-white text-sm">{factor.factor}</h3>
                  <span className="text-primary-400 font-semibold text-sm tabular-nums">
                    {factor.value}
                  </span>
                </div>
                <p className="text-xs text-dark-300 mb-1">{factor.description}</p>
                <p className="text-xs text-yellow-300/80">{factor.impact}</p>
              </div>
            ))}
          </div>
        </div>

        {/* 实时数据 */}
        <div className={isMLModel ? "card stagger-item stagger-3" : "card stagger-item stagger-2"}>
          <div className="card-header">
            <div className="card-header-icon bg-yellow-500/15">
              <Sun className="w-5 h-5 text-yellow-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">实时条件</h2>
              <p className="card-header-subtitle">当前光伏发电环境参数</p>
            </div>
          </div>

          <div className="space-y-4">
            {/* 当前辐射 */}
            {weather?.regional_average?.shortwave_radiation && (
              <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-dark-300 text-sm">太阳辐射</span>
                  <Sun className="w-5 h-5 text-yellow-400" aria-hidden="true" />
                </div>
                <div className="text-2xl font-bold text-white tabular-nums">
                  {weather.regional_average.shortwave_radiation.toFixed(0)}
                  <span className="text-sm text-dark-400 ml-1">W/m²</span>
                </div>
                <div className="text-xs text-dark-400 mt-1">影响发电量的关键因素</div>
              </div>
            )}

            {/* 当前温度 */}
            {weather?.regional_average?.temperature_2m && (
              <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-dark-300 text-sm">环境温度</span>
                  <Battery className="w-5 h-5 text-load-400" aria-hidden="true" />
                </div>
                <div className="text-2xl font-bold text-white tabular-nums">
                  {weather.regional_average.temperature_2m.toFixed(1)}
                  <span className="text-sm text-dark-400 ml-1">°C</span>
                </div>
                <div className="text-xs text-dark-400 mt-1">
                  {weather.regional_average.temperature_2m > 25
                    ? '温度较高，效率降低'
                    : '适宜温度，效率最佳'}
                </div>
              </div>
            )}

            {/* 当前云量 */}
            {weather?.regional_average?.cloud_cover && (
              <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-dark-300 text-sm">云层覆盖</span>
                  <BarChart3 className="w-5 h-5 text-purple-400" aria-hidden="true" />
                </div>
                <div className="text-2xl font-bold text-white tabular-nums">
                  {weather.regional_average.cloud_cover.toFixed(0)}
                  <span className="text-sm text-dark-400 ml-1">%</span>
                </div>
                <div className="text-xs text-dark-400 mt-1">
                  {weather.regional_average.cloud_cover > 70
                    ? '多云，发电量下降'
                    : weather.regional_average.cloud_cover > 30
                      ? '少云，影响较小'
                      : '晴朗，发电良好'}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 24小时光伏发电预测表 */}
      {solarData?.hourly_pv_mw && solarData.hourly_pv_mw.length > 0 ? (
        <div className="card">
          <div className="card-header">
            <div className="card-header-icon bg-yellow-500/15">
              <Zap className="w-5 h-5 text-yellow-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">24小时光伏 ML 预测</h2>
              <p className="card-header-subtitle">
                {isMLModel ? '深度学习模型预测的逐小时光伏发电量' : '逐小时光伏发电估算'}
              </p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-dark-600">
                  <th scope="col" className="text-left py-3 px-4 text-dark-300 font-medium">时间</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">光伏发电</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">负荷预测</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">光伏占比</th>
                  <th scope="col" className="text-center py-3 px-4 text-dark-300 font-medium">光照条件</th>
                </tr>
              </thead>
              <tbody>
                {solarData.hourly_pv_mw.map((pv_mw, index) => {
                  const ts = solarData.timestamps?.[index] || ''
                  const hour = ts ? new Date(ts).getHours() : index
                  const isDaytime = hour >= 6 && hour < 18
                  const load_mw = prediction?.predictions?.[index]?.load_forecast_mw || 0
                  const coverage = pv_mw > 0 && load_mw > 0 ? (pv_mw / load_mw) * 100 : 0

                  const peakGen = solarMetrics.peakGeneration || 1
                  const pvRatio = Math.min(pv_mw / peakGen, 1)
                  const baseAlpha = index % 2 === 0 ? 0.22 : 0.38
                  const r = isDaytime ? Math.round(30 + pvRatio * 28) : 30
                  const g = isDaytime ? Math.round(41 + pvRatio * 18) : 41
                  const b = isDaytime ? Math.round(59 - pvRatio * 12) : 59
                  const rowBg = `rgba(${r}, ${g}, ${b}, ${baseAlpha})`

                  return (
                    <tr
                      key={index}
                      className="table-row pv-table-row"
                      style={{ '--row-bg': rowBg } as React.CSSProperties}
                    >
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span className="text-white font-medium tabular-nums">{hour}时</span>
                          <span className="text-dark-400 text-xs tabular-nums">
                            {ts ? new Date(ts).toLocaleTimeString('zh-CN', {
                              hour: '2-digit',
                              minute: '2-digit',
                            }) : ''}
                          </span>
                        </div>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span
                          className={`font-medium tabular-nums ${
                            isDaytime ? 'text-yellow-400' : 'text-dark-400'
                          }`}
                        >
                          {pv_mw.toFixed(1)}
                        </span>
                        <span className="text-dark-400 text-xs ml-1">MW</span>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span className="text-white font-medium tabular-nums">
                          {load_mw.toFixed(0)}
                        </span>
                        <span className="text-dark-400 text-xs ml-1">MW</span>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span
                          className={`font-medium tabular-nums ${
                            coverage > 10 ? 'text-success-400' : 'text-dark-300'
                          }`}
                        >
                          {coverage.toFixed(1)}%
                        </span>
                      </td>
                      <td className="text-center py-3 px-4">
                        <div className="flex items-center justify-center gap-2">
                          {isDaytime ? (
                            <Sun className="w-4 h-4 text-yellow-400" aria-hidden="true" />
                          ) : (
                            <div className="w-4 h-4 bg-dark-500 rounded-full" aria-hidden="true"></div>
                          )}
                          <span className="text-xs text-dark-300">{isDaytime ? '日照' : '夜间'}</span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : prediction?.predictions && (
        <div className="card">
          <div className="card-header">
            <div className="card-header-icon bg-yellow-500/15">
              <Zap className="w-5 h-5 text-yellow-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">24小时光伏发电估算</h2>
              <p className="card-header-subtitle">逐小时光伏发电与负荷对比</p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-dark-600">
                  <th scope="col" className="text-left py-3 px-4 text-dark-300 font-medium">时间</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">光伏发电</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">负荷预测</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">光伏占比</th>
                  <th scope="col" className="text-center py-3 px-4 text-dark-300 font-medium">光照条件</th>
                </tr>
              </thead>
              <tbody>
                {prediction.predictions.map((pred, index) => {
                  const hour = new Date(pred.timestamp).getHours()
                  const isDaytime = hour >= 6 && hour < 18
                  const coverage =
                    pred.pv_estimation_mw > 0
                      ? (pred.pv_estimation_mw / pred.load_forecast_mw) * 100
                      : 0

                  const peakGen = solarMetrics.peakGeneration || 1
                  const pvRatio = Math.min(pred.pv_estimation_mw / peakGen, 1)
                  const baseAlpha = index % 2 === 0 ? 0.22 : 0.38
                  const r = isDaytime ? Math.round(30 + pvRatio * 28) : 30
                  const g = isDaytime ? Math.round(41 + pvRatio * 18) : 41
                  const b = isDaytime ? Math.round(59 - pvRatio * 12) : 59
                  const rowBg = `rgba(${r}, ${g}, ${b}, ${baseAlpha})`

                  return (
                    <tr
                      key={index}
                      className="table-row pv-table-row"
                      style={{ '--row-bg': rowBg } as React.CSSProperties}
                    >
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span className="text-white font-medium tabular-nums">{pred.hour}时</span>
                          <span className="text-dark-400 text-xs tabular-nums">
                            {new Date(pred.timestamp).toLocaleTimeString('zh-CN', {
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </span>
                        </div>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span
                          className={`font-medium tabular-nums ${
                            isDaytime ? 'text-yellow-400' : 'text-dark-400'
                          }`}
                        >
                          {pred.pv_estimation_mw.toFixed(1)}
                        </span>
                        <span className="text-dark-400 text-xs ml-1">MW</span>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span className="text-white font-medium tabular-nums">
                          {pred.load_forecast_mw.toFixed(0)}
                        </span>
                        <span className="text-dark-400 text-xs ml-1">MW</span>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span
                          className={`font-medium tabular-nums ${
                            coverage > 10 ? 'text-success-400' : 'text-dark-300'
                          }`}
                        >
                          {coverage.toFixed(1)}%
                        </span>
                      </td>
                      <td className="text-center py-3 px-4">
                        <div className="flex items-center justify-center gap-2">
                          {isDaytime ? (
                            <Sun className="w-4 h-4 text-yellow-400" aria-hidden="true" />
                          ) : (
                            <div className="w-4 h-4 bg-dark-500 rounded-full" aria-hidden="true"></div>
                          )}
                          <span className="text-xs text-dark-300">{isDaytime ? '日照' : '夜间'}</span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 错误提示 */}
      {solarError && (
        <div className="card border-red-500/30">
          <div className="p-4 text-sm text-red-400">
            ⚠️ 光伏 ML 预测请求失败: {solarError}
            <br />
            <span className="text-dark-400">已回退到负荷预测中的光伏估算数据</span>
          </div>
        </div>
      )}
    </div>
  )
}

export default SolarGeneration
