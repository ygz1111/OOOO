"""
智能电网负荷预测系统 - 光伏发电估算模块

基于物理模型的光伏发电量估算器，包含：
  1. 太阳位置计算（高度角、方位角、赤纬）
  2. 面板入射角修正
  3. 温度损失修正
  4. 云量遮挡损失
  5. 大气透射率
  6. 多种光伏组件类型
  7. 不确定性估计
  8. 新英格兰地区特性适配

计算公式说明:
  ┌─────────────────────────────────────────────────────────────────┐
  │                                                                 │
  │  PV_output = G_eff × A × η_STC × η_temp × η_inv × η_other     │
  │                                                                 │
  │  G_eff = G_h × R_beam × cos(θ) + G_diffuse                   │
  │                                                                 │
  │  η_temp = 1 + γ_T × (T_cell - 25)                             │
  │  T_cell = T_amb + (NOCT - 20)/800 × G                         │
  │                                                                 │
  │  δ = 23.45° × sin(2π(284+N)/365)   (太阳赤纬)                 │
  │  ω = 15° × (t_solar - 12)           (时角)                    │
  │  α = arcsin(sin(δ)sin(φ) + cos(δ)cos(φ)cos(ω))  (高度角)      │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘

依赖: numpy, pandas

作者: 毕业设计项目
"""

import os
import math
import logging
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# ============================================================================
# 日志
# ============================================================================
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )


# ============================================================================
# 光伏组件类型定义
# ============================================================================

@dataclass
class PanelType:
    """光伏组件类型参数"""
    name: str
    efficiency_stc: float        # 标准测试条件效率 (STC: 1000W/m², 25°C, AM1.5)
    temperature_coeff: float     # 温度系数 γ_T (1/°C, 负值)
    noct: float                  # 标称工作温度 (°C)
    degradation_rate: float      # 年衰减率 (%/年)

# 预定义组件类型
PANEL_TYPES = {
    "monocrystalline": PanelType(
        name="单晶硅",
        efficiency_stc=0.21,
        temperature_coeff=-0.0035,
        noct=45.0,
        degradation_rate=0.5,
    ),
    "polycrystalline": PanelType(
        name="多晶硅",
        efficiency_stc=0.18,
        temperature_coeff=-0.0040,
        noct=46.0,
        degradation_rate=0.6,
    ),
    "cdte": PanelType(
        name="碲化镉薄膜",
        efficiency_stc=0.17,
        temperature_coeff=-0.0025,
        noct=44.0,
        degradation_rate=0.4,
    ),
    "cigs": PanelType(
        name="铜铟镓硒薄膜",
        efficiency_stc=0.15,
        temperature_coeff=-0.0030,
        noct=45.0,
        degradation_rate=0.5,
    ),
}


# ============================================================================
# 结果数据类
# ============================================================================

@dataclass
class PVForecastResult:
    """光伏预测结果"""
    hourly_generation_mw: np.ndarray          # 每小时发电量 (MW)
    hourly_efficiency: np.ndarray              # 每小时效率
    hourly_uncertainty: np.ndarray              # 每小时不确定性 (±MW)
    sun_elevation: np.ndarray                  # 太阳高度角
    cell_temperature: np.ndarray              # 组件温度
    timestamps: List[str] = field(default_factory=list)
    total_daily_mwh: float = 0.0
    capacity_factor: float = 0.0              # 容量因子
    panel_type: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'hourly_generation_mw': [round(v, 2) for v in self.hourly_generation_mw],
            'hourly_efficiency': [round(v, 4) for v in self.hourly_efficiency],
            'hourly_uncertainty': [round(v, 2) for v in self.hourly_uncertainty],
            'total_daily_mwh': round(self.total_daily_mwh, 2),
            'capacity_factor': round(self.capacity_factor, 4),
            'panel_type': self.panel_type,
        }


# ============================================================================
# 光伏发电估算器
# ============================================================================

class PVGenerationEstimator:
    """
    光伏发电估算器

    基于物理模型计算光伏发电量，考虑：
      - 太阳位置（赤纬、高度角、方位角）
      - 面板倾角和方位角
      - 温度损失
      - 云量遮挡
      - 大气透射
      - 逆变器效率
      - 系统损耗

    新英格兰地区默认参数:
      - 纬度: 42°N (Boston)
      - 经度: -71°W
      - 海拔: 50m
      - 最佳倾角: 42° (≈纬度)
      - 面板朝向: 正南 (方位角=180°)
      - 装机容量: 500MW (公用事业级)
    """

    # 物理常数
    SOLAR_CONSTANT = 1367.0      # 太阳常数 W/m²
    STEFAN_BOLTZMANN = 5.67e-8  # 斯特凡-玻尔兹曼常数

    def __init__(
        self,
        latitude: float = 42.36,       # 纬度 (°)
        longitude: float = -71.06,     # 经度 (°)
        elevation: float = 50.0,       # 海拔 (m)
        installed_capacity_mw: float = 500.0,
        panel_type: str = "monocrystalline",
        tilt_angle: float = 42.0,      # 面板倾角 (°)
        azimuth_angle: float = 180.0,  # 面板方位角 (°, 正南=180)
        inverter_efficiency: float = 0.97,
        system_losses: float = 0.14,   # 线路、匹配等损耗
        timezone_offset: float = -5,   # UTC偏移 (新英格兰 EST=-5)
    ):
        """
        初始化光伏估算器

        Args:
            latitude: 纬度 (°), 新英格兰 ~42°N
            longitude: 经度 (°), 新英格兰 ~-71°W
            elevation: 海拔 (m)
            installed_capacity_mw: 装机容量 (MW)
            panel_type: 组件类型
            tilt_angle: 面板倾角 (°), ≈纬度为最佳
            azimuth_angle: 方位角 (°, 正南=180°)
            inverter_efficiency: 逆变器效率
            system_losses: 系统损耗率 (0.14 = 14%)
            timezone_offset: UTC时区偏移
        """
        self.lat = math.radians(latitude)
        self.lon = longitude
        self.elevation = elevation
        self.installed_capacity = installed_capacity_mw
        self.tilt = math.radians(tilt_angle)
        self.azimuth = math.radians(azimuth_angle)
        self.inverter_eff = inverter_efficiency
        self.system_losses = system_losses
        self.tz_offset = timezone_offset

        # 组件参数
        if panel_type not in PANEL_TYPES:
            raise ValueError(f"未知组件类型: {panel_type}, 可选: {list(PANEL_TYPES.keys())}")
        self.panel = PANEL_TYPES[panel_type]
        self.panel_type_name = panel_type

        logger.info(f"PVGenerationEstimator 初始化:")
        logger.info(f"  位置: ({latitude}°N, {longitude}°W), 海拔 {elevation}m")
        logger.info(f"  装机: {installed_capacity_mw}MW, 组件: {self.panel.name}")
        logger.info(f"  倾角: {tilt_angle}°, 方位: {azimuth_angle}°")

    # ========================================================================
    # 太阳位置计算
    # ========================================================================

    def solar_declination(self, day_of_year: int) -> float:
        """
        计算太阳赤纬角

        公式: δ = 23.45° × sin(2π × (284 + N) / 365)

        Args:
            day_of_year: 年内第几天 (1-366)

        Returns:
            赤纬角 (弧度)
        """
        declination_deg = 23.45 * math.sin(
            2 * math.pi * (284 + day_of_year) / 365
        )
        return math.radians(declination_deg)

    def hour_angle(self, hour: float) -> float:
        """
        计算时角

        公式: ω = 15° × (太阳时 - 12)
        太阳时 ≈ 标准时 + (经度 - 时区中心经度)/15

        Args:
            hour: 当地标准时间 (小时)

        Returns:
            时角 (弧度)
        """
        # 经度修正 (新英格兰时区中心 = -75°W)
        lon_correction = (self.lon - (-75.0)) / 15.0
        solar_time = hour + lon_correction
        hour_angle_deg = 15.0 * (solar_time - 12)
        return math.radians(hour_angle_deg)

    def solar_elevation(self, declination: float, ha: float) -> float:
        """
        计算太阳高度角

        公式: sin(α) = sin(δ)sin(φ) + cos(δ)cos(φ)cos(ω)

        Args:
            declination: 赤纬 (弧度)
            ha: 时角 (弧度)

        Returns:
            高度角 (弧度, 0~π/2)
        """
        sin_alpha = (
            math.sin(declination) * math.sin(self.lat) +
            math.cos(declination) * math.cos(self.lat) * math.cos(ha)
        )
        sin_alpha = max(-1.0, min(1.0, sin_alpha))
        return max(0.0, math.asin(sin_alpha))

    def solar_azimuth(self, declination: float, ha: float, elevation: float) -> float:
        """
        计算太阳方位角

        公式:
          cos(γ) = [sin(δ)cos(φ) - cos(δ)sin(φ)cos(ω)] / cos(α)

        Args:
            declination: 赤纬 (弧度)
            ha: 时角 (弧度)
            elevation: 高度角 (弧度)

        Returns:
            方位角 (弧度, 正南=0, 西为正)
        """
        cos_alpha = math.cos(elevation)
        if cos_alpha < 0.01:
            return 0.0

        cos_az = (
            math.sin(declination) * math.cos(self.lat) -
            math.cos(declination) * math.sin(self.lat) * math.cos(ha)
        ) / cos_alpha
        cos_az = max(-1.0, min(1.0, cos_az))

        azimuth = math.acos(cos_az)

        # 上午方位角为东 (负)，下午为西 (正)
        if math.sin(ha) > 0:
            azimuth = 2 * math.pi - azimuth

        return azimuth

    # ========================================================================
    # 入射角计算
    # ========================================================================

    def incidence_angle(
        self,
        solar_elev: float,
        solar_az: float,
    ) -> float:
        """
        计算阳光在面板上的入射角

        公式:
          cos(θ) = cos(α)cos(γ_s - γ_p)sin(β) + sin(α)cos(β)

        其中:
          α = 太阳高度角
          γ_s = 太阳方位角
          γ_p = 面板方位角
          β = 面板倾角

        Args:
            solar_elev: 太阳高度角 (弧度)
            solar_az: 太阳方位角 (弧度)

        Returns:
            入射角余弦值 (0~1)
        """
        cos_incidence = (
            math.cos(solar_elev) *
            math.cos(solar_az - self.azimuth) *
            math.sin(self.tilt) +
            math.sin(solar_elev) * math.cos(self.tilt)
        )
        return max(0.0, cos_incidence)

    # ========================================================================
    # 温度损失
    # ========================================================================

    def cell_temperature(
        self,
        ambient_temp: float,
        irradiance: float,
    ) -> float:
        """
        计算光伏组件温度

        公式: T_cell = T_amb + (NOCT - 20) / 800 × G

        Args:
            ambient_temp: 环境温度 (°C)
            irradiance: 面板面辐照度 (W/m²)

        Returns:
            组件温度 (°C)
        """
        return ambient_temp + (self.panel.noct - 20) / 800.0 * irradiance

    def temperature_efficiency(self, cell_temp: float) -> float:
        """
        计算温度效率修正

        公式: η_temp = 1 + γ_T × (T_cell - 25)

        硅基组件温度升高会降低效率 (γ_T < 0)

        Args:
            cell_temp: 组件温度 (°C)

        Returns:
            效率修正系数 (通常 < 1.0)
        """
        return 1.0 + self.panel.temperature_coeff * (cell_temp - 25.0)

    # ========================================================================
    # 云量遮挡损失
    # ========================================================================

    def cloud_attenuation(self, cloud_cover: float) -> float:
        """
        计算云量遮挡系数

        使用 Kasten-Czeplak 模型:
          G_clear = G_0 × τ_atm
          G_cloud = G_clear × (1 - 0.75 × (C/8)^3.4)

        简化版本:
          f_cloud = 1 - 0.72 × (cloud_cover/100)^2

        Args:
            cloud_cover: 云量 (0-100%)

        Returns:
            透过率 (0~1)
        """
        c = max(0.0, min(100.0, cloud_cover)) / 100.0
        # Kasten 模型简化
        return 1.0 - 0.72 * (c ** 2)

    # ========================================================================
    # 大气透射率
    # ========================================================================

    def atmospheric_transmittance(self, solar_elev: float) -> float:
        """
        计算晴空大气透射率

        使用 Hottel (1976) 模型:
          τ = a0 + a1 × exp(-k/sin(α))

        海拔修正: k = k0 × exp(-h/8000)

        Args:
            solar_elev: 太阳高度角 (弧度)

        Returns:
            大气透射率 (0~1)
        """
        sin_alpha = math.sin(solar_elev)
        if sin_alpha < 0.01:
            return 0.0

        # Hottel 模型参数 (中纬度夏季)
        a0 = 0.97
        a1 = 0.21
        k0 = 0.3955

        # 海拔修正
        k = k0 * math.exp(-self.elevation / 8000.0)

        tau = a0 + a1 * math.exp(-k / sin_alpha)
        return max(0.0, min(1.0, tau))

    # ========================================================================
    # 晴空辐照度
    # ========================================================================

    def clear_sky_irradiance(self, solar_elev: float) -> float:
        """
        计算晴空条件下的法向直射辐照度 (DNI)

        公式: G_clear = SOLAR_CONSTANT × τ_atm × sin(α)

        Args:
            solar_elev: 太阳高度角 (弧度)

        Returns:
            晴空水平面辐照度 (W/m²)
        """
        sin_alpha = math.sin(solar_elev)
        if sin_alpha <= 0:
            return 0.0

        tau = self.atmospheric_transmittance(solar_elev)
        return self.SOLAR_CONSTANT * tau * sin_alpha

    # ========================================================================
    # 主估算方法
    # ========================================================================

    def estimate_hourly(
        self,
        shortwave_radiation: float,
        cloud_cover: float,
        temperature_2m: float,
        timestamp: Optional[datetime] = None,
    ) -> Tuple[float, float, float]:
        """
        估算单小时光伏发电量

        Args:
            shortwave_radiation: Open-Meteo短波辐射 (W/m²)
            cloud_cover: 云量 (0-100%)
            temperature_2m: 2m温度 (°C)
            timestamp: 时间戳 (用于太阳位置计算)

        Returns:
            Tuple[发电量MW, 效率, 不确定性±MW]
        """
        if timestamp is None:
            timestamp = datetime.now()

        # 1. 太阳位置
        day_of_year = timestamp.timetuple().tm_yday
        hour = timestamp.hour + timestamp.minute / 60.0

        declination = self.solar_declination(day_of_year)
        ha = self.hour_angle(hour)
        solar_elev = self.solar_elevation(declination, ha)

        # 夜间
        if solar_elev <= 0.01:
            return 0.0, 0.0, 0.0

        # 2. 晴空辐照度
        g_clear = self.clear_sky_irradiance(solar_elev)

        # 3. 实际辐照度（优先使用观测值）
        if shortwave_radiation is not None:
            g_horizontal = max(0.0, float(shortwave_radiation))
        else:
            # 使用晴空模型 + 云量修正
            cloud_factor = self.cloud_attenuation(cloud_cover)
            g_horizontal = g_clear * cloud_factor

        # 4. 入射角修正
        solar_az = self.solar_azimuth(declination, ha, solar_elev)
        cos_theta = self.incidence_angle(solar_elev, solar_az)

        # 5. 面板面辐照度 (直射 + 散射)
        # 散射约占总辐射的 20% (阴天更高)
        diffuse_fraction = 0.2 + 0.6 * (cloud_cover / 100.0) ** 2
        diffuse_fraction = min(0.95, diffuse_fraction)

        beam_on_panel = g_horizontal * (1 - diffuse_fraction) * cos_theta
        diffuse_on_panel = g_horizontal * diffuse_fraction * (1 + math.cos(self.tilt)) / 2

        g_panel = beam_on_panel + diffuse_on_panel

        # 6. 组件温度和效率
        t_cell = self.cell_temperature(temperature_2m, g_panel)
        eta_temp = self.temperature_efficiency(t_cell)

        # 7. 总效率
        # η_total = η_STC × η_temp × η_inverter × (1 - losses)
        eta_total = (
            self.panel.efficiency_stc *
            eta_temp *
            self.inverter_eff *
            (1 - self.system_losses)
        )

        # 8. 发电量 (MW)
        # P = G_panel × (capacity_STC / G_STC) × η_ratio
        # capacity_STC = installed_capacity (MW, at 1000W/m²)
        # 实际输出 = (G_panel / 1000) × installed_capacity × (eta_total / eta_STC)
        # 因为 installed_capacity 已经包含了 eta_STC 的面板面积
        power_mw = (g_panel / 1000.0) * self.installed_capacity * (eta_total / self.panel.efficiency_stc)
        power_mw = max(0.0, power_mw)

        # 9. 不确定性估计
        # 主要来源: 云量预测误差 ±15%, 温度误差 ±2°C, 辐射测量误差 ±5%
        uncertainty = power_mw * 0.15  # ±15%

        return power_mw, eta_total, uncertainty

    def estimate_24h(
        self,
        weather_df: pd.DataFrame,
        start_time: Optional[datetime] = None,
    ) -> PVForecastResult:
        """
        估算未来24小时光伏发电量

        Args:
            weather_df: 气象数据 DataFrame
                必须包含: timestamp, shortwave_radiation, cloud_cover, temperature_2m
            start_time: 起始时间 (默认当前时间)

        Returns:
            PVForecastResult
        """
        if start_time is None:
            start_time = datetime.now()

        # 确保列存在
        required = ["shortwave_radiation", "cloud_cover", "temperature_2m"]
        for col in required:
            if col not in weather_df.columns:
                logger.warning(f"缺少列 {col}，使用默认值")
                weather_df[col] = 0.0

        # 取最后24行（未来24小时）
        df = weather_df.tail(24).copy()

        # 如果有 timestamp 列，使用它；否则构造
        if "timestamp" in df.columns:
            timestamps = pd.to_datetime(df["timestamp"]).tolist()
        else:
            timestamps = [start_time + timedelta(hours=i) for i in range(24)]

        hourly_gen = np.zeros(24)
        hourly_eff = np.zeros(24)
        hourly_unc = np.zeros(24)
        sun_elev = np.zeros(24)
        cell_temps = np.zeros(24)
        ts_strings = []

        for i in range(24):
            row = df.iloc[i]
            ts = timestamps[i]

            power, eff, unc = self.estimate_hourly(
                shortwave_radiation=float(row.get("shortwave_radiation", 0)),
                cloud_cover=float(row.get("cloud_cover", 0)),
                temperature_2m=float(row.get("temperature_2m", 20)),
                timestamp=ts,
            )

            hourly_gen[i] = power
            hourly_eff[i] = eff
            hourly_unc[i] = unc
            ts_strings.append(ts.isoformat())

            # 记录太阳高度角和组件温度（用于诊断）
            day_of_year = ts.timetuple().tm_yday
            hour = ts.hour + ts.minute / 60.0
            declination = self.solar_declination(day_of_year)
            ha = self.hour_angle(hour)
            sun_elev[i] = math.degrees(self.solar_elevation(declination, ha))
            cell_temps[i] = self.cell_temperature(
                float(row.get("temperature_2m", 20)),
                max(float(row.get("shortwave_radiation", 0)), 0)
            )

        # 汇总
        total_mwh = float(hourly_gen.sum())
        capacity_factor = total_mwh / (self.installed_capacity * 24)

        logger.info(
            f"光伏估算完成: 日发电 {total_mwh:.1f} MWh, "
            f"容量因子 {capacity_factor:.1%}"
        )

        return PVForecastResult(
            hourly_generation_mw=hourly_gen,
            hourly_efficiency=hourly_eff,
            hourly_uncertainty=hourly_unc,
            sun_elevation=sun_elev,
            cell_temperature=cell_temps,
            timestamps=ts_strings,
            total_daily_mwh=total_mwh,
            capacity_factor=capacity_factor,
            panel_type=self.panel.name,
        )

    # ========================================================================
    # 效率曲线
    # ========================================================================

    def efficiency_curve(
        self,
        irradiance_range: Tuple[float, float] = (0, 1200),
        steps: int = 25,
        temperature: float = 25.0,
    ) -> pd.DataFrame:
        """
        生成发电效率曲线

        Args:
            irradiance_range: 辐照度范围 (W/m²)
            steps: 采样点数
            temperature: 固定温度 (°C)

        Returns:
            DataFrame: 辐照度 vs 效率 vs 发电量
        """
        irradiance_values = np.linspace(
            irradiance_range[0], irradiance_range[1], steps
        )

        efficiencies = []
        powers = []
        for g in irradiance_values:
            t_cell = self.cell_temperature(temperature, g)
            eta_temp = self.temperature_efficiency(t_cell)
            eta_total = (
                self.panel.efficiency_stc *
                eta_temp *
                self.inverter_eff *
                (1 - self.system_losses)
            )
            power = (g / 1000.0) * self.installed_capacity * (eta_total / self.panel.efficiency_stc)
            efficiencies.append(eta_total)
            powers.append(power)

        return pd.DataFrame({
            "irradiance_w_m2": irradiance_values,
            "efficiency": efficiencies,
            "power_mw": powers,
        })

    # ========================================================================
    # 兼容旧接口 (SolarEstimator.estimate)
    # ========================================================================

    def estimate(self, radiation: float, temperature: float = 25.0) -> float:
        """兼容旧接口的简化估算"""
        power, _, _ = self.estimate_hourly(
            shortwave_radiation=radiation,
            cloud_cover=0,
            temperature_2m=temperature,
            timestamp=datetime.now(),
        )
        return power


# ============================================================================
# 使用示例
# ============================================================================

def demo():
    """演示光伏估算器使用"""
    print("=" * 60)
    print("光伏发电估算模块演示")
    print("=" * 60)

    # 1. 创建估算器 (新英格兰地区参数)
    print("\n[1] 创建估算器...")
    estimator = PVGenerationEstimator(
        latitude=42.36,
        longitude=-71.06,
        elevation=50.0,
        installed_capacity_mw=500.0,
        panel_type="monocrystalline",
        tilt_angle=42.0,
    )

    # 2. 生成模拟气象数据
    print("\n[2] 生成模拟气象数据...")
    now = datetime.now()
    timestamps = [now + timedelta(hours=i) for i in range(24)]
    weather_df = pd.DataFrame({
        "timestamp": timestamps,
        "shortwave_radiation": [
            max(0, 800 * math.sin((ts.hour - 6) * math.pi / 12))
            if 6 <= ts.hour <= 18 else 0
            for ts in timestamps
        ],
        "cloud_cover": [20 + 10 * math.sin(i) for i in range(24)],
        "temperature_2m": [15 + 10 * math.sin((ts.hour - 6) * math.pi / 12) for ts in timestamps],
    })

    # 3. 24小时预测
    print("\n[3] 24小时光伏发电预测...")
    result = estimator.estimate_24h(weather_df)

    print(f"\n  日总发电: {result.total_daily_mwh:.1f} MWh")
    print(f"  容量因子: {result.capacity_factor:.1%}")
    print(f"  组件类型: {result.panel_type}")

    print(f"\n  逐小时发电 (MW):")
    for i in range(24):
        print(f"    [{i:02d}:00] {result.hourly_generation_mw[i]:6.1f} MW "
              f"(η={result.hourly_efficiency[i]:.3f}, "
              f"α={result.sun_elevation[i]:5.1f}°, "
              f"T={result.cell_temperature[i]:4.1f}°C)")

    # 4. 效率曲线
    print("\n[4] 效率曲线:")
    curve = estimator.efficiency_curve()
    print(curve.to_string(index=False))

    # 5. 多组件对比
    print("\n[5] 多组件类型对比:")
    for ptype in PANEL_TYPES:
        est = PVGenerationEstimator(panel_type=ptype)
        r = est.estimate_24h(weather_df)
        print(f"  {r.panel_type:12s}: {r.total_daily_mwh:7.1f} MWh, CF={r.capacity_factor:.1%}")

    return estimator, result


if __name__ == "__main__":
    demo()
