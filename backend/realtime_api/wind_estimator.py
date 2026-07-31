"""
智能电网负荷预测系统 - 风电功率估算模块

基于物理模型的风电功率估算器，包含：
  1. 风切变高度修正 (10m → 轮毂高度)
  2. 空气密度修正 (温度 + 气压)
  3. 风机功率曲线 (分段模型)
  4. 风电场尾流损失
  5. 不确定性估计
  6. 新英格兰地区特性适配

计算公式说明:
  ┌─────────────────────────────────────────────────────────────────┐
  │                                                                 │
  │  P = 0.5 × ρ × A × v³ × Cp × η                               │
  │                                                                 │
  │  高度修正: v_h = v_ref × (h / h_ref)^α                        │
  │                                                                 │
  │  空气密度: ρ = ρ_0 × (T_0 / T) × (P / P_0)                  │
  │                                                                 │
  │  功率曲线 (分段):                                               │
  │    v < v_cut_in:  P = 0                                        │
  │    v_cut_in ≤ v < v_rated: P = P_rated × ((v-v_ci)/(v_r-v_ci))³│
  │    v_rated ≤ v < v_cut_out: P = P_rated                        │
  │    v ≥ v_cut_out: P = 0                                        │
  │                                                                 │
  │  尾流损失: P_farm = N × P_turbine × (1 - wake_loss)           │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘

参考标准:
  - IEC 61400-12-1: 风力发电机组功率特性测试
  - NREL Wind Toolkit: 美国风电资源评估
  - ISO-NE: 新英格兰独立系统运营商风电数据

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
# 风机类型定义
# ============================================================================

@dataclass
class TurbineType:
    """风力发电机组类型参数"""
    name: str
    rated_power_kw: float        # 额定功率 (kW)
    rotor_diameter_m: float      # 风轮直径 (m)
    hub_height_m: float          # 轮毂高度 (m)
    cut_in_speed: float          # 切入风速 (m/s)
    rated_speed: float           # 额定风速 (m/s)
    cut_out_speed: float         # 切出风速 (m/s)
    power_coefficient: float     # 功率系数 Cp (0-0.593)
    mechanical_efficiency: float # 机电效率 (齿轮箱+发电机)

# 预定义风机类型
TURBINE_TYPES = {
    "onshore_2mw": TurbineType(
        name="陆上 2MW",
        rated_power_kw=2000.0,
        rotor_diameter_m=80.0,
        hub_height_m=80.0,
        cut_in_speed=3.0,
        rated_speed=12.0,
        cut_out_speed=25.0,
        power_coefficient=0.40,
        mechanical_efficiency=0.92,
    ),
    "onshore_3mw": TurbineType(
        name="陆上 3MW",
        rated_power_kw=3000.0,
        rotor_diameter_m=100.0,
        hub_height_m=100.0,
        cut_in_speed=3.0,
        rated_speed=11.5,
        cut_out_speed=25.0,
        power_coefficient=0.42,
        mechanical_efficiency=0.93,
    ),
    "offshore_5mw": TurbineType(
        name="海上 5MW (NREL参考)",
        rated_power_kw=5000.0,
        rotor_diameter_m=126.0,
        hub_height_m=90.0,
        cut_in_speed=3.0,
        rated_speed=11.4,
        cut_out_speed=25.0,
        power_coefficient=0.45,
        mechanical_efficiency=0.94,
    ),
}


# ============================================================================
# 结果数据类
# ============================================================================

@dataclass
class WindForecastResult:
    """风电预测结果"""
    hourly_generation_mw: np.ndarray          # 每小时发电量 (MW)
    hourly_wind_speed_hub: np.ndarray          # 轮毂高度风速 (m/s)
    hourly_efficiency: np.ndarray              # 每小时效率 (Cp × η)
    hourly_uncertainty: np.ndarray             # 每小时不确定性 (±MW)
    hourly_air_density: np.ndarray             # 每小时空气密度 (kg/m³)
    timestamps: List[str] = field(default_factory=list)
    total_daily_mwh: float = 0.0
    capacity_factor: float = 0.0               # 容量因子
    turbine_type: str = ""
    installed_capacity_mw: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'hourly_generation_mw': [round(v, 2) for v in self.hourly_generation_mw],
            'hourly_wind_speed_hub': [round(v, 2) for v in self.hourly_wind_speed_hub],
            'hourly_efficiency': [round(v, 4) for v in self.hourly_efficiency],
            'hourly_uncertainty': [round(v, 2) for v in self.hourly_uncertainty],
            'total_daily_mwh': round(self.total_daily_mwh, 2),
            'capacity_factor': round(self.capacity_factor, 4),
            'turbine_type': self.turbine_type,
            'installed_capacity_mw': self.installed_capacity_mw,
        }


# ============================================================================
# 风电功率估算器
# ============================================================================

class WindPowerEstimator:
    """
    风电功率估算器

    基于物理模型计算风电功率，考虑：
      - 风切变高度修正 (10m → 轮毂高度)
      - 空气密度修正 (温度 + 气压)
      - 风机功率曲线 (分段模型)
      - 风电场尾流损失
      - 风机可用率

    新英格兰地区默认参数:
      - 风切变指数: 0.22 (混合地形)
      - 轮毂高度: 80m
      - 装机容量: 1500 MW
      - 尾流损失: 10%
      - 可用率: 95%
    """

    # 物理常数
    AIR_DENSITY_STC = 1.225         # 标准空气密度 (kg/m³, 15°C, 1013.25 hPa)
    TEMP_STC_K = 288.15             # 标准温度 (K, 15°C)
    PRESSURE_STC = 1013.25          # 标准气压 (hPa)
    KELVIN_OFFSET = 273.15          # 摄氏度→开尔文
    BETZ_LIMIT = 0.593              # 贝兹极限

    def __init__(
        self,
        latitude: float = 42.36,       # 纬度 (°)
        longitude: float = -71.06,     # 经度 (°)
        elevation: float = 300.0,      # 海拔 (m)
        installed_capacity_mw: float = 1500.0,
        turbine_type: str = "onshore_2mw",
        wind_shear_alpha: float = 0.22,  # 风切变指数 (新英格兰混合地形)
        wake_loss: float = 0.10,         # 尾流损失 (10%)
        availability: float = 0.95,      # 风机可用率 (95%)
        reference_height: float = 10.0,  # 参考风速高度 (m)
    ):
        """
        初始化风电估算器

        Args:
            latitude: 纬度 (°), 新英格兰 ~42°N
            longitude: 经度 (°), 新英格兰 ~-71°W
            elevation: 海拔 (m), 新英格兰平均 ~300m
            installed_capacity_mw: 装机容量 (MW)
            turbine_type: 风机类型
            wind_shear_alpha: 风切变指数 (0.15开阔~0.35森林)
            wake_loss: 尾流损失率 (0-1)
            availability: 风机可用率 (0-1)
            reference_height: 参考风速测量高度 (m)
        """
        self.lat = latitude
        self.lon = longitude
        self.elevation = elevation
        self.installed_capacity = installed_capacity_mw
        self.alpha = wind_shear_alpha
        self.wake_loss = wake_loss
        self.availability = availability
        self.ref_height = reference_height

        # 风机参数
        if turbine_type not in TURBINE_TYPES:
            raise ValueError(f"未知风机类型: {turbine_type}, 可选: {list(TURBINE_TYPES.keys())}")
        self.turbine = TURBINE_TYPES[turbine_type]
        self.turbine_type_name = turbine_type

        # 计算风机数量
        self.n_turbines = int(installed_capacity_mw * 1000 / self.turbine.rated_power_kw)
        self.hub_height = self.turbine.hub_height_m

        # 风轮扫掠面积
        self.rotor_area = math.pi * (self.turbine.rotor_diameter_m / 2) ** 2

        logger.info(f"WindPowerEstimator 初始化:")
        logger.info(f"  位置: ({latitude}°N, {longitude}°W), 海拔 {elevation}m")
        logger.info(f"  装机: {installed_capacity_mw}MW, 风机: {self.turbine.name}")
        logger.info(f"  风机数: {self.n_turbines}台 × {self.turbine.rated_power_kw}kW")
        logger.info(f"  轮毂高度: {self.hub_height}m, 风轮直径: {self.turbine.rotor_diameter_m}m")
        logger.info(f"  风切变指数: {self.alpha}, 尾流损失: {self.wake_loss:.0%}")

    # ========================================================================
    # 风切变高度修正
    # ========================================================================

    def wind_shear_correction(self, v_ref: float) -> float:
        """
        风切变高度修正

        将参考高度(10m)的风速修正到轮毂高度(80m)

        公式: v_h = v_ref × (h / h_ref)^α

        Args:
            v_ref: 参考高度风速 (m/s)

        Returns:
            轮毂高度风速 (m/s)
        """
        if v_ref < 0:
            v_ref = 0
        height_ratio = self.hub_height / self.ref_height
        v_hub = v_ref * (height_ratio ** self.alpha)
        return v_hub

    # ========================================================================
    # 空气密度修正
    # ========================================================================

    def air_density_correction(
        self,
        temperature: float,
        pressure: float = 1013.25,
    ) -> float:
        """
        空气密度修正

        基于温度和气压计算实际空气密度

        公式: ρ = ρ_0 × (T_0 / T) × (P / P_0)

        Args:
            temperature: 环境温度 (°C)
            pressure: 大气压力 (hPa)

        Returns:
            空气密度 (kg/m³)
        """
        T = self.KELVIN_OFFSET + temperature
        rho = self.AIR_DENSITY_STC * (self.TEMP_STC_K / T) * (pressure / self.PRESSURE_STC)

        # 海拔修正 (每升高 1000m, 气压降低约 12%)
        altitude_factor = math.exp(-self.elevation / 8000.0)
        rho *= altitude_factor

        return rho

    # ========================================================================
    # 风机功率曲线
    # ========================================================================

    def turbine_power_curve(self, v_hub: float, air_density: float = 1.225) -> float:
        """
        计算单台风机输出功率

        使用分段功率曲线模型:
          v < v_cut_in:       P = 0
          v_cut_in ≤ v < v_rated: P = P_rated × ((v - v_ci) / (v_rated - v_ci))³
          v_rated ≤ v < v_cut_out: P = P_rated
          v ≥ v_cut_out:      P = 0

        空气密度修正: P_actual = P × (ρ / ρ_STC)

        Args:
            v_hub: 轮毂高度风速 (m/s)
            air_density: 空气密度 (kg/m³)

        Returns:
            单台风机功率 (kW)
        """
        t = self.turbine

        # 切入风速以下或切出风速以上
        if v_hub < t.cut_in_speed or v_hub >= t.cut_out_speed:
            return 0.0

        # 额定风速以上: 输出额定功率
        if v_hub >= t.rated_speed:
            power = t.rated_power_kw
        else:
            # 切入到额定之间: 三次方关系
            ratio = (v_hub - t.cut_in_speed) / (t.rated_speed - t.cut_in_speed)
            power = t.rated_power_kw * (ratio ** 3)

        # 空气密度修正
        density_ratio = air_density / self.AIR_DENSITY_STC
        power *= density_ratio

        return power

    # ========================================================================
    # 理论风功率 (第一性原理)
    # ========================================================================

    def theoretical_power(self, v_hub: float, air_density: float = 1.225) -> float:
        """
        第一性原理计算理论风功率

        P = 0.5 × ρ × A × v³ × Cp × η

        用于验证功率曲线的合理性

        Args:
            v_hub: 轮毂高度风速 (m/s)
            air_density: 空气密度 (kg/m³)

        Returns:
            理论功率 (kW)
        """
        t = self.turbine

        if v_hub < t.cut_in_speed or v_hub >= t.cut_out_speed:
            return 0.0

        # P = 0.5 × ρ × A × v³ × Cp × η
        power_w = (
            0.5 *
            air_density *
            self.rotor_area *
            (v_hub ** 3) *
            t.power_coefficient *
            t.mechanical_efficiency
        )

        # 限制在额定功率以内
        power_w = min(power_w, t.rated_power_kw * 1000)

        return power_w / 1000.0  # kW

    # ========================================================================
    # 风电场尾流损失
    # ========================================================================

    def farm_wake_correction(
        self,
        single_turbine_power: float,
        wind_direction: float = 0.0,
    ) -> float:
        """
        风电场尾流损失修正

        P_farm = N × P_turbine × (1 - wake_loss) × availability

        尾流损失取决于:
          - 风机间距
          - 风向 (主风向尾流更严重)
          - 大气稳定度

        Args:
            single_turbine_power: 单台风机功率 (kW)
            wind_direction: 风向 (°, 0=北, 90=东)

        Returns:
            风电场总功率 (MW)
        """
        # 基础尾流损失
        actual_wake = self.wake_loss

        # 风向修正: 新英格兰主风向为西风 (270°)
        # 当风向与主排方向一致时, 尾流损失增加
        main_wind_dir = 270.0  # 新英格兰主风向
        dir_diff = abs(wind_direction - main_wind_dir)
        if dir_diff > 180:
            dir_diff = 360 - dir_diff

        # 风向偏差 < 30° 时增加 2% 尾流损失
        if dir_diff < 30:
            actual_wake += 0.02

        actual_wake = min(actual_wake, 0.20)  # 上限 20%

        # 风电场总功率
        farm_power_kw = (
            self.n_turbines *
            single_turbine_power *
            (1 - actual_wake) *
            self.availability
        )

        return farm_power_kw / 1000.0  # MW

    # ========================================================================
    # 主估算方法
    # ========================================================================

    def estimate_hourly(
        self,
        wind_speed_10m: float,
        temperature_2m: float = 15.0,
        surface_pressure: float = 1013.25,
        wind_direction: float = 270.0,
    ) -> Tuple[float, float, float, float]:
        """
        估算单小时风电功率

        Args:
            wind_speed_10m: 10m高度风速 (m/s)
            temperature_2m: 2m温度 (°C)
            surface_pressure: 地面气压 (hPa)
            wind_direction: 风向 (°, 0=北, 90=东)

        Returns:
            Tuple[发电量MW, 轮毂风速m/s, 效率, 不确定性±MW]
        """
        # 1. 风切变高度修正: 10m → 轮毂高度
        v_hub = self.wind_shear_correction(wind_speed_10m)

        # 2. 空气密度修正
        rho = self.air_density_correction(temperature_2m, surface_pressure)

        # 3. 单台风机功率 (功率曲线)
        single_power_kw = self.turbine_power_curve(v_hub, rho)

        # 4. 风电场总功率 (尾流损失 + 可用率)
        farm_power_mw = self.farm_wake_correction(single_power_kw, wind_direction)

        # 确保不超过装机容量
        farm_power_mw = min(farm_power_mw, self.installed_capacity)

        # 5. 效率计算
        if v_hub >= self.turbine.cut_in_speed and v_hub < self.turbine.cut_out_speed:
            if v_hub >= self.turbine.rated_speed:
                efficiency = self.turbine.power_coefficient * self.turbine.mechanical_efficiency
            else:
                # 部分负载效率 = Cp × η × (实际功率/理论最大功率)
                theoretical_max = 0.5 * rho * self.rotor_area * (v_hub ** 3) / 1000  # kW
                if theoretical_max > 0:
                    actual_cp = single_power_kw / theoretical_max
                    efficiency = actual_cp * self.turbine.mechanical_efficiency
                else:
                    efficiency = 0.0
        else:
            efficiency = 0.0

        # 6. 不确定性估计
        # 主要来源: 风速预测误差 ±1.5 m/s (24h), v³ 放大效应
        # δP/P ≈ 3 × δv/v
        if v_hub > 0.5 and farm_power_mw > 0:
            wind_speed_error = 1.5  # m/s (24h预测误差)
            relative_error = 3 * wind_speed_error / v_hub  # v³ 放大
            relative_error = min(relative_error, 0.30)  # 上限 30%
            uncertainty = farm_power_mw * relative_error
        else:
            uncertainty = 0.0

        return farm_power_mw, v_hub, efficiency, uncertainty

    def estimate_24h(
        self,
        weather_df: pd.DataFrame,
        start_time: Optional[datetime] = None,
    ) -> WindForecastResult:
        """
        估算未来24小时风电功率

        Args:
            weather_df: 气象数据 DataFrame
                必须包含: timestamp, wind_speed_10m
                可选包含: temperature_2m, surface_pressure, wind_direction_10m
            start_time: 起始时间 (默认当前时间)

        Returns:
            WindForecastResult
        """
        if start_time is None:
            start_time = datetime.now()

        # 确保必要列存在
        required = ["wind_speed_10m"]
        for col in required:
            if col not in weather_df.columns:
                logger.warning(f"缺少列 {col}，使用默认值")
                weather_df[col] = 0.0

        # 可选列默认值
        if "temperature_2m" not in weather_df.columns:
            weather_df["temperature_2m"] = 15.0
        if "surface_pressure" not in weather_df.columns:
            weather_df["surface_pressure"] = 1013.25
        if "wind_direction_10m" not in weather_df.columns:
            weather_df["wind_direction_10m"] = 270.0

        # 按预测时间窗口对齐
        if "timestamp" in weather_df.columns:
            df_all = weather_df.copy()
            df_all["timestamp"] = pd.to_datetime(df_all["timestamp"])

            aligned_rows = []
            for i in range(24):
                target_time = start_time + timedelta(hours=i)
                window_start = target_time - timedelta(minutes=30)
                window_end = target_time + timedelta(minutes=30)

                mask = (df_all["timestamp"] >= window_start) & (df_all["timestamp"] <= window_end)

                if mask.any():
                    row_data = {
                        "timestamp": target_time,
                        "wind_speed_10m": float(df_all.loc[mask, "wind_speed_10m"].mean()),
                        "temperature_2m": float(df_all.loc[mask, "temperature_2m"].mean()) if "temperature_2m" in df_all.columns else 15.0,
                        "surface_pressure": float(df_all.loc[mask, "surface_pressure"].mean()) if "surface_pressure" in df_all.columns else 1013.25,
                        "wind_direction_10m": float(df_all.loc[mask, "wind_direction_10m"].mean()) if "wind_direction_10m" in df_all.columns else 270.0,
                    }
                else:
                    if len(df_all) > 0:
                        time_diffs = (df_all["timestamp"] - pd.Timestamp(target_time)).abs()
                        nearest_idx = time_diffs.idxmin()
                        row_data = {
                            "timestamp": target_time,
                            "wind_speed_10m": float(df_all.loc[nearest_idx, "wind_speed_10m"]),
                            "temperature_2m": float(df_all.loc[nearest_idx, "temperature_2m"]) if "temperature_2m" in df_all.columns else 15.0,
                            "surface_pressure": float(df_all.loc[nearest_idx, "surface_pressure"]) if "surface_pressure" in df_all.columns else 1013.25,
                            "wind_direction_10m": float(df_all.loc[nearest_idx, "wind_direction_10m"]) if "wind_direction_10m" in df_all.columns else 270.0,
                        }
                    else:
                        row_data = {
                            "timestamp": target_time,
                            "wind_speed_10m": 0.0,
                            "temperature_2m": 15.0,
                            "surface_pressure": 1013.25,
                            "wind_direction_10m": 270.0,
                        }
                aligned_rows.append(row_data)

            df = pd.DataFrame(aligned_rows)
            timestamps = [r["timestamp"] for r in aligned_rows]
        else:
            df = weather_df.tail(24).copy()
            timestamps = [start_time + timedelta(hours=i) for i in range(24)]

        # 逐小时计算
        hourly_gen = np.zeros(24)
        hourly_v_hub = np.zeros(24)
        hourly_eff = np.zeros(24)
        hourly_unc = np.zeros(24)
        hourly_rho = np.zeros(24)
        ts_strings = []

        for i in range(24):
            row = df.iloc[i]
            ts = timestamps[i]

            power, v_hub, eff, unc = self.estimate_hourly(
                wind_speed_10m=float(row.get("wind_speed_10m", 0)),
                temperature_2m=float(row.get("temperature_2m", 15)),
                surface_pressure=float(row.get("surface_pressure", 1013.25)),
                wind_direction=float(row.get("wind_direction_10m", 270)),
            )

            hourly_gen[i] = power
            hourly_v_hub[i] = v_hub
            hourly_eff[i] = eff
            hourly_unc[i] = unc
            ts_strings.append(ts.isoformat())

            # 空气密度记录
            hourly_rho[i] = self.air_density_correction(
                float(row.get("temperature_2m", 15)),
                float(row.get("surface_pressure", 1013.25)),
            )

        # 汇总
        total_mwh = float(hourly_gen.sum())
        capacity_factor = total_mwh / (self.installed_capacity * 24)

        logger.info(
            f"风电估算完成: 日发电 {total_mwh:.1f} MWh, "
            f"容量因子 {capacity_factor:.1%}, "
            f"平均轮毂风速 {hourly_v_hub.mean():.1f} m/s"
        )

        return WindForecastResult(
            hourly_generation_mw=hourly_gen,
            hourly_wind_speed_hub=hourly_v_hub,
            hourly_efficiency=hourly_eff,
            hourly_uncertainty=hourly_unc,
            hourly_air_density=hourly_rho,
            timestamps=ts_strings,
            total_daily_mwh=total_mwh,
            capacity_factor=capacity_factor,
            turbine_type=self.turbine.name,
            installed_capacity_mw=self.installed_capacity,
        )

    # ========================================================================
    # 功率曲线生成
    # ========================================================================

    def power_curve(
        self,
        speed_range: Tuple[float, float] = (0, 30),
        steps: int = 60,
    ) -> pd.DataFrame:
        """
        生成风机功率曲线数据

        Args:
            speed_range: 风速范围 (m/s)
            steps: 采样点数

        Returns:
            DataFrame: 风速 vs 功率 vs 效率
        """
        speeds = np.linspace(speed_range[0], speed_range[1], steps)

        powers_curve = []
        powers_theory = []
        efficiencies = []

        for v in speeds:
            p_curve = self.turbine_power_curve(v)
            p_theory = self.theoretical_power(v)
            if v > 0 and p_theory > 0:
                eff = p_curve / p_theory * self.turbine.mechanical_efficiency
            else:
                eff = 0.0

            powers_curve.append(p_curve)
            powers_theory.append(p_theory)
            efficiencies.append(eff)

        return pd.DataFrame({
            "wind_speed_ms": speeds,
            "power_curve_kw": powers_curve,
            "power_theoretical_kw": powers_theory,
            "efficiency": efficiencies,
        })

    # ========================================================================
    # 兼容旧接口
    # ========================================================================

    def estimate(self, wind_speed: float, temperature: float = 15.0) -> float:
        """兼容旧接口的简化估算"""
        power, _, _, _ = self.estimate_hourly(
            wind_speed_10m=wind_speed,
            temperature_2m=temperature,
        )
        return power


# ============================================================================
# 使用示例
# ============================================================================

def demo():
    """演示风电估算器使用"""
    print("=" * 60)
    print("风电功率估算模块演示")
    print("=" * 60)

    # 1. 创建估算器
    print("\n[1] 创建估算器...")
    estimator = WindPowerEstimator(
        latitude=42.36,
        longitude=-71.06,
        elevation=300.0,
        installed_capacity_mw=1500.0,
        turbine_type="onshore_2mw",
    )

    # 2. 生成模拟气象数据
    print("\n[2] 生成模拟气象数据...")
    now = datetime.now()
    timestamps = [now + timedelta(hours=i) for i in range(24)]

    # 模拟风速: 夜间更强, 白天较弱 (新英格兰典型)
    wind_speeds = []
    for ts in timestamps:
        base = 7.0
        # 夜间增强 (0-6时, 20-23时)
        if ts.hour < 6 or ts.hour >= 20:
            base += 3.0
        # 随机波动
        base += np.random.normal(0, 1.0)
        wind_speeds.append(max(0, base))

    weather_df = pd.DataFrame({
        "timestamp": timestamps,
        "wind_speed_10m": wind_speeds,
        "temperature_2m": [10 + 5 * math.sin(ts.hour * math.pi / 12) for ts in timestamps],
        "surface_pressure": [1013 + np.random.normal(0, 3) for _ in timestamps],
        "wind_direction_10m": [240 + np.random.normal(0, 20) for _ in timestamps],
    })

    # 3. 24小时预测
    print("\n[3] 24小时风电功率预测...")
    result = estimator.estimate_24h(weather_df)

    print(f"\n  日总发电: {result.total_daily_mwh:.1f} MWh")
    print(f"  容量因子: {result.capacity_factor:.1%}")
    print(f"  风机类型: {result.turbine_type}")

    print(f"\n  逐小时发电 (MW):")
    for i in range(24):
        print(f"    [{i:02d}:00] {result.hourly_generation_mw[i]:6.1f} MW "
              f"(v_hub={result.hourly_wind_speed_hub[i]:4.1f} m/s, "
              f"η={result.hourly_efficiency[i]:.3f}, "
              f"ρ={result.hourly_air_density[i]:.3f} kg/m³)")

    # 4. 功率曲线
    print("\n[4] 功率曲线 (关键点):")
    curve = estimator.power_curve()
    key_speeds = [0, 3, 6, 9, 12, 15, 20, 25, 26]
    for v in key_speeds:
        idx = curve["wind_speed_ms"].sub(v).abs().idxmin()
        row = curve.iloc[idx]
        print(f"  v={row['wind_speed_ms']:5.1f} m/s → "
              f"P={row['power_curve_kw']:7.0f} kW "
              f"(理论={row['power_theoretical_kw']:7.0f} kW)")

    # 5. 多风机类型对比
    print("\n[5] 多风机类型对比:")
    for ttype in TURBINE_TYPES:
        est = WindPowerEstimator(turbine_type=ttype, installed_capacity_mw=1500.0)
        r = est.estimate_24h(weather_df)
        print(f"  {r.turbine_type:20s}: {r.total_daily_mwh:8.1f} MWh, CF={r.capacity_factor:.1%}")

    return estimator, result


if __name__ == "__main__":
    demo()
