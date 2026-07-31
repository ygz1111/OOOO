import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { Wind, Zap, TrendingUp, Calculator, BarChart3, Gauge, Activity } from 'lucide-react'
import { useApi } from '../contexts/ApiContext'
import MetricCard from '../components/MetricCard'
import { MetricCardSkeleton } from '../components/Skeleton'
import { RefreshButton } from '../components/ui/MicroInteractions'
import apiService from '../services/api'
import type { WindGenerationResponse, PowerCurveResponse } from '../types'

// 风电API响应类型
const WindGeneration: React.FC = () => {
  const { prediction, weather, isInitialLoad } = useApi()
  const [windData, setWindData] = useState<WindGenerationResponse | null>(null)
  const [powerCurve, setPowerCurve] = useState<PowerCurveResponse | null>(null)
  const [windLoading, setWindLoading] = useState(false)
  const [curveLoading, setCurveLoading] = useState(false)
  const [windError, setWindError] = useState<string | null>(null)

  // 获取风电预测数据
  const fetchWindData = useCallback(async () => {
    setWindLoading(true)
    setWindError(null)
    try {
      const data = await apiService.getWindGeneration()
      setWindData(data)
    } catch (err) {
      setWindError(err instanceof Error ? err.message : '获取风电数据失败')
    } finally {
      setWindLoading(false)
    }
  }, [])

  // 获取功率曲线
  const fetchPowerCurve = useCallback(async () => {
    setCurveLoading(true)
    try {
      const data = await apiService.getWindPowerCurve()
      setPowerCurve(data)
    } catch (err) {
      console.error('获取功率曲线失败:', err)
    } finally {
      setCurveLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchWindData()
    fetchPowerCurve()
  }, [fetchWindData, fetchPowerCurve])

  // 从预测数据中获取风电指标 — useMemo 避免每次渲染重计算
  const windMetrics = useMemo(() => {
    if (windData) {
      const gen = windData.hourly_generation_mw
      const speeds = windData.hourly_wind_speed_hub
      const totalGen = gen.reduce((sum, v) => sum + v, 0)
      const peakGen = Math.max(...gen)
      const avgGen = totalGen / 24
      const avgSpeed = speeds.reduce((sum, v) => sum + v, 0) / 24
      const activeHours = gen.filter((v) => v > 1).length

      return {
        totalGeneration: totalGen,
        peakGeneration: peakGen,
        averageGeneration: avgGen,
        averageWindSpeed: avgSpeed,
        capacityFactor: windData.capacity_factor * 100,
        activeHours,
      }
    }

    // 从负荷预测中获取风电数据
    if (!prediction?.predictions?.length) {
      return {
        totalGeneration: 0,
        peakGeneration: 0,
        averageGeneration: 0,
        averageWindSpeed: 0,
        capacityFactor: 0,
        activeHours: 0,
      }
    }

    const windDataArr = prediction.predictions.map((p) => p.wind_estimation_mw || 0)
    const totalGeneration = windDataArr.reduce((sum, val) => sum + val, 0)
    const peakGeneration = Math.max(...windDataArr)
    const averageGeneration = totalGeneration / 24
    const activeHours = windDataArr.filter((v) => v > 1).length
    const avgWindSpeed = weather?.regional_average?.wind_speed_10m || 0
    const capacityFactor = (totalGeneration / (1500 * 24)) * 100

    return {
      totalGeneration,
      peakGeneration,
      averageGeneration,
      averageWindSpeed: avgWindSpeed,
      capacityFactor,
      activeHours,
    }
  }, [windData, prediction, weather])

  // 风机参数
  const turbineParams = powerCurve
    ? [
        { factor: '风机类型', value: powerCurve.turbine_type, description: '新英格兰地区陆上风力发电机组', impact: '决定功率曲线特性' },
        { factor: '额定功率', value: `${(powerCurve.rated_power_kw / 1000).toFixed(1)} MW`, description: `单台风机额定输出功率`, impact: `共 ${powerCurve.n_turbines} 台` },
        { factor: '风轮直径', value: `${powerCurve.rotor_diameter_m} m`, description: '风轮扫掠面积决定捕风能力', impact: `扫掠面积 ${Math.round(Math.PI * (powerCurve.rotor_diameter_m / 2) ** 2)} m²` },
        { factor: '轮毂高度', value: `${powerCurve.hub_height_m} m`, description: '风速随高度增加而增大', impact: `风切变指数 α=${powerCurve.wind_shear_alpha}` },
        { factor: '切入风速', value: `${powerCurve.cut_in_speed} m/s`, description: '开始发电的最低风速', impact: '低于此风速无输出' },
        { factor: '额定风速', value: `${powerCurve.rated_speed} m/s`, description: '达到额定功率的风速', impact: '风速超过此值满功率运行' },
        { factor: '切出风速', value: `${powerCurve.cut_out_speed} m/s`, description: '安全停机的最高风速', impact: '高于此风速自动停机' },
        { factor: '功率系数 Cp', value: powerCurve.power_coefficient.toFixed(2), description: '贝兹极限 0.593 的利用率', impact: `效率 ${((powerCurve.power_coefficient / 0.593) * 100).toFixed(0)}%` },
        { factor: '尾流损失', value: `${(powerCurve.wake_loss * 100).toFixed(0)}%`, description: '风机间尾流效应造成的损失', impact: '多排布置时增大' },
        { factor: '可用率', value: `${(powerCurve.availability * 100).toFixed(0)}%`, description: '考虑运维停机后的可用率', impact: '实际可用风机比例' },
      ]
    : [
        { factor: '装机容量', value: '1500 MW', description: '新英格兰地区风电总装机容量', impact: '750台 × 2MW' },
        { factor: '风切变指数', value: '0.22', description: '新英格兰混合地形', impact: '10m→80m高度修正' },
        { factor: '尾流损失', value: '10%', description: '多排布置的尾流效应', impact: '降低风电场总输出' },
        { factor: '可用率', value: '95%', description: '运维停机后的可用率', impact: '实际可用风机比例' },
      ]

  return (
    <div className="space-y-6 animate-fade-in relative">
      {/* 粒子背景 */}

      {/* 页面标题 */}
      <div className="page-header-centered relative z-10">
        <h1>风电功率预测</h1>
        <p>基于物理模型的风电功率实时估算系统 — 风切变修正 · 空气密度修正 · 功率曲线 · 尾流损失</p>
        <div className="header-decoration" />
      </div>

      {/* 刷新按钮 — 居中布局，与 LoadForecast/Dashboard 统一 */}
      <div className="flex items-center justify-center gap-3 flex-wrap relative z-10">
        <RefreshButton onClick={fetchWindData} isLoading={windLoading} className="btn-ghost" />
      </div>

      {/* 核心指标 */}
      {windLoading && isInitialLoad.prediction ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <MetricCardSkeleton key={i} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
          <div className="stagger-item stagger-1">
            <MetricCard
              title="日总发电量"
              value={windMetrics.totalGeneration.toFixed(0)}
              unit="MW·h"
              icon={<Zap className="w-5 h-5 text-cyan-400" />}
              className="bg-gradient-to-br from-cyan-500/10 to-blue-500/10 border-cyan-500/20"
            />
          </div>
          <div className="stagger-item stagger-2">
            <MetricCard
              title="峰值功率"
              value={windMetrics.peakGeneration.toFixed(1)}
              unit="MW"
              icon={<TrendingUp className="w-5 h-5 text-success-500" />}
            />
          </div>
          <div className="stagger-item stagger-3">
            <MetricCard
              title="平均功率"
              value={windMetrics.averageGeneration.toFixed(1)}
              unit="MW"
              icon={<BarChart3 className="w-5 h-5 text-primary-500" />}
            />
          </div>
          <div className="stagger-item stagger-4">
            <MetricCard
              title="平均风速"
              value={windMetrics.averageWindSpeed.toFixed(1)}
              unit="m/s"
              icon={<Wind className="w-5 h-5 text-cyan-400" />}
            />
          </div>
          <div className="stagger-item stagger-5">
            <MetricCard
              title="容量因子"
              value={windMetrics.capacityFactor.toFixed(1)}
              unit="%"
              icon={<Gauge className="w-5 h-5 text-blue-400" />}
            />
          </div>
          <div className="stagger-item stagger-6">
            <MetricCard
              title="有效发电时长"
              value={windMetrics.activeHours}
              unit="小时"
              icon={<Activity className="w-5 h-5 text-teal-400" />}
            />
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 估算原理 */}
        <div className="card stagger-item stagger-1">
          <div className="card-header">
            <div className="card-header-icon bg-cyan-500/15">
              <Calculator className="w-5 h-5 text-cyan-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">物理模型</h2>
              <p className="card-header-subtitle">基于第一性原理的风功率计算</p>
            </div>
          </div>

          <div className="space-y-4">
            <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
              <h3 className="font-semibold text-white mb-2">风功率方程</h3>
              <div className="text-sm text-dark-300 font-mono bg-dark-800/50 p-3 rounded border border-dark-600">
                P = ½ × ρ × A × v³ × Cp × η
              </div>
              <div className="mt-2 text-xs text-dark-400 space-y-1">
                <div>· ρ: 空气密度 (kg/m³)</div>
                <div>· A: 风轮扫掠面积 (m²)</div>
                <div>· v: 轮毂高度风速 (m/s)</div>
                <div>· Cp: 功率系数 (贝兹极限 0.593)</div>
                <div>· η: 机电效率 (齿轮箱+发电机)</div>
              </div>
            </div>

            <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
              <h3 className="font-semibold text-white mb-2">风切变高度修正</h3>
              <div className="text-sm text-dark-300 font-mono bg-dark-800/50 p-3 rounded border border-dark-600">
                v_hub = v_ref × (h/h_ref)^α
              </div>
              <div className="mt-2 text-xs text-dark-400">
                10m风速 → 80m轮毂高度，α=0.22 (新英格兰混合地形)
              </div>
            </div>

            <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
              <h3 className="font-semibold text-white mb-2">空气密度修正</h3>
              <div className="text-sm text-dark-300 font-mono bg-dark-800/50 p-3 rounded border border-dark-600">
                ρ = ρ₀ × (T₀/T) × (P/P₀)
              </div>
              <div className="mt-2 text-xs text-dark-400">
                温度和气压影响空气密度，进而影响功率输出
              </div>
            </div>

            <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
              <h3 className="font-semibold text-white mb-2">功率曲线 (分段模型)</h3>
              <div className="text-sm text-dark-300 font-mono bg-dark-800/50 p-3 rounded border border-dark-600 space-y-1">
                <div>v &lt; 3 m/s: P = 0</div>
                <div>3 ≤ v &lt; 12: P = P_rated × ((v-3)/9)³</div>
                <div>12 ≤ v &lt; 25: P = P_rated</div>
                <div>v ≥ 25 m/s: P = 0</div>
              </div>
            </div>
          </div>
        </div>

        {/* 风机参数 */}
        <div className="card stagger-item stagger-2">
          <div className="card-header">
            <div className="card-header-icon bg-blue-500/15">
              <Gauge className="w-5 h-5 text-blue-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">风机参数</h2>
              <p className="card-header-subtitle">风力发电机组关键参数</p>
            </div>
          </div>

          <div className="space-y-3">
            {turbineParams.map((factor, index) => (
              <div
                key={index}
                className="bg-dark-700/50 rounded-lg p-3 border border-dark-600 hover:border-cyan-500/30 transition-colors"
              >
                <div className="flex justify-between items-start mb-2">
                  <h3 className="font-medium text-white text-sm">{factor.factor}</h3>
                  <span className="text-cyan-400 font-semibold text-sm tabular-nums">
                    {factor.value}
                  </span>
                </div>
                <p className="text-xs text-dark-300 mb-1">{factor.description}</p>
                <p className="text-xs text-cyan-300/70">{factor.impact}</p>
              </div>
            ))}
          </div>
        </div>

        {/* 实时条件 */}
        <div className="card stagger-item stagger-3">
          <div className="card-header">
            <div className="card-header-icon bg-cyan-500/15">
              <Wind className="w-5 h-5 text-cyan-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">实时风况</h2>
              <p className="card-header-subtitle">当前风电发电环境参数</p>
            </div>
          </div>

          <div className="space-y-4">
            {/* 当前风速 */}
            {weather?.regional_average?.wind_speed_10m !== undefined && (
              <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-dark-300 text-sm">10m 风速</span>
                  <Wind className="w-5 h-5 text-cyan-400" aria-hidden="true" />
                </div>
                <div className="text-2xl font-bold text-white tabular-nums">
                  {weather.regional_average.wind_speed_10m.toFixed(1)}
                  <span className="text-sm text-dark-400 ml-1">m/s</span>
                </div>
                <div className="text-xs text-dark-400 mt-1">
                  {weather.regional_average.wind_speed_10m < 3
                    ? '风速过低，无发电'
                    : weather.regional_average.wind_speed_10m < 12
                      ? '正常发电区间'
                      : weather.regional_average.wind_speed_10m < 25
                        ? '接近额定功率'
                        : '风速过高，安全停机'}
                </div>
              </div>
            )}

            {/* 轮毂高度风速 */}
            {windData && (
              <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-dark-300 text-sm">轮毂高度风速 (80m)</span>
                  <Gauge className="w-5 h-5 text-blue-400" aria-hidden="true" />
                </div>
                <div className="text-2xl font-bold text-white tabular-nums">
                  {(windData.hourly_wind_speed_hub.reduce((s, v) => s + v, 0) / 24).toFixed(1)}
                  <span className="text-sm text-dark-400 ml-1">m/s</span>
                </div>
                <div className="text-xs text-dark-400 mt-1">经风切变修正后的轮毂高度风速</div>
              </div>
            )}

            {/* 空气密度 */}
            {windData && (
              <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-dark-300 text-sm">空气密度</span>
                  <Activity className="w-5 h-5 text-teal-400" aria-hidden="true" />
                </div>
                <div className="text-2xl font-bold text-white tabular-nums">
                  {(windData.hourly_air_density.reduce((s, v) => s + v, 0) / 24).toFixed(3)}
                  <span className="text-sm text-dark-400 ml-1">kg/m³</span>
                </div>
                <div className="text-xs text-dark-400 mt-1">温度和气压修正后的实际空气密度</div>
              </div>
            )}

            {/* 温度 */}
            {weather?.regional_average?.temperature_2m !== undefined && (
              <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-dark-300 text-sm">环境温度</span>
                  <BarChart3 className="w-5 h-5 text-load-400" aria-hidden="true" />
                </div>
                <div className="text-2xl font-bold text-white tabular-nums">
                  {weather.regional_average.temperature_2m.toFixed(1)}
                  <span className="text-sm text-dark-400 ml-1">°C</span>
                </div>
                <div className="text-xs text-dark-400 mt-1">影响空气密度和功率输出</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 功率曲线图表 */}
      {powerCurve && !curveLoading && (
        <div className="card">
          <div className="card-header">
            <div className="card-header-icon bg-cyan-500/15">
              <TrendingUp className="w-5 h-5 text-cyan-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">风机功率特性曲线</h2>
              <p className="card-header-subtitle">功率曲线与理论功率对比</p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <div className="min-w-[600px]">
              {/* 功率曲线 SVG */}
              <div className="relative h-64 bg-dark-800/50 rounded-lg border border-dark-600 p-4">
                <PowerCurveChart curve={powerCurve.curve} ratedPower={powerCurve.rated_power_kw} />
              </div>

              {/* 关键参数 */}
              <div className="grid grid-cols-4 gap-4 mt-4">
                <div className="bg-dark-700/50 rounded-lg p-3 border border-dark-600 text-center">
                  <div className="text-xs text-dark-400">切入风速</div>
                  <div className="text-lg font-bold text-cyan-400">{powerCurve.cut_in_speed} m/s</div>
                </div>
                <div className="bg-dark-700/50 rounded-lg p-3 border border-dark-600 text-center">
                  <div className="text-xs text-dark-400">额定风速</div>
                  <div className="text-lg font-bold text-success-400">{powerCurve.rated_speed} m/s</div>
                </div>
                <div className="bg-dark-700/50 rounded-lg p-3 border border-dark-600 text-center">
                  <div className="text-xs text-dark-400">切出风速</div>
                  <div className="text-lg font-bold text-red-400">{powerCurve.cut_out_speed} m/s</div>
                </div>
                <div className="bg-dark-700/50 rounded-lg p-3 border border-dark-600 text-center">
                  <div className="text-xs text-dark-400">额定功率</div>
                  <div className="text-lg font-bold text-white">{(powerCurve.rated_power_kw / 1000).toFixed(1)} MW</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 24小时风电数据表 */}
      {(windData || prediction?.predictions) && (
        <div className="card">
          <div className="card-header">
            <div className="card-header-icon bg-cyan-500/15">
              <Zap className="w-5 h-5 text-cyan-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">24小时风电功率预测</h2>
              <p className="card-header-subtitle">逐小时风电发电预测与负荷对比</p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-dark-600">
                  <th scope="col" className="text-left py-3 px-4 text-dark-300 font-medium">时间</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">风电功率</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">轮毂风速</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">效率</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">不确定性</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">负荷预测</th>
                  <th scope="col" className="text-right py-3 px-4 text-dark-300 font-medium">风电占比</th>
                  <th scope="col" className="text-center py-3 px-4 text-dark-300 font-medium">风况</th>
                </tr>
              </thead>
              <tbody>
                {(windData
                  ? windData.hourly_generation_mw.map((gen, i) => ({
                      gen,
                      speed: windData.hourly_wind_speed_hub[i],
                      eff: windData.hourly_efficiency[i],
                      unc: windData.hourly_uncertainty_mw[i],
                      load: prediction?.predictions?.[i]?.load_forecast_mw || 0,
                      timestamp: windData.timestamps[i],
                      hour: i,
                    }))
                  : prediction!.predictions.map((pred) => ({
                      gen: pred.wind_estimation_mw || 0,
                      speed: 0,
                      eff: 0,
                      unc: 0,
                      load: pred.load_forecast_mw,
                      timestamp: pred.timestamp,
                      hour: pred.hour,
                    }))
                ).map((row, index) => {
                  const coverage = row.load > 0 ? (row.gen / row.load) * 100 : 0
                  const windStatus =
                    row.speed < 3 ? '无风' :
                    row.speed < 6 ? '微风' :
                    row.speed < 12 ? '正常' :
                    row.speed < 25 ? '强风' : '停机'

                  const statusColor =
                    row.speed < 3 ? 'text-dark-400' :
                    row.speed < 6 ? 'text-blue-300' :
                    row.speed < 12 ? 'text-cyan-400' :
                    row.speed < 25 ? 'text-success-400' : 'text-red-400'

                  const baseAlpha = index % 2 === 0 ? 0.22 : 0.38
                  const windRatio = windMetrics.peakGeneration > 0 ? Math.min(row.gen / windMetrics.peakGeneration, 1) : 0
                  const r = Math.round(30 + windRatio * 15)
                  const g = Math.round(41 + windRatio * 35)
                  const b = Math.round(59 + windRatio * 20)
                  const rowBg = `rgba(${r}, ${g}, ${b}, ${baseAlpha})`

                  return (
                    <tr
                      key={index}
                      className="table-row wind-table-row"
                      style={{ '--row-bg': rowBg } as React.CSSProperties}
                    >
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span className="text-white font-medium tabular-nums">{row.hour}时</span>
                          <span className="text-dark-400 text-xs tabular-nums">
                            {new Date(row.timestamp).toLocaleTimeString('zh-CN', {
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </span>
                        </div>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span className={`font-medium tabular-nums ${row.gen > 0 ? 'text-cyan-400' : 'text-dark-400'}`}>
                          {row.gen.toFixed(1)}
                        </span>
                        <span className="text-dark-400 text-xs ml-1">MW</span>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span className="text-blue-300 font-medium tabular-nums">
                          {row.speed > 0 ? row.speed.toFixed(1) : '—'}
                        </span>
                        {row.speed > 0 && <span className="text-dark-400 text-xs ml-1">m/s</span>}
                      </td>
                      <td className="text-right py-3 px-4">
                        <span className="text-dark-300 font-medium tabular-nums">
                          {(row.eff * 100).toFixed(1)}%
                        </span>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span className="text-dark-400 text-xs tabular-nums">
                          ±{row.unc.toFixed(1)} MW
                        </span>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span className="text-white font-medium tabular-nums">
                          {row.load.toFixed(0)}
                        </span>
                        <span className="text-dark-400 text-xs ml-1">MW</span>
                      </td>
                      <td className="text-right py-3 px-4">
                        <span className={`font-medium tabular-nums ${coverage > 5 ? 'text-success-400' : 'text-dark-300'}`}>
                          {coverage.toFixed(1)}%
                        </span>
                      </td>
                      <td className="text-center py-3 px-4">
                        <div className="flex items-center justify-center gap-2">
                          <Wind className={`w-4 h-4 ${statusColor}`} aria-hidden="true" />
                          <span className={`text-xs ${statusColor}`}>{windStatus}</span>
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
      {windError && (
        <div className="card border-red-500/30">
          <div className="card-header !border-red-500/20">
            <div className="card-header-icon bg-red-500/15">
              <Activity className="w-5 h-5 text-red-400" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1 flex items-center justify-between">
              <h2 className="card-header-title text-red-400">风电API连接失败</h2>
              <span className="text-xs text-dark-400">显示预测管线中的风电数据</span>
            </div>
          </div>
          <p className="text-sm text-dark-300 mt-2">{windError}</p>
        </div>
      )}
    </div>
  )
}

// ── 功率曲线 SVG 图表组件 ──
const PowerCurveChart: React.FC<{
  curve: Array<{ wind_speed_ms: number; power_curve_kw: number; power_theoretical_kw: number }>
  ratedPower: number
}> = ({ curve, ratedPower }) => {
  const width = 800
  const height = 240
  const margin = { top: 20, right: 40, bottom: 30, left: 50 }
  const plotW = width - margin.left - margin.right
  const plotH = height - margin.top - margin.bottom

  const maxSpeed = 30
  const maxPower = ratedPower * 1.1

  const xScale = (v: number) => margin.left + (v / maxSpeed) * plotW
  const yScale = (v: number) => margin.top + plotH - (v / maxPower) * plotH

  const curvePath = curve
    .map((d, i) => `${i === 0 ? 'M' : 'L'} ${xScale(d.wind_speed_ms)},${yScale(d.power_curve_kw)}`)
    .join(' ')

  const theoryPath = curve
    .map((d, i) => `${i === 0 ? 'M' : 'L'} ${xScale(d.wind_speed_ms)},${yScale(d.power_theoretical_kw)}`)
    .join(' ')

  // 网格线
  const xTicks = [0, 5, 10, 15, 20, 25, 30]
  const yTicks = [0, ratedPower * 0.25, ratedPower * 0.5, ratedPower * 0.75, ratedPower]

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-full">
      {/* 网格 */}
      {xTicks.map((t) => (
        <g key={`x-${t}`}>
          <line x1={xScale(t)} y1={margin.top} x2={xScale(t)} y2={margin.top + plotH} stroke="#2d3748" strokeWidth="1" />
          <text x={xScale(t)} y={height - 8} fill="#718096" fontSize="11" textAnchor="middle">{t}</text>
        </g>
      ))}
      {yTicks.map((t) => (
        <g key={`y-${t}`}>
          <line x1={margin.left} y1={yScale(t)} x2={margin.left + plotW} y2={yScale(t)} stroke="#2d3748" strokeWidth="1" />
          <text x={margin.left - 8} y={yScale(t) + 4} fill="#718096" fontSize="11" textAnchor="end">
            {(t / 1000).toFixed(1)}
          </text>
        </g>
      ))}

      {/* 轴标签 */}
      <text x={width / 2} y={height - 2} fill="#a0aec0" fontSize="12" textAnchor="middle">风速 (m/s)</text>
      <text x={15} y={height / 2} fill="#a0aec0" fontSize="12" textAnchor="middle" transform={`rotate(-90, 15, ${height / 2})`}>功率 (MW)</text>

      {/* 理论功率 (虚线) */}
      <path d={theoryPath} fill="none" stroke="#4a5568" strokeWidth="1.5" strokeDasharray="4,3" opacity="0.6" />

      {/* 功率曲线 (实线) */}
      <path d={curvePath} fill="none" stroke="#06B6D4" strokeWidth="2.5" />

      {/* 关键点标注 */}
      <line x1={xScale(3)} y1={margin.top} x2={xScale(3)} y2={margin.top + plotH} stroke="#f56565" strokeWidth="1" strokeDasharray="2,2" opacity="0.5" />
      <text x={xScale(3)} y={margin.top - 4} fill="#f56565" fontSize="10" textAnchor="middle">切入</text>

      <line x1={xScale(12)} y1={margin.top} x2={xScale(12)} y2={margin.top + plotH} stroke="#48bb78" strokeWidth="1" strokeDasharray="2,2" opacity="0.5" />
      <text x={xScale(12)} y={margin.top - 4} fill="#48bb78" fontSize="10" textAnchor="middle">额定</text>

      <line x1={xScale(25)} y1={margin.top} x2={xScale(25)} y2={margin.top + plotH} stroke="#f56565" strokeWidth="1" strokeDasharray="2,2" opacity="0.5" />
      <text x={xScale(25)} y={margin.top - 4} fill="#f56565" fontSize="10" textAnchor="middle">切出</text>

      {/* 图例 */}
      <g transform={`translate(${margin.left + 10}, ${margin.top + 10})`}>
        <line x1="0" y1="0" x2="20" y2="0" stroke="#06B6D4" strokeWidth="2.5" />
        <text x="26" y="4" fill="#a0aec0" fontSize="11">功率曲线</text>
        <line x1="0" y1="16" x2="20" y2="16" stroke="#4a5568" strokeWidth="1.5" strokeDasharray="4,3" />
        <text x="26" y="20" fill="#a0aec0" fontSize="11">理论功率</text>
      </g>
    </svg>
  )
}

export default WindGeneration
