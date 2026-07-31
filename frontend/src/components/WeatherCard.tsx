import React from 'react'
import { Thermometer, Droplets, Wind, Cloud, Sun, MapPin } from 'lucide-react'
import { WeatherStationData } from '../types'

interface WeatherCardProps {
  station: WeatherStationData
  isRegional?: boolean
}

const WeatherCard: React.FC<WeatherCardProps> = ({ station, isRegional = false }) => {
  const getTemperatureColor = (temp: number) => {
    if (temp >= 30) return 'text-danger-400'
    if (temp >= 25) return 'text-warning-400'
    if (temp >= 15) return 'text-solar-400'
    if (temp >= 0) return 'text-load-400'
    return 'text-purple-400'
  }

  const getHumidityColor = (humidity?: number) => {
    if (!humidity) return 'text-dark-400'
    if (humidity >= 80) return 'text-load-400'
    if (humidity >= 60) return 'text-load-300'
    if (humidity >= 40) return 'text-dark-300'
    return 'text-dark-400'
  }

  const formatWindSpeed = (speed?: number) => {
    if (!speed) return '0 mph'
    return `${speed.toFixed(1)} mph`
  }

  return (
    <div
      className={`rounded-lg p-3 border transition-all duration-200 cursor-default backdrop-blur-sm
        ${isRegional
          ? 'bg-gradient-to-br from-load-500/10 to-load-600/5 border-load-500/30 hover:border-load-500/50'
          : 'bg-dark-700/40 border-dark-700 hover:border-dark-600 hover:shadow-lg'
        }`}
      role="article"
      aria-label={`${station.name} 气象数据`}
    >
      {/* 站点标题 */}
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          {isRegional ? (
            <MapPin className="w-4 h-4 text-load-400" aria-hidden="true" />
          ) : (
            <span className="status-indicator status-online"></span>
          )}
          <h3 className="font-medium text-white text-sm">{station.name}</h3>
        </div>
        {isRegional && (
          <span className="text-[10px] bg-load-500/20 text-load-300 px-1.5 py-0.5 rounded-md font-medium">
            区域平均
          </span>
        )}
      </div>

      {/* 核心温度显示 */}
      <div className="mb-3">
        <div className="flex items-baseline gap-2">
          <Thermometer className={`w-5 h-5 ${getTemperatureColor(station.temperature_2m)}`} aria-hidden="true" />
          <span
            className={`text-2xl font-bold tabular-nums ${getTemperatureColor(station.temperature_2m)}`}
          >
            {station.temperature_2m.toFixed(1)}
          </span>
          <span className="text-dark-300 text-sm">°C</span>
        </div>
      </div>

      {/* 详细信息网格 */}
      <div className="space-y-2 text-sm">
        {/* 露点温度 */}
        <div className="flex items-center justify-between">
          <span className="text-dark-400">露点温度</span>
          <span className="text-dark-200 tabular-nums">{station.dew_point_2m.toFixed(1)}°C</span>
        </div>

        {/* 相对湿度 */}
        {station.relative_humidity_2m && (
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
        {station.wind_speed_10m && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Wind className="w-4 h-4 text-dark-400" aria-hidden="true" />
              <span className="text-dark-400">风速</span>
            </div>
            <span className="text-dark-200 tabular-nums">{formatWindSpeed(station.wind_speed_10m)}</span>
          </div>
        )}

        {/* 云量 */}
        {station.cloud_cover && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Cloud className="w-4 h-4 text-dark-400" aria-hidden="true" />
              <span className="text-dark-400">云量</span>
            </div>
            <span className="text-dark-200 tabular-nums">{station.cloud_cover.toFixed(0)}%</span>
          </div>
        )}

        {/* 太阳辐射 */}
        {station.shortwave_radiation && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Sun className="w-4 h-4 text-warning-400" aria-hidden="true" />
              <span className="text-dark-400">太阳辐射</span>
            </div>
            <span className="text-solar-300 tabular-nums">
              {station.shortwave_radiation.toFixed(0)} W/m²
            </span>
          </div>
        )}
      </div>

      {/* 位置信息 */}
      {!isRegional && (
        <div className="mt-2.5 pt-2.5 border-t border-dark-700/60">
          <div className="text-[11px] text-dark-400 tabular-nums">
            {station.latitude.toFixed(4)}°N, {station.longitude.toFixed(4)}°W
          </div>
        </div>
      )}
    </div>
  )
}

// React.memo 优化：天气数据不变时避免重渲染
export default React.memo(WeatherCard)
