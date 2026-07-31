import React from 'react'
import { WeatherStationData } from '../types'

// ========================================
// 新英格兰地区站点坐标（来自后端 openmeteo_client.py）
// ========================================
// Boston:       42.3601°N, 71.0589°W
// Hartford:     41.7637°N, 72.6851°W
// Portland:     43.6615°N, 70.2553°W
// Manchester:   42.9956°N, 71.4548°W
// Providence:   41.8240°N, 71.4128°W
// Burlington:   44.4759°N, 73.2121°W

// ========================================
// 坐标映射参数
// ========================================
// SVG viewBox: 400 x 500
// 经度范围: -74.5 ~ -66.5 (8° 跨度)
// 纬度范围: 40.5 ~ 48.0 (7.5° 跨度)
const SVG_W = 400
const SVG_H = 500
const MIN_LON = -74.5
const MAX_LON = -66.5
const MIN_LAT = 40.5
const MAX_LAT = 48.0

const lonToX = (lon: number): number => ((lon - MIN_LON) / (MAX_LON - MIN_LON)) * SVG_W
const latToY = (lat: number): number => ((MAX_LAT - lat) / (MAX_LAT - MIN_LAT)) * SVG_H

// 新英格兰地区轮廓（简化多边形，顺时针方向）
const NEW_ENGLAND_PATH = `
  M 57.5 200
  L 137.5 200 L 150 180 L 170 153 L 185 100
  L 265 33 L 325 67 L 375 153 L 375 233
  L 365 300 L 190 327 L 185 353 L 190 400
  L 230 400 L 220 433 L 155 447 L 135 467
  L 50 467 L 50 400 L 60 353 L 57.5 333
  L 57.5 267 Z
`

// 州标签位置（简化）
const STATE_LABELS = [
  { label: 'VT', x: 85, y: 240 },
  { label: 'NH', x: 175, y: 240 },
  { label: 'ME', x: 300, y: 140 },
  { label: 'MA', x: 130, y: 370 },
  { label: 'CT', x: 80, y: 440 },
  { label: 'RI', x: 140, y: 430 },
]

// ========================================
// 温度颜色映射（数据可视化热力色阶）
// ========================================
const getTempColor = (temp: number): string => {
  if (temp >= 30) return '#ef4444' // 红
  if (temp >= 25) return '#f59e0b' // 橙
  if (temp >= 20) return '#eab308' // 黄
  if (temp >= 15) return '#10B981' // 绿 (solar-500)
  if (temp >= 10) return '#06b6d4' // 青
  if (temp >= 0) return '#3B82F6'  // 蓝 (load-500)
  return '#a855f7'                  // 紫
}

const TEMP_LEGEND = [
  { color: '#a855f7', label: '< 0°C' },
  { color: '#3B82F6', label: '0-10°C' },
  { color: '#06b6d4', label: '10-15°C' },
  { color: '#10B981', label: '15-20°C' },
  { color: '#eab308', label: '20-25°C' },
  { color: '#f59e0b', label: '25-30°C' },
  { color: '#ef4444', label: '≥ 30°C' },
]

// ========================================
// 组件 Props
// ========================================
interface WeatherMapProps {
  stations: WeatherStationData[]
  selectedStation: string | null
  onSelectStation: (name: string) => void
}

const WeatherMap: React.FC<WeatherMapProps> = ({
  stations,
  selectedStation,
  onSelectStation,
}) => {
  return (
    <div className="w-full">
      {/* 地图 SVG */}
      <div className="relative w-full" style={{ aspectRatio: '400 / 500' }}>
        <svg
          viewBox={`0 0 ${SVG_W} ${SVG_H}`}
          className="w-full h-full"
          role="img"
          aria-label="新英格兰地区气象站点分布图"
        >
          <defs>
            {/* 地图区域渐变 */}
            <linearGradient id="mapBg" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#111827" stopOpacity={0.9} />
              <stop offset="100%" stopColor="#0B0F19" stopOpacity={0.7} />
            </linearGradient>
            {/* 选中站点脉冲动画 */}
            <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="3" result="coloredBlur" />
              <feMerge>
                <feMergeNode in="coloredBlur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* 背景海洋 */}
          <rect x="0" y="0" width={SVG_W} height={SVG_H} fill="#0B0F19" rx="12" />

          {/* 经纬度网格线 */}
          <g stroke="#1F2937" strokeWidth="0.5" opacity="0.5">
            {/* 经度线 (每1度) */}
            {Array.from({ length: 9 }).map((_, i) => {
              const lon = MIN_LON + i
              const x = lonToX(lon)
              return <line key={`lon-${i}`} x1={x} y1={0} x2={x} y2={SVG_H} />
            })}
            {/* 纬度线 (每1度) */}
            {Array.from({ length: 8 }).map((_, i) => {
              const lat = MIN_LAT + i
              const y = latToY(lat)
              return <line key={`lat-${i}`} x1={0} y1={y} x2={SVG_W} y2={y} />
            })}
          </g>

          {/* 新英格兰陆地轮廓 */}
          <path
            d={NEW_ENGLAND_PATH}
            fill="url(#mapBg)"
            stroke="#374151"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />

          {/* 州标签 */}
          {STATE_LABELS.map((s) => (
            <text
              key={s.label}
              x={s.x}
              y={s.y}
              fill="#475569"
              fontSize="11"
              fontWeight="600"
              textAnchor="middle"
              className="font-mono select-none"
            >
              {s.label}
            </text>
          ))}

          {/* 站点标记 */}
          {stations.map((station) => {
            const cx = lonToX(station.longitude)
            const cy = latToY(station.latitude)
            const isSelected = selectedStation === station.name
            const tempColor = getTempColor(station.temperature_2m)
            const radius = isSelected ? 11 : 8

            return (
              <g
                key={station.name}
                className="cursor-pointer"
                onClick={() => onSelectStation(station.name)}
                role="button"
                tabIndex={0}
                aria-label={`${station.name} 站点，温度 ${station.temperature_2m.toFixed(1)}°C`}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelectStation(station.name)
                  }
                }}
              >
                {/* 选中站点脉冲环 */}
                {isSelected && (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={radius + 8}
                    fill="none"
                    stroke={tempColor}
                    strokeWidth="2"
                    opacity="0.4"
                  >
                    <animate
                      attributeName="r"
                      values={`${radius + 4};${radius + 14};${radius + 4}`}
                      dur="2s"
                      repeatCount="indefinite"
                    />
                    <animate
                      attributeName="opacity"
                      values="0.5;0;0.5"
                      dur="2s"
                      repeatCount="indefinite"
                    />
                  </circle>
                )}

                {/* 站点光晕 */}
                <circle
                  cx={cx}
                  cy={cy}
                  r={radius + 3}
                  fill={tempColor}
                  opacity={isSelected ? 0.25 : 0.12}
                />

                {/* 站点圆点 */}
                <circle
                  cx={cx}
                  cy={cy}
                  r={radius}
                  fill={tempColor}
                  stroke={isSelected ? '#ffffff' : '#111827'}
                  strokeWidth={isSelected ? 2.5 : 1.5}
                  filter={isSelected ? 'url(#glow)' : undefined}
                  className="transition-all duration-200"
                />

                {/* 站点名称标签 */}
                <text
                  x={cx}
                  y={cy - radius - 6}
                  fill={isSelected ? '#ffffff' : '#cbd5e1'}
                  fontSize="11"
                  fontWeight={isSelected ? 700 : 500}
                  textAnchor="middle"
                  className="select-none pointer-events-none"
                >
                  {station.name}
                </text>

                {/* 温度标签（选中时显示） */}
                {isSelected && (
                  <text
                    x={cx}
                    y={cy + 4}
                    fill="#ffffff"
                    fontSize="10"
                    fontWeight="700"
                    textAnchor="middle"
                    className="select-none pointer-events-none tabular-nums"
                  >
                    {station.temperature_2m.toFixed(0)}°
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {/* 温度色标图例 */}
      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="text-xs text-dark-400 font-medium mr-1">温度色标:</span>
        {TEMP_LEGEND.map((item) => (
          <div key={item.label} className="flex items-center gap-1.5">
            <span
              className="w-3 h-3 rounded-full flex-shrink-0"
              style={{ backgroundColor: item.color }}
              aria-hidden="true"
            />
            <span className="text-xs text-dark-300 tabular-nums">{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default WeatherMap
