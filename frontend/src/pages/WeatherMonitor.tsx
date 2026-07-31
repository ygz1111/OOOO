import React, { useState } from 'react'
import { useApi } from '../contexts/ApiContext'
import WeatherCard from '../components/WeatherCard'
import WeatherMap from '../components/WeatherMap'
import { CardSkeleton, Spinner, ErrorBanner } from '../components/Skeleton'
import { Cloud, MapPin, RefreshCw, Wind, Navigation, Thermometer, MousePointerClick } from 'lucide-react'
import ParticleField from '../components/ui/ParticleField'

const WeatherMonitor: React.FC = () => {
  const { weather, isLoading, errors, loadWeather } = useApi()
  const [selectedStation, setSelectedStation] = useState<string | null>(null)

  const getRegionalStats = () => {
    if (!weather?.stations?.length) return null

    const temps = weather.stations.map((s) => s.temperature_2m)
    const humidity = weather.stations.map((s) => s.relative_humidity_2m).filter(Boolean) as number[]
    const winds = weather.stations.map((s) => s.wind_speed_10m).filter(Boolean) as number[]

    return {
      tempRange: {
        min: Math.min(...temps),
        max: Math.max(...temps),
        avg: temps.reduce((a, b) => a + b, 0) / temps.length,
      },
      humidityAvg: humidity.length ? humidity.reduce((a, b) => a + b, 0) / humidity.length : 0,
      windAvg: winds.length ? winds.reduce((a, b) => a + b, 0) / winds.length : 0,
    }
  }

  const stats = getRegionalStats()

  return (
    <div className="space-y-6 animate-fade-in relative">
      {/* 粒子背景 */}
      <ParticleField count={30} opacity={0.25} color="#10B981" />

      {/* 页面标题 — 居中 */}
      <div className="page-header-centered relative z-10">
        <h1>气象数据监控</h1>
        <p>Open-Meteo API 实时采集新英格兰地区6个站点气象数据</p>
        <div className="header-decoration" />
      </div>

      <div className="flex justify-center relative z-10">
        <button
          onClick={() => loadWeather(true)}
          disabled={isLoading.weather}
          className="btn btn-primary"
          aria-label="刷新气象数据"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading.weather ? 'animate-spin' : ''}`} aria-hidden="true" />
          刷新数据
        </button>
      </div>

      {/* 区域统计概览 */}
      {stats ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 animate-slide-up">
          <div className="metric-card stagger-item stagger-1">
            <div className="flex items-start justify-between mb-2">
              <div>
                <p className="text-dark-400 text-xs uppercase tracking-wider mb-1">温度范围</p>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold text-white tabular-nums">
                    {stats.tempRange.min.toFixed(1)}° - {stats.tempRange.max.toFixed(1)}°
                  </span>
                  <span className="text-dark-400 text-sm">C</span>
                </div>
                <div className="text-sm text-dark-300 mt-1 tabular-nums">
                  平均 {stats.tempRange.avg.toFixed(1)}°C
                </div>
              </div>
              <div className="p-2 bg-load-500/15 rounded-lg">
                <Thermometer className="w-5 h-5 text-load-400" aria-hidden="true" />
              </div>
            </div>
          </div>

          <div className="metric-card stagger-item stagger-2">
            <div className="flex items-start justify-between mb-2">
              <div>
                <p className="text-dark-400 text-xs uppercase tracking-wider mb-1">区域平均湿度</p>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold text-white tabular-nums">
                    {stats.humidityAvg.toFixed(0)}
                  </span>
                  <span className="text-dark-400 text-sm">%</span>
                </div>
                <div className="text-sm text-dark-300 mt-1">基于6个站点</div>
              </div>
              <div className="p-2 bg-load-500/15 rounded-lg">
                <Cloud className="w-5 h-5 text-load-400" aria-hidden="true" />
              </div>
            </div>
          </div>

          <div className="metric-card stagger-item stagger-3">
            <div className="flex items-start justify-between mb-2">
              <div>
                <p className="text-dark-400 text-xs uppercase tracking-wider mb-1">区域平均风速</p>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold text-white tabular-nums">
                    {stats.windAvg.toFixed(1)}
                  </span>
                  <span className="text-dark-400 text-sm">mph</span>
                </div>
                <div className="text-sm text-dark-300 mt-1">当前风力条件</div>
              </div>
              <div className="p-2 bg-solar-500/15 rounded-lg">
                <Wind className="w-5 h-5 text-solar-400" aria-hidden="true" />
              </div>
            </div>
          </div>
        </div>
      ) : isLoading.weather ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <CardSkeleton lines={2} />
          <CardSkeleton lines={2} />
          <CardSkeleton lines={2} />
        </div>
      ) : null}

      {/* ══════════════════════════════════════════════════════
          三列布局：站点列表 | 气象地图(主视觉) | 站点详情
          CSS Grid: 左 3列 | 中 6列(放大) | 右 3列
          所有卡片头部使用 .card-header 保证水平线对齐
          ══════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-start">
        {/* ── 左侧 - 气象站点列表（紧凑型滚动抽屉）── */}
        <div className="xl:col-span-3">
          <div className="card">
            {/* 统一卡片头部 */}
            <div className="card-header">
              <div className="card-header-icon bg-load-500/15">
                <Navigation className="w-5 h-5 text-load-400" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h2 className="card-header-title">气象站点</h2>
                <p className="card-header-subtitle">6个关键站点实时监控</p>
              </div>
            </div>

            {/* 区域平均卡片 - 固定在顶部 */}
            {weather?.regional_average && (
              <div className="mb-3">
                <WeatherCard
                  station={
                    {
                      name: '区域平均',
                      latitude: 0,
                      longitude: 0,
                      ...weather.regional_average,
                    } as any
                  }
                  isRegional={true}
                />
              </div>
            )}

            {/* 站点列表 - 可滚动区域，不再撑高页面 */}
            <div className="space-y-2 max-h-[480px] overflow-y-auto pr-1 -mr-1">
              {weather?.stations?.map((station, index) => (
                <div
                  key={index}
                  className={`cursor-pointer rounded-lg transition-all duration-200 ${
                    selectedStation === station.name
                      ? 'ring-2 ring-load-500 ring-offset-1 ring-offset-dark-800'
                      : 'hover:ring-1 hover:ring-dark-600'
                  }`}
                  onClick={() => setSelectedStation(station.name)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setSelectedStation(station.name)
                    }
                  }}
                  aria-pressed={selectedStation === station.name}
                  aria-label={`选择站点 ${station.name}`}
                >
                  <WeatherCard station={station} />
                </div>
              ))}

              {isLoading.weather && <Spinner size="lg" />}
            </div>

            {errors.weather && <ErrorBanner message={errors.weather} onRetry={loadWeather} />}
          </div>
        </div>

        {/* ── 中间 - 气象地图（主视觉中心，大幅度放大）── */}
        <div className="xl:col-span-6">
          <div className="card">
            {/* 统一卡片头部 */}
            <div className="card-header">
              <div className="card-header-icon bg-load-500/15">
                <MapPin className="w-5 h-5 text-load-400" aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="card-header-title">新英格兰气象地图</h2>
                <p className="card-header-subtitle">点击地图标记选择站点</p>
              </div>
              {selectedStation && (
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-load-500/15 border border-load-500/20">
                  <span className="w-1.5 h-1.5 rounded-full bg-load-400 animate-pulse" aria-hidden="true" />
                  <span className="text-xs font-medium text-load-300">{selectedStation}</span>
                </div>
              )}
            </div>

            {/* 地图 - 放大显示，作为主视觉中心 */}
            {weather?.stations && weather.stations.length > 0 ? (
              <div className="flex items-center justify-center">
                <WeatherMap
                  stations={weather.stations}
                  selectedStation={selectedStation}
                  onSelectStation={setSelectedStation}
                />
              </div>
            ) : isLoading.weather ? (
              <div className="flex items-center justify-center h-[500px]">
                <Spinner size="lg" />
              </div>
            ) : (
              <div className="flex items-center justify-center h-[500px] text-dark-400">
                <div className="text-center">
                  <MapPin className="w-12 h-12 mx-auto mb-3 opacity-40" aria-hidden="true" />
                  <p className="text-sm">暂无地图数据</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── 右侧 - 站点详情面板（含优雅空状态）── */}
        <div className="xl:col-span-3">
          <div className="card">
            {/* 统一卡片头部 */}
            <div className="card-header">
              <div className="card-header-icon bg-load-500/15">
                <Cloud className="w-5 h-5 text-load-400" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h2 className="card-header-title">站点详情</h2>
                <p className="card-header-subtitle">
                  {selectedStation ? `${selectedStation}` : '选择站点查看详情'}
                </p>
              </div>
            </div>

            {selectedStation && weather?.stations ? (
              <div className="space-y-4 animate-fade-in">
                {weather.stations
                  .filter((s) => s.name === selectedStation)
                  .map((station, index) => (
                    <div key={index} className="space-y-4">
                      {/* 站点基本信息 */}
                      <div className="flex justify-between items-start pb-3 border-b border-dark-700/60">
                        <div>
                          <h3 className="text-base font-semibold text-white">{station.name}</h3>
                          <p className="text-xs text-dark-400 tabular-nums mt-0.5">
                            {station.latitude.toFixed(4)}°N, {station.longitude.toFixed(4)}°W
                          </p>
                        </div>
                        <div className="text-right">
                          <span className="status-indicator status-online inline-block"></span>
                          <p className="text-[11px] text-dark-400 mt-1.5">在线</p>
                        </div>
                      </div>

                      {/* 核心温度展示 */}
                      <div className="bg-gradient-to-br from-load-500/10 to-load-600/5 rounded-xl p-4 border border-load-500/20">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Thermometer className="w-5 h-5 text-load-400" aria-hidden="true" />
                            <span className="text-dark-300 text-sm">当前温度</span>
                          </div>
                          <div className="flex items-baseline gap-1">
                            <span className="text-3xl font-bold text-white tabular-nums">
                              {station.temperature_2m.toFixed(1)}
                            </span>
                            <span className="text-dark-400">°C</span>
                          </div>
                        </div>
                      </div>

                      {/* 详细数据网格 */}
                      <div className="grid grid-cols-2 gap-2.5">
                        <div className="bg-dark-700/40 rounded-lg p-3 border border-dark-700">
                          <div className="text-[11px] text-dark-400 mb-1">露点温度</div>
                          <div className="text-base font-semibold text-white tabular-nums">
                            {station.dew_point_2m.toFixed(1)}°C
                          </div>
                        </div>
                        {station.relative_humidity_2m && (
                          <div className="bg-dark-700/40 rounded-lg p-3 border border-dark-700">
                            <div className="text-[11px] text-dark-400 mb-1">相对湿度</div>
                            <div className="text-base font-semibold text-white tabular-nums">
                              {station.relative_humidity_2m.toFixed(0)}%
                            </div>
                          </div>
                        )}
                        {station.wind_speed_10m && (
                          <div className="bg-dark-700/40 rounded-lg p-3 border border-dark-700">
                            <div className="text-[11px] text-dark-400 mb-1">风速</div>
                            <div className="text-base font-semibold text-white tabular-nums">
                              {station.wind_speed_10m.toFixed(1)} mph
                            </div>
                          </div>
                        )}
                        {station.cloud_cover && (
                          <div className="bg-dark-700/40 rounded-lg p-3 border border-dark-700">
                            <div className="text-[11px] text-dark-400 mb-1">云量</div>
                            <div className="text-base font-semibold text-white tabular-nums">
                              {station.cloud_cover.toFixed(0)}%
                            </div>
                          </div>
                        )}
                        {station.shortwave_radiation && (
                          <div className="bg-solar-500/10 rounded-lg p-3 border border-solar-500/20 col-span-2">
                            <div className="flex items-center gap-1.5 mb-1">
                              <span className="text-[11px] text-solar-300">太阳辐射</span>
                            </div>
                            <div className="text-base font-semibold text-solar-400 tabular-nums">
                              {station.shortwave_radiation.toFixed(0)} W/m²
                            </div>
                          </div>
                        )}
                      </div>

                      {/* 数据更新时间 */}
                      <div className="pt-3 border-t border-dark-700/60">
                        <div className="text-[11px] text-dark-400 tabular-nums">
                          最后更新: {weather.timestamp
                            ? new Date(weather.timestamp).toLocaleString('zh-CN')
                            : '未知'}
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            ) : (
              /* ── 优雅默认空状态 ── */
              <div className="empty-state">
                <div className="empty-state-icon">
                  <div className="w-16 h-16 rounded-full bg-dark-700/60 border border-dark-700 flex items-center justify-center">
                    <MousePointerClick className="w-8 h-8 text-dark-400" aria-hidden="true" />
                  </div>
                </div>
                <p className="empty-state-title">尚未选择站点</p>
                <p className="empty-state-desc">
                  点击左侧站点卡片或地图上的标记，查看详细气象数据
                </p>
                <div className="mt-5 flex items-center gap-2 px-3 py-1.5 rounded-md bg-dark-700/40 border border-dark-700">
                  <kbd className="text-[11px] font-mono text-dark-300 px-1.5 py-0.5 rounded bg-dark-700">Tab</kbd>
                  <span className="text-[11px] text-dark-400">+</span>
                  <kbd className="text-[11px] font-mono text-dark-300 px-1.5 py-0.5 rounded bg-dark-700">Enter</kbd>
                  <span className="text-[11px] text-dark-400">键盘可选</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default WeatherMonitor
