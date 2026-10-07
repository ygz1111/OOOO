import React from 'react'
import { Thermometer, Droplets, Wind, Cloud, Sun, MapPin } from 'lucide-react'
import { WeatherStationData } from '../types'

interface WeatherCardProps {
  station: Pick<WeatherStationData, 'name' | 'latitude' | 'longitude'>
    & Partial<Omit<WeatherStationData, 'name' | 'latitude' | 'longitude'>>
  isRegional?: boolean
  compact?: boolean
}

const WeatherCard: React.FC<WeatherCardProps> = ({ station, isRegional = false, compact = false }) => {
  const isFiniteNumber = (value: number | undefined): value is number =>
    typeof value === 'number' && Number.isFinite(value)
  // regional_average 可能缺少部分字段；缺失值应显示“--”，不能伪装成真实的 0。
  const temperature = isFiniteNumber(station.temperature_2m) ? station.temperature_2m : null
  const dewPoint = isFiniteNumber(station.dew_point_2m) ? station.dew_point_2m : null

  const getTemperatureColor = (temp: number | null) => {
    if (temp == null) return 'text-dark-400'
    if (temp >= 30) return 'text-danger-600'
    if (temp >= 25) return 'text-warning-600'
    if (temp >= 15) return 'text-success-600'
    if (temp >= 0) return 'text-primary-600'
    return 'text-primary-700'
  }

  const getHumidityColor = (humidity?: number) => {
    if (!isFiniteNumber(humidity)) return 'text-dark-400'
    if (humidity >= 80) return 'text-primary-600'
    if (humidity >= 60) return 'text-primary-600'
    if (humidity >= 40) return 'text-dark-300'
    return 'text-dark-400'
  }

  const formatWindSpeed = (speed?: number) => {
    // Open-Meteo wind_speed_10m 单位为 m/s（2026-08 修正：此前误标 mph）
    if (!isFiniteNumber(speed)) return '--'
    return `${speed.toFixed(1)} m/s`
  }

  const latitude = `${Math.abs(station.latitude).toFixed(4)}°${station.latitude >= 0 ? 'N' : 'S'}`
  const longitude = `${Math.abs(station.longitude).toFixed(4)}°${station.longitude >= 0 ? 'E' : 'W'}`

  if (compact) return (
    <article className="weather-station-summary" aria-label={`${station.name} 气象数据`}>
      <div className="flex min-w-0 items-center justify-between gap-3">
        <h3 className="min-w-0 break-words text-sm font-medium text-ink">{station.name}</h3>
        <span className={`shrink-0 text-lg font-semibold tabular-nums ${getTemperatureColor(temperature)}`}>
          {temperature == null ? '--' : temperature.toFixed(1)}<span className="ml-1 text-xs font-normal text-ink-muted">°C</span>
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-muted tabular-nums">
        <span>湿度 {isFiniteNumber(station.relative_humidity_2m) ? `${station.relative_humidity_2m.toFixed(0)}%` : '--'}</span>
        <span>风速 {formatWindSpeed(station.wind_speed_10m)}</span>
      </div>
    </article>
  )

  return (
    <div
      className={`weather-card ${isRegional ? 'weather-card-regional' : ''}`}
      role="article"
      aria-label={`${station.name} 气象数据`}
    >
      {/* 站点标题 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {isRegional ? (
            <MapPin className="w-4 h-4 text-primary-600" aria-hidden="true" />
          ) : (
            <span className="status-indicator status-online"></span>
          )}
          <h3 className="font-semibold text-dark-200 text-sm">{station.name}</h3>
        </div>
        {isRegional && (
          <span className="badge">
            区域平均
          </span>
        )}
      </div>

      {/* 核心温度显示 */}
      <div className="mb-3">
        <div className="flex items-baseline gap-2">
          <Thermometer className={`w-5 h-5 ${getTemperatureColor(temperature)}`} aria-hidden="true" />
          <span
            className={`text-2xl font-bold tabular-nums ${getTemperatureColor(temperature)}`}
          >
            {temperature == null ? '--' : temperature.toFixed(1)}
          </span>
          <span className="text-dark-300 text-sm">°C</span>
        </div>
      </div>

      {/* 详细信息网格 */}
      <div className="space-y-2 text-sm">
        {/* 露点温度 */}
        <div className="flex items-center justify-between">
          <span className="text-dark-400">露点温度</span>
          <span className="text-dark-200 tabular-nums">{dewPoint == null ? '--' : `${dewPoint.toFixed(1)}°C`}</span>
        </div>

        {/* 相对湿度 */}
        {isFiniteNumber(station.relative_humidity_2m) && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Droplets className={`w-4 h-4 ${getHumidityColor(station.relative_humidity_2m)}`} aria-hidden="true" />
              <span className="text-dark-400">湿度</span>
            </div>
            <span className="text-dark-200 tabular-nums">
              {station.relative_humidity_2m.toFixed(0)}%
            </span>
          </div>
        )}

        {/* 风速 */}
        {isFiniteNumber(station.wind_speed_10m) && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Wind className="w-4 h-4 text-dark-400" aria-hidden="true" />
              <span className="text-dark-400">风速</span>
            </div>
            <span className="text-dark-200 tabular-nums">{formatWindSpeed(station.wind_speed_10m)}</span>
          </div>
        )}

        {/* 云量 */}
        {isFiniteNumber(station.cloud_cover) && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Cloud className="w-4 h-4 text-dark-400" aria-hidden="true" />
              <span className="text-dark-400">云量</span>
            </div>
            <span className="text-dark-200 tabular-nums">{station.cloud_cover.toFixed(0)}%</span>
          </div>
        )}

        {/* 太阳辐射 */}
        {isFiniteNumber(station.shortwave_radiation) && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Sun className="w-4 h-4 text-primary-600" aria-hidden="true" />
              <span className="text-dark-400">太阳辐射</span>
            </div>
            <span className="text-dark-200 tabular-nums">
              {station.shortwave_radiation.toFixed(0)} W/m²
            </span>
          </div>
        )}
      </div>

      {/* 位置信息 */}
      {!isRegional && (
        <div className="mt-2.5 pt-2.5 border-t border-dark-700/60">
          <div className="text-[11px] text-dark-400 tabular-nums">
            {latitude}, {longitude}
          </div>
        </div>
      )}
    </div>
  )
}

// React.memo 优化：天气数据不变时避免重渲染
export default React.memo(WeatherCard)
