import React, { useState } from 'react'
import { useApi } from '../contexts/ApiContext'
import MetricCard from '../components/MetricCard'
import WeatherCard from '../components/WeatherCard'
import WeatherMap from '../components/WeatherMap'
import { CardSkeleton, Spinner, ErrorBanner } from '../components/Skeleton'
import { Cloud, MapPin, RefreshCw, Wind, Navigation, Thermometer, MousePointerClick } from 'lucide-react'
import { formatEasternISO, ET_FULL } from '../utils/time'

const isFiniteNumber = (value: number | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value)

const WeatherMonitor: React.FC = () => {
  const { weather, isLoading, errors, loadWeather } = useApi()
  const [selectedStation, setSelectedStation] = useState<string | null>(null)

  const getRegionalStats = () => {
    if (!weather?.stations?.length) return null

    const temps = weather.stations.map((s) => s.temperature_2m).filter(isFiniteNumber)
    const humidity = weather.stations.map((s) => s.relative_humidity_2m).filter(isFiniteNumber)
    const winds = weather.stations.map((s) => s.wind_speed_10m).filter(isFiniteNumber)
    if (!temps.length) return null

    return {
      tempRange: {
        min: Math.min(...temps),
        max: Math.max(...temps),
        avg: temps.reduce((a, b) => a + b, 0) / temps.length,
      },
      humidityAvg: humidity.length ? humidity.reduce((a, b) => a + b, 0) / humidity.length : null,
      windAvg: winds.length ? winds.reduce((a, b) => a + b, 0) / winds.length : null,
    }
  }

  const stats = getRegionalStats()

  return (
    <div className="space-y-6 animate-fade-in relative">
      <div className="page-header flex flex-wrap items-start justify-between gap-4 relative z-10">
        <div className="min-w-0">
          <h1>气象监测</h1>
          <p>新英格兰区域 6 个站点的气温、风速、湿度及太阳辐射数据。</p>
        </div>
        <div className="page-actions">
          <button
            onClick={() => loadWeather(true)}
            disabled={isLoading.weather}
            className="btn btn-primary"
            aria-label="刷新气象数据"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading.weather ? 'animate-spin' : ''}`} aria-hidden="true" />
            <span>同步气象数据</span>
          </button>
        </div>
      </div>

      {/* 区域统计概览 */}
      {stats ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 animate-slide-up">
          <div className="stagger-item stagger-1">
            <MetricCard
              title="区域气温跨度"
              value={`${stats.tempRange.min.toFixed(1)}° ~ ${stats.tempRange.max.toFixed(1)}°`}
              unit="C"
              icon={<Thermometer className="w-5 h-5 text-primary-600" />}
              trend="stable"
              trendValue={`区域平均 ${stats.tempRange.avg.toFixed(1)}°C`}
            />
          </div>

          <div className="stagger-item stagger-2">
            <MetricCard
              title="区域平均相对湿度"
              value={stats.humidityAvg == null ? '--' : stats.humidityAvg.toFixed(0)}
              unit={stats.humidityAvg == null ? '' : '%'}
              icon={<Cloud className="w-5 h-5 text-primary-600" />}
              trend="stable"
              trendValue="站点有效湿度的算术平均"
            />
          </div>

          <div className="stagger-item stagger-3 sm:col-span-2 xl:col-span-1">
            <MetricCard
              title="区域平均风速"
              value={stats.windAvg == null ? '--' : stats.windAvg.toFixed(1)}
              unit={stats.windAvg == null ? '' : 'm/s'}
              icon={<Wind className="w-5 h-5 text-primary-600" />}
              trend="stable"
              trendValue="站点有效风速的算术平均"
            />
          </div>
        </div>
      ) : isLoading.weather ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
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
        <div className="min-w-0 xl:col-span-3">
          <div className="card">
            {/* 统一卡片头部 */}
            <div className="card-header">
              <div className="card-header-icon bg-surface-muted border border-edge">
                <Navigation className="w-5 h-5 text-primary-600" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h2 className="card-header-title">气象站点</h2>
                <p className="card-header-subtitle">6个关键站点实时监控</p>
              </div>
            </div>

            {/* 区域平均卡片 - 固定在顶部 */}
            {weather?.regional_average && (
              <details className="weather-regional-details mb-3">
                <summary>区域平均气象明细</summary>
                <WeatherCard
                  station={
                    {
                      name: '区域平均',
                      latitude: 0,
                      longitude: 0,
                      ...weather.regional_average,
                    }
                  }
                  isRegional={true}
                />
              </details>
            )}

            {/* 站点列表 - 可滚动区域，不再撑高页面 */}
            <div className="weather-station-list space-y-2 max-h-[480px] overflow-y-auto pr-1 -mr-1" role="group" aria-label="选择气象站点">
              {weather?.stations?.map((station, index) => (
                <div
                  key={index}
                  className={`cursor-pointer rounded transition-all duration-200 ${
                    selectedStation === station.name
                      ? 'ring-2 ring-primary-600 ring-offset-1 ring-offset-surface'
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
                  <WeatherCard station={station} compact />
                </div>
              ))}

              {isLoading.weather && <Spinner size="lg" />}
            </div>

            {errors.weather && <ErrorBanner message={errors.weather} onRetry={loadWeather} />}
          </div>
        </div>

        {/* ── 中间 - 气象地图（主视觉中心，大幅度放大）── */}
        <div className="min-w-0 xl:col-span-6">
          <div className="card">
            {/* 统一卡片头部 */}
            <div className="card-header flex-wrap">
              <div className="card-header-icon bg-surface-muted border border-edge">
                <MapPin className="w-5 h-5 text-primary-600" aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="card-header-title">新英格兰气象地图</h2>
                <p className="card-header-subtitle">点击地图标记选择站点</p>
              </div>
              {selectedStation && (
                <div className="flex min-w-0 max-w-full items-center gap-1.5 px-2.5 py-1 rounded bg-surface-muted border border-edge">
                  <span className="w-1.5 h-1.5 shrink-0 rounded-full bg-primary-600" aria-hidden="true" />
                  <span className="break-words text-xs font-medium text-primary-600">{selectedStation}</span>
                </div>
              )}
            </div>

            {/* 地图 - 放大显示，作为主视觉中心 */}
            {weather?.stations && weather.stations.length > 0 ? (
              <div className="mx-auto w-full max-w-[440px]">
                <WeatherMap
                  stations={weather.stations}
                  selectedStation={selectedStation}
                  onSelectStation={setSelectedStation}
                />
              </div>
            ) : isLoading.weather ? (
              <div className="flex items-center justify-center h-[280px] sm:h-[360px]" role="status" aria-label="正在加载气象地图">
                <Spinner size="lg" />
              </div>
            ) : (
              <div className="flex items-center justify-center h-[280px] sm:h-[360px] text-ink-muted">
                <div className="text-center">
                  <MapPin className="w-12 h-12 mx-auto mb-3 opacity-40" aria-hidden="true" />
                  <p className="text-sm">暂无地图数据</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── 右侧 - 站点详情面板（含优雅空状态）── */}
        <div className="min-w-0 xl:col-span-3">
          <div className="card">
            {/* 统一卡片头部 */}
            <div className="card-header">
              <div className="card-header-icon bg-surface-muted border border-edge">
                <Cloud className="w-5 h-5 text-primary-600" aria-hidden="true" />
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
                      <div className="flex flex-wrap justify-between items-start gap-3 pb-3 border-b border-edge">
                        <div className="min-w-0 break-words">
                          <h3 className="text-base font-semibold text-ink">{station.name}</h3>
                          <p className="text-xs text-ink-muted tabular-nums mt-0.5">
                            {Math.abs(station.latitude).toFixed(4)}°{station.latitude >= 0 ? 'N' : 'S'}, {' '}
                            {Math.abs(station.longitude).toFixed(4)}°{station.longitude >= 0 ? 'E' : 'W'}
                          </p>
                        </div>
                        <div className="shrink-0 text-right">
                          <span className="status-indicator status-online inline-block"></span>
                          <p className="text-[11px] text-ink-muted mt-1.5">数据可用</p>
                        </div>
                      </div>

                      {/* 核心温度展示 */}
                      <div className="bg-surface-muted rounded p-4 border border-edge">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <Thermometer className="w-5 h-5 text-primary-600" aria-hidden="true" />
                            <span className="text-ink text-sm">当前温度</span>
                          </div>
                          <div className="flex items-baseline gap-1">
                            <span className="text-3xl font-bold text-ink tabular-nums">
                              {station.temperature_2m.toFixed(1)}
                            </span>
                            <span className="text-ink-muted">°C</span>
                          </div>
                        </div>
                      </div>

                      {/* 详细数据网格 */}
                      <div className="grid grid-cols-2 gap-2.5">
                        <div className="bg-surface-muted rounded p-3 border border-edge">
                          <div className="text-[11px] text-ink-muted mb-1">露点温度</div>
                          <div className="text-base font-semibold text-ink tabular-nums">
                            {station.dew_point_2m.toFixed(1)}°C
                          </div>
                        </div>
                        {isFiniteNumber(station.relative_humidity_2m) && (
                          <div className="bg-surface-muted rounded p-3 border border-edge">
                            <div className="text-[11px] text-ink-muted mb-1">相对湿度</div>
                            <div className="text-base font-semibold text-ink tabular-nums">
                              {station.relative_humidity_2m.toFixed(0)}%
                            </div>
                          </div>
                        )}
                        {isFiniteNumber(station.wind_speed_10m) && (
                          <div className="bg-surface-muted rounded p-3 border border-edge">
                            <div className="text-[11px] text-ink-muted mb-1">风速</div>
                            <div className="text-base font-semibold text-ink tabular-nums">
                              {station.wind_speed_10m.toFixed(1)} m/s
                            </div>
                          </div>
                        )}
                        {isFiniteNumber(station.cloud_cover) && (
                          <div className="bg-surface-muted rounded p-3 border border-edge">
                            <div className="text-[11px] text-ink-muted mb-1">云量</div>
                            <div className="text-base font-semibold text-ink tabular-nums">
                              {station.cloud_cover.toFixed(0)}%
                            </div>
                          </div>
                        )}
                        {isFiniteNumber(station.shortwave_radiation) && (
                          <div className="bg-surface-muted rounded p-3 border border-edge col-span-2">
                            <div className="flex items-center gap-1.5 mb-1">
                              <span className="text-[11px] text-ink-muted">太阳辐射</span>
                            </div>
                            <div className="text-base font-semibold text-ink tabular-nums">
                              {station.shortwave_radiation.toFixed(0)} W/m²
                            </div>
                          </div>
                        )}
                      </div>

                      {/* 数据更新时间 */}
                      <div className="pt-3 border-t border-edge">
                        <div className="text-[11px] text-ink-muted tabular-nums">
                          最后更新 (ET): {weather.timestamp
                            ? formatEasternISO(weather.timestamp, ET_FULL)
                            : '未知'}
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            ) : (
              /* ── 优雅默认空状态 ── */
              <div className="weather-station-empty">
                <div className="empty-state-icon">
                  <div className="w-16 h-16 rounded-full bg-surface-muted border border-edge flex items-center justify-center">
                    <MousePointerClick className="w-8 h-8 text-ink-muted" aria-hidden="true" />
                  </div>
                </div>
                <p className="empty-state-title">尚未选择站点</p>
                <p className="empty-state-desc">
                  点击左侧站点卡片或地图上的标记，查看详细气象数据
                </p>
                <div className="mt-4 flex flex-wrap items-center justify-center gap-2 px-3 py-1.5 rounded-md bg-surface-muted border border-edge">
                  <kbd className="text-[11px] tabular-nums text-ink px-1.5 py-0.5 rounded bg-surface-muted">Tab</kbd>
                  <span className="text-[11px] text-ink-muted">+</span>
                  <kbd className="text-[11px] tabular-nums text-ink px-1.5 py-0.5 rounded bg-surface-muted">Enter</kbd>
                  <span className="text-[11px] text-ink-muted">键盘可选</span>
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
