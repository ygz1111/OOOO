"""
智能电网负荷预测系统 - 净负荷计算模块

功能:
  1. 基础净负荷计算: 净负荷 = 总负荷 - 光伏发电
  2. 电网约束处理: 最小/最大出力、爬坡率、传输容量
  3. 调度策略: 削峰填谷、经济调度、储能充放电
  4. 多时间尺度: 小时级/分钟级预测
  5. 储能系统: SOC管理、充放电建议
  6. 经济调度: 发电成本估算、市场套利

核心公式:
  ┌─────────────────────────────────────────────────────────────────┐
  │  Net_Load = Load_Forecast - PV_Generation                      │
  │                                                                 │
  │  削峰: SOC_discharge = min(peak_excess, P_max_discharge)      │
  │  填谷: SOC_charge = min(valley_deficit, P_max_charge)         │
  │                                                                 │
  │  Cost = Σ(Gen_i × Cost_i) + Storage_Cycle_Cost                │
  │  Revenue = Σ(Export_i × Price_i) - Σ(Import_i × Price_i)     │
  └─────────────────────────────────────────────────────────────────┘

依赖: numpy, pandas

作者: 毕业设计项目
"""

import os
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
# 异常定义
# ============================================================================

class NetLoadError(Exception):
    """净负荷计算异常"""
    pass


# ============================================================================
# 电网参数定义
# ============================================================================

@dataclass
class GridConstraints:
    """
    电网运营约束参数

    新英格兰地区典型值:
      - 最小出力: 8000 MW (基荷+核电)
      - 最大出力: 25000 MW (全部机组)
      - 爬坡率: 50 MW/min (常规机组)
      - 反向潮流限制: 3000 MW (分布式光伏限制)
    """
    min_generation_mw: float = 8000.0     # 最小发电出力
    max_generation_mw: float = 25000.0   # 最大发电出力
    ramp_rate_mw_per_min: float = 50.0  # 爬坡率 (MW/min)
    reverse_flow_limit_mw: float = 3000.0  # 反向潮流限制
    transmission_limit_mw: float = 30000.0  # 传输容量


@dataclass
class StorageParams:
    """
    储能系统参数

    新英格兰地区典型 BESS:
      - 容量: 400 MWh (电池储能)
      - 功率: 200 MW (充放电)
      - 效率: 90% (往返)
      - SOC范围: 10%-90%
    """
    capacity_mwh: float = 400.0          # 储能容量 (MWh)
    power_charge_mw: float = 200.0       # 最大充电功率
    power_discharge_mw: float = 200.0    # 最大放电功率
    efficiency_charge: float = 0.92      # 充电效率
    efficiency_discharge: float = 0.92   # 放电效率
    soc_min: float = 0.10                # 最小SOC
    soc_max: float = 0.90                # 最大SOC
    soc_initial: float = 0.50            # 初始SOC
    cycle_cost_per_mwh: float = 15.0     # 循环成本 ($/MWh)


@dataclass
class GenerationMix:
    """
    发电组合及成本

    新英格兰地区典型组合:
      - 核电: 4100 MW, $25/MWh
      - 天然气: 12000 MW, $45/MWh
      - 水电: 3000 MW, $15/MWh
      - 风电: 1500 MW, $5/MWh
      - 光伏: 500 MW, $0/MWh (已计算)
      - 柴油/油: 1000 MW, $120/MWh (调峰)
    """
    nuclear_mw: float = 4100.0
    nuclear_cost: float = 25.0
    gas_mw: float = 12000.0
    gas_cost: float = 45.0
    hydro_mw: float = 3000.0
    hydro_cost: float = 15.0
    wind_mw: float = 1500.0
    wind_cost: float = 5.0
    oil_mw: float = 1000.0
    oil_cost: float = 120.0
    market_price: float = 50.0          # 日前市场均价 ($/MWh)
    export_price: float = 35.0          # 出口价格 ($/MWh)
    curtailment_cost: float = 10.0     # 弃电成本 ($/MWh)


# ============================================================================
# 结果数据类
# ============================================================================

@dataclass
class HourlyResult:
    """每小时计算结果"""
    hour: int
    timestamp: str
    load_forecast_mw: float
    pv_generation_mw: float
    net_load_mw: float                   # 原始净负荷
    curtailed_pv_mw: float               # 弃光量
    storage_charge_mw: float             # 储能充电(正=充电)
    storage_discharge_mw: float          # 储能放电(正=放电)
    adjusted_net_load_mw: float          # 调整后净负荷
    soc_percent: float                    # 储能SOC
    generation_cost_usd: float           # 发电成本
    is_peak: bool = False                 # 是否峰值时段
    is_valley: bool = False               # 是否谷值时段


@dataclass
class NetLoadResult:
    """净负荷计算完整结果"""
    hourly: List[HourlyResult] = field(default_factory=list)
    total_load_mwh: float = 0.0
    total_pv_mwh: float = 0.0
    total_net_load_mwh: float = 0.0
    total_curtailed_mwh: float = 0.0
    total_storage_charged_mwh: float = 0.0
    total_storage_discharged_mwh: float = 0.0
    peak_load_mw: float = 0.0
    valley_load_mw: float = 0.0
    peak_hours: List[int] = field(default_factory=list)
    valley_hours: List[int] = field(default_factory=list)
    total_generation_cost_usd: float = 0.0
    storage_revenue_usd: float = 0.0
    curtailment_cost_usd: float = 0.0
    dispatch_actions: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'hourly': [
                {
                    'hour': h.hour,
                    'timestamp': h.timestamp,
                    'load_forecast_mw': round(h.load_forecast_mw, 1),
                    'pv_generation_mw': round(h.pv_generation_mw, 1),
                    'net_load_mw': round(h.net_load_mw, 1),
                    'curtailed_pv_mw': round(h.curtailed_pv_mw, 1),
                    'storage_charge_mw': round(h.storage_charge_mw, 1),
                    'storage_discharge_mw': round(h.storage_discharge_mw, 1),
                    'adjusted_net_load_mw': round(h.adjusted_net_load_mw, 1),
                    'soc_percent': round(h.soc_percent, 1),
                    'generation_cost_usd': round(h.generation_cost_usd, 1),
                    'is_peak': h.is_peak,
                    'is_valley': h.is_valley,
                }
                for h in self.hourly
            ],
            'summary': {
                'total_load_mwh': round(self.total_load_mwh, 1),
                'total_pv_mwh': round(self.total_pv_mwh, 1),
                'total_net_load_mwh': round(self.total_net_load_mwh, 1),
                'total_curtailed_mwh': round(self.total_curtailed_mwh, 1),
                'peak_load_mw': round(self.peak_load_mw, 1),
                'valley_load_mw': round(self.valley_load_mw, 1),
                'total_generation_cost_usd': round(self.total_generation_cost_usd, 1),
                'storage_revenue_usd': round(self.storage_revenue_usd, 1),
                'curtailment_cost_usd': round(self.curtailment_cost_usd, 1),
                'dispatch_actions': self.dispatch_actions,
            }
        }


# ============================================================================
# 净负荷计算器
# ============================================================================

class NetLoadCalculator:
    """
    净负荷计算器

    整合负荷预测、光伏发电、储能系统和电网约束，
    计算净负荷并提供调度建议。

    计算流程:
      1. 基础净负荷 = 负荷预测 - 光伏发电
      2. 识别峰谷时段
      3. 储能调度: 谷时充电、峰时放电
      4. 弃光处理: 超过反向潮流限制的光伏
      5. 爬坡检查: 确保净负荷变化率在约束内
      6. 经济调度: 计算发电成本

    Attributes:
        grid: 电网约束参数
        storage: 储能系统参数
        gen_mix: 发电组合及成本
    """

    def __init__(
        self,
        grid: Optional[GridConstraints] = None,
        storage: Optional[StorageParams] = None,
        gen_mix: Optional[GenerationMix] = None,
    ):
        self.grid = grid or GridConstraints()
        self.storage = storage or StorageParams()
        self.gen_mix = gen_mix or GenerationMix()

        logger.info(f"NetLoadCalculator 初始化:")
        logger.info(f"  电网: [{self.grid.min_generation_mw}, {self.grid.max_generation_mw}] MW")
        logger.info(f"  储能: {self.storage.capacity_mwh} MWh, {self.storage.power_discharge_mw} MW")
        logger.info(f"  爬坡率: {self.grid.ramp_rate_mw_per_min} MW/min")

    # ========================================================================
    # 主计算入口
    # ========================================================================

    def calculate(
        self,
        load_forecast: np.ndarray,
        pv_generation: np.ndarray,
        timestamps: Optional[List[datetime]] = None,
    ) -> NetLoadResult:
        """
        计算净负荷和调度建议

        Args:
            load_forecast: 负荷预测 (MW), shape (24,)
            pv_generation: 光伏发电 (MW), shape (24,)
            timestamps: 时间戳列表 (24个)

        Returns:
            NetLoadResult: 完整计算结果
        """
        # 1. 输入验证
        load_forecast, pv_generation, timestamps = self._validate_input(
            load_forecast, pv_generation, timestamps
        )

        # 2. 基础净负荷
        net_load = load_forecast - pv_generation

        # 3. 识别峰谷时段
        peak_hours, valley_hours = self._identify_peak_valley(net_load)

        logger.info(f"  峰值时段: {peak_hours}")
        logger.info(f"  谷值时段: {valley_hours}")

        # 4. 储能调度
        storage_schedule, soc_profile, curtailed_pv = self._dispatch_storage(
            net_load, peak_hours, valley_hours
        )

        # 5. 调整后净负荷
        adjusted_net_load = self._compute_adjusted_net_load(
            net_load, storage_schedule, curtailed_pv
        )

        # 6. 爬坡约束检查
        adjusted_net_load = self._apply_ramp_constraints(adjusted_net_load)

        # 7. 电网容量约束
        adjusted_net_load, curtailed_pv = self._apply_grid_constraints(
            adjusted_net_load, pv_generation, curtailed_pv
        )

        # 8. 经济调度
        hourly_costs = self._compute_economic_dispatch(adjusted_net_load, storage_schedule)

        # 9. 构建结果
        result = self._build_result(
            load_forecast, pv_generation, net_load, curtailed_pv,
            storage_schedule, soc_profile, adjusted_net_load,
            hourly_costs, peak_hours, valley_hours, timestamps
        )

        logger.info(
            f"  净负荷: 总{result.total_net_load_mwh:.0f} MWh, "
            f"弃光{result.total_curtailed_mwh:.1f} MWh, "
            f"成本${result.total_generation_cost_usd:.0f}"
        )

        return result

    # ========================================================================
    # 输入验证
    # ========================================================================

    def _validate_input(
        self,
        load_forecast: np.ndarray,
        pv_generation: np.ndarray,
        timestamps: Optional[List[datetime]],
    ) -> Tuple[np.ndarray, np.ndarray, List[datetime]]:
        """验证输入数据"""
        load_forecast = np.asarray(load_forecast, dtype=np.float64)
        pv_generation = np.asarray(pv_generation, dtype=np.float64)

        if len(load_forecast) != len(pv_generation):
            raise NetLoadError(
                f"负荷和光伏数据长度不匹配: {len(load_forecast)} vs {len(pv_generation)}"
            )

        n = len(load_forecast)

        # 确保非负
        load_forecast = np.maximum(0, load_forecast)
        pv_generation = np.maximum(0, pv_generation)

        # 光伏不应超过负荷+合理余量
        excess_pv = pv_generation > load_forecast * 1.5
        if excess_pv.any():
            logger.warning(f"  {excess_pv.sum()} 个时段光伏超过负荷1.5倍")

        # 时间戳
        if timestamps is None:
            now = datetime.now()
            timestamps = [now + timedelta(hours=i) for i in range(n)]

        return load_forecast, pv_generation, timestamps

    # ========================================================================
    # 峰谷识别
    # ========================================================================

    def _identify_peak_valley(self, net_load: np.ndarray) -> Tuple[List[int], List[int]]:
        """
        识别峰值和谷值时段

        策略:
          - 峰值: 净负荷 > 均值 + 1标准差
          - 谷值: 净负荷 < 均值 - 1标准差
          - 或使用固定时段: 峰值 8-11/17-21, 谷值 0-5
        """
        n = len(net_load)
        mean_load = np.mean(net_load)
        std_load = np.std(net_load)

        peak_threshold = mean_load + 0.5 * std_load
        valley_threshold = mean_load - 0.5 * std_load

        peak_hours = [i for i in range(n) if net_load[i] > peak_threshold]
        valley_hours = [i for i in range(n) if net_load[i] < valley_threshold]

        # 确保峰谷不重叠
        valley_hours = [h for h in valley_hours if h not in peak_hours]

        return peak_hours, valley_hours

    # ========================================================================
    # 储能调度
    # ========================================================================

    def _dispatch_storage(
        self,
        net_load: np.ndarray,
        peak_hours: List[int],
        valley_hours: List[int],
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        储能充放电调度

        策略:
          1. 谷值时段充电: 利用低谷多余容量
          2. 峰值时段放电: 削峰
          3. SOC约束: 保持在 [soc_min, soc_max]
          4. 弃光处理: 超过反向潮流限制的光伏优先存储

        Returns:
            storage_schedule: (n,) 正=放电, 负=充电
            soc_profile: (n,) SOC百分比
            curtailed_pv: (n,) 弃光量
        """
        n = len(net_load)
        storage_schedule = np.zeros(n)
        soc_profile = np.zeros(n)
        curtailed_pv = np.zeros(n)

        # 当前SOC (MWh)
        current_soc_mwh = self.storage.soc_initial * self.storage.capacity_mwh
        min_soc_mwh = self.storage.soc_min * self.storage.capacity_mwh
        max_soc_mwh = self.storage.soc_max * self.storage.capacity_mwh

        # 逐小时调度
        for i in range(n):
            nl = net_load[i]

            # 检查是否需要弃光（净负荷为负且超过反向潮流限制）
            if nl < -self.grid.reverse_flow_limit_mw:
                excess = -nl - self.grid.reverse_flow_limit_mw
                # 优先尝试储能吸收
                available_charge = min(
                    self.storage.power_charge_mw,
                    (max_soc_mwh - current_soc_mwh),  # SOC空间
                    excess
                )
                if available_charge > 0:
                    # 充电
                    charged = available_charge
                    actual_charged = charged * self.storage.efficiency_charge
                    current_soc_mwh += actual_charged
                    storage_schedule[i] -= charged  # 负=充电
                    excess -= charged

                # 剩余弃光
                curtailed_pv[i] = max(0, excess)

            elif i in valley_hours and nl < np.mean(net_load) * 0.9:
                # 谷值充电: 净负荷低于均值90%时储能充电
                available_charge = min(
                    self.storage.power_charge_mw,
                    (max_soc_mwh - current_soc_mwh),
                    max(0, np.mean(net_load) - nl)  # 可吸收的量
                )
                if available_charge > 0:
                    actual_charged = available_charge * self.storage.efficiency_charge
                    current_soc_mwh += actual_charged
                    storage_schedule[i] -= available_charge

            elif i in peak_hours and current_soc_mwh > min_soc_mwh:
                # 峰值放电: 削峰
                available_discharge = min(
                    self.storage.power_discharge_mw,
                    (current_soc_mwh - min_soc_mwh),  # SOC可用
                    max(0, nl - np.mean(net_load))  # 削峰量
                )
                if available_discharge > 0:
                    actual_discharged = available_discharge / self.storage.efficiency_discharge
                    current_soc_mwh -= actual_discharged
                    storage_schedule[i] += available_discharge

            # 确保SOC在约束内
            current_soc_mwh = max(min_soc_mwh, min(max_soc_mwh, current_soc_mwh))
            soc_profile[i] = current_soc_mwh / self.storage.capacity_mwh * 100

        return storage_schedule, soc_profile, curtailed_pv

    # ========================================================================
    # 调整后净负荷
    # ========================================================================

    def _compute_adjusted_net_load(
        self,
        net_load: np.ndarray,
        storage_schedule: np.ndarray,
        curtailed_pv: np.ndarray,
    ) -> np.ndarray:
        """
        计算储能调度后的调整净负荷

        adjusted = net_load - storage_discharge + storage_charge + curtailed_pv
        (正=放电减少净负荷, 负=充电增加净负荷)
        """
        adjusted = net_load.copy()
        # storage_schedule: 正=放电(减少负荷), 负=充电(增加负荷)
        adjusted -= storage_schedule  # 放电减少负荷，充电增加负荷
        # 弃光增加了净负荷（因为光伏被削减）
        adjusted += curtailed_pv

        return adjusted

    # ========================================================================
    # 爬坡约束
    # ========================================================================

    def _apply_ramp_constraints(self, adjusted_net_load: np.ndarray) -> np.ndarray:
        """
        应用爬坡率约束

        确保相邻时段净负荷变化不超过最大爬坡率
        ramp_limit_per_hour = ramp_rate_mw_per_min × 60
        """
        ramp_limit = self.grid.ramp_rate_mw_per_min * 60  # MW/hour
        n = len(adjusted_net_load)

        for i in range(1, n):
            delta = adjusted_net_load[i] - adjusted_net_load[i-1]
            if abs(delta) > ramp_limit:
                adjusted_net_load[i] = adjusted_net_load[i-1] + np.sign(delta) * ramp_limit
                logger.warning(
                    f"  时段{i}: 爬坡约束激活, "
                    f"原始变化{delta:.0f}MW → 限制为{ramp_limit:.0f}MW/h"
                )

        return adjusted_net_load

    # ========================================================================
    # 电网容量约束
    # ========================================================================

    def _apply_grid_constraints(
        self,
        adjusted_net_load: np.ndarray,
        pv_generation: np.ndarray,
        curtailed_pv: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        应用电网容量约束

        1. 净负荷不低于最小发电出力（基荷约束）
        2. 净负荷不超过最大发电出力
        3. 负值不超过反向潮流限制
        """
        n = len(adjusted_net_load)

        for i in range(n):
            nl = adjusted_net_load[i]

            # 最大出力约束
            if nl > self.grid.max_generation_mw:
                excess = nl - self.grid.max_generation_mw
                logger.warning(
                    f"  时段{i}: 净负荷{nl:.0f}MW超过最大出力"
                    f"{self.grid.max_generation_mw:.0f}MW"
                )
                adjusted_net_load[i] = self.grid.max_generation_mw

            # 最小出力约束 (净负荷过低)
            if nl < self.grid.min_generation_mw * 0.3:
                # 可能需要弃光更多
                deficit = self.grid.min_generation_mw * 0.3 - nl
                if deficit > 0 and pv_generation[i] > 0:
                    additional_curtail = min(deficit, pv_generation[i] - curtailed_pv[i])
                    curtailed_pv[i] += additional_curtail
                    adjusted_net_load[i] += additional_curtail

        return adjusted_net_load, curtailed_pv

    # ========================================================================
    # 经济调度
    # ========================================================================

    def _compute_economic_dispatch(
        self,
        adjusted_net_load: np.ndarray,
        storage_schedule: np.ndarray,
    ) -> np.ndarray:
        """
        经济调度成本计算

        发电成本按机组经济性排序（ merit order）:
          1. 光伏/风电: $0-5/MWh (边际成本极低)
          2. 水电: $15/MWh
          3. 核电: $25/MWh
          4. 天然气: $45/MWh
          5. 油/柴油: $120/MWh (调峰机组)

        储能成本: 循环成本 × 充放电量
        """
        n = len(adjusted_net_load)
        hourly_costs = np.zeros(n)

        for i in range(n):
            load = max(0, adjusted_net_load[i])
            remaining = load
            cost = 0.0

            # 按经济性排序调度
            # 1. 光伏 (已在净负荷中扣除)
            # 2. 风电
            wind_dispatch = min(remaining, self.gen_mix.wind_mw)
            cost += wind_dispatch * self.gen_mix.wind_cost
            remaining -= wind_dispatch

            # 3. 水电
            hydro_dispatch = min(remaining, self.gen_mix.hydro_mw)
            cost += hydro_dispatch * self.gen_mix.hydro_cost
            remaining -= hydro_dispatch

            # 4. 核电
            nuclear_dispatch = min(remaining, self.gen_mix.nuclear_mw)
            cost += nuclear_dispatch * self.gen_mix.nuclear_cost
            remaining -= nuclear_dispatch

            # 5. 天然气
            gas_dispatch = min(remaining, self.gen_mix.gas_mw)
            cost += gas_dispatch * self.gen_mix.gas_cost
            remaining -= gas_dispatch

            # 6. 油/柴油 (调峰)
            oil_dispatch = min(remaining, self.gen_mix.oil_mw)
            cost += oil_dispatch * self.gen_mix.oil_cost
            remaining -= oil_dispatch

            # 如果仍有剩余，按市场价
            if remaining > 0:
                cost += remaining * self.gen_mix.market_price

            # 储能循环成本
            storage_energy = abs(storage_schedule[i])
            cost += storage_energy * self.storage.cycle_cost_per_mwh

            hourly_costs[i] = cost

        return hourly_costs

    # ========================================================================
    # 构建结果
    # ========================================================================

    def _build_result(
        self,
        load_forecast: np.ndarray,
        pv_generation: np.ndarray,
        net_load: np.ndarray,
        curtailed_pv: np.ndarray,
        storage_schedule: np.ndarray,
        soc_profile: np.ndarray,
        adjusted_net_load: np.ndarray,
        hourly_costs: np.ndarray,
        peak_hours: List[int],
        valley_hours: List[int],
        timestamps: List[datetime],
    ) -> NetLoadResult:
        """构建完整结果"""
        n = len(load_forecast)
        hourly_results = []

        for i in range(n):
            charge = max(0, -storage_schedule[i])  # 充电
            discharge = max(0, storage_schedule[i])  # 放电

            hourly_results.append(HourlyResult(
                hour=i,
                timestamp=timestamps[i].isoformat(),
                load_forecast_mw=float(load_forecast[i]),
                pv_generation_mw=float(pv_generation[i]),
                net_load_mw=float(net_load[i]),
                curtailed_pv_mw=float(curtailed_pv[i]),
                storage_charge_mw=float(charge),
                storage_discharge_mw=float(discharge),
                adjusted_net_load_mw=float(adjusted_net_load[i]),
                soc_percent=float(soc_profile[i]),
                generation_cost_usd=float(hourly_costs[i]),
                is_peak=i in peak_hours,
                is_valley=i in valley_hours,
            ))

        # 生成调度建议
        dispatch_actions = self._generate_dispatch_actions(
            hourly_results, peak_hours, valley_hours
        )

        result = NetLoadResult(
            hourly=hourly_results,
            total_load_mwh=float(np.sum(load_forecast)),
            total_pv_mwh=float(np.sum(pv_generation)),
            total_net_load_mwh=float(np.sum(adjusted_net_load)),
            total_curtailed_mwh=float(np.sum(curtailed_pv)),
            total_storage_charged_mwh=float(np.sum(np.maximum(0, -storage_schedule))),
            total_storage_discharged_mwh=float(np.sum(np.maximum(0, storage_schedule))),
            peak_load_mw=float(np.max(adjusted_net_load)),
            valley_load_mw=float(np.min(adjusted_net_load)),
            peak_hours=peak_hours,
            valley_hours=valley_hours,
            total_generation_cost_usd=float(np.sum(hourly_costs)),
            storage_revenue_usd=self._compute_storage_revenue(storage_schedule, peak_hours, valley_hours),
            curtailment_cost_usd=float(np.sum(curtailed_pv) * self.gen_mix.curtailment_cost),
            dispatch_actions=dispatch_actions,
        )

        return result

    # ========================================================================
    # 调度建议生成
    # ========================================================================

    def _generate_dispatch_actions(
        self,
        hourly: List[HourlyResult],
        peak_hours: List[int],
        valley_hours: List[int],
    ) -> List[Dict]:
        """
        生成电网调度建议

        基于净负荷曲线生成操作建议
        """
        actions = []

        # 削峰建议
        if peak_hours:
            peak_load = max(hourly[h].adjusted_net_load_mw for h in peak_hours)
            peak_hour = max(peak_hours, key=lambda h: hourly[h].adjusted_net_load_mw)
            storage_discharge = sum(hourly[h].storage_discharge_mw for h in peak_hours)

            actions.append({
                "type": "peak_shaving",
                "priority": "high",
                "description": f"峰值时段{peak_hours}削峰",
                "peak_load_mw": round(peak_load, 1),
                "storage_discharge_mw": round(storage_discharge, 1),
                "recommendation": (
                    f"在峰值时段（小时{peak_hour}）启动储能放电"
                    f"（{hourly[peak_hour].storage_discharge_mw:.0f}MW），"
                    f"减少调峰机组启动"
                ),
            })

        # 填谷建议
        if valley_hours:
            valley_load = min(hourly[h].adjusted_net_load_mw for h in valley_hours)
            valley_hour = min(valley_hours, key=lambda h: hourly[h].adjusted_net_load_mw)
            storage_charge = sum(hourly[h].storage_charge_mw for h in valley_hours)

            actions.append({
                "type": "valley_filling",
                "priority": "medium",
                "description": f"谷值时段{valley_hours}填谷",
                "valley_load_mw": round(valley_load, 1),
                "storage_charge_mw": round(storage_charge, 1),
                "recommendation": (
                    f"在谷值时段（小时{valley_hour}）储能充电"
                    f"（{hourly[valley_hour].storage_charge_mw:.0f}MW），"
                    f"避免基荷机组降出力"
                ),
            })

        # 弃光建议
        total_curtail = sum(h.curtailed_pv_mw for h in hourly)
        if total_curtail > 0:
            curtail_hours = [h.hour for h in hourly if h.curtailed_pv_mw > 0]
            actions.append({
                "type": "curtailment",
                "priority": "high",
                "description": f"光伏弃光 {total_curtail:.1f} MWh",
                "curtail_hours": curtail_hours,
                "recommendation": (
                    f"小时{curtail_hours}出现光伏过剩，"
                    f"建议增加储能容量或调整光伏出力"
                ),
            })

        # 反向潮流警告
        negative_hours = [h.hour for h in hourly if h.net_load_mw < -self.grid.reverse_flow_limit_mw]
        if negative_hours:
            actions.append({
                "type": "reverse_flow_warning",
                "priority": "critical",
                "description": f"反向潮流超限 小时{negative_hours}",
                "recommendation": "分布式光伏可能导致反向潮流，需要负荷管理或弃光",
            })

        # 爬坡建议
        ramp_violations = []
        for i in range(1, len(hourly)):
            delta = hourly[i].adjusted_net_load_mw - hourly[i-1].adjusted_net_load_mw
            ramp_limit = self.grid.ramp_rate_mw_per_min * 60
            if abs(delta) > ramp_limit:
                ramp_violations.append({
                    "hour": i,
                    "delta_mw": round(delta, 1),
                    "limit_mw": round(ramp_limit, 1),
                })

        if ramp_violations:
            actions.append({
                "type": "ramp_constraint",
                "priority": "high",
                "description": f"爬坡约束违反 {len(ramp_violations)}次",
                "violations": ramp_violations,
                "recommendation": "调整储能调度平滑负荷曲线",
            })

        return actions

    # ========================================================================
    # 储能收益计算
    # ========================================================================

    def _compute_storage_revenue(
        self,
        storage_schedule: np.ndarray,
        peak_hours: List[int],
        valley_hours: List[int],
    ) -> float:
        """
        计算储能套利收益

        收益 = 放电量 × 峰值价格 - 充电量 × 谷值价格
        """
        discharge_revenue = 0.0
        charge_cost = 0.0

        for i in range(len(storage_schedule)):
            if storage_schedule[i] > 0:  # 放电
                # 按峰值价格
                price = self.gen_mix.market_price * 1.5 if i in peak_hours else self.gen_mix.market_price
                discharge_revenue += storage_schedule[i] * price
            elif storage_schedule[i] < 0:  # 充电
                # 按谷值价格
                price = self.gen_mix.market_price * 0.5 if i in valley_hours else self.gen_mix.market_price
                charge_cost += abs(storage_schedule[i]) * price

        net_revenue = discharge_revenue - charge_cost
        # 减去循环成本
        cycle_cost = np.sum(np.abs(storage_schedule)) * self.storage.cycle_cost_per_mwh

        return net_revenue - cycle_cost

    # ========================================================================
    # 多时间尺度
    # ========================================================================

    def calculate_minute_resolution(
        self,
        load_forecast_hourly: np.ndarray,
        pv_generation_hourly: np.ndarray,
        timestamps: Optional[List[datetime]] = None,
        minutes_per_step: int = 15,
    ) -> NetLoadResult:
        """
        分钟级分辨率计算

        将小时级数据插值为分钟级，进行更精细的调度

        Args:
            load_forecast_hourly: 小时级负荷 (24,)
            pv_generation_hourly: 小时级光伏 (24,)
            minutes_per_step: 每步分钟数 (5/15/30)
        """
        n_hours = len(load_forecast_hourly)
        steps_per_hour = 60 // minutes_per_step
        n_total = n_hours * steps_per_hour

        # 线性插值
        load_fine = np.interp(
            np.linspace(0, n_hours - 1, n_total),
            np.arange(n_hours),
            load_forecast_hourly,
        )
        pv_fine = np.interp(
            np.linspace(0, n_hours - 1, n_total),
            np.arange(n_hours),
            pv_generation_hourly,
        )

        # 时间戳
        if timestamps is None:
            now = datetime.now()
            timestamps_fine = [now + timedelta(minutes=minutes_per_step * i) for i in range(n_total)]
        else:
            timestamps_fine = []
            for i in range(n_hours):
                for j in range(steps_per_hour):
                    if i < len(timestamps):
                        timestamps_fine.append(
                            timestamps[i] + timedelta(minutes=minutes_per_step * j)
                        )

        # 调用主计算
        result = self.calculate(load_fine, pv_fine, timestamps_fine)
        result.dispatch_actions.append({
            "type": "resolution_note",
            "description": f"分钟级分辨率 ({minutes_per_step}分钟/步)",
            "total_steps": n_total,
        })

        return result


# ============================================================================
# 使用示例
# ============================================================================

def demo():
    """演示净负荷计算器"""
    print("=" * 60)
    print("净负荷计算模块演示")
    print("=" * 60)

    # 1. 创建计算器
    print("\n[1] 创建计算器...")
    calculator = NetLoadCalculator()

    # 2. 模拟数据
    print("\n[2] 生成模拟数据...")
    np.random.seed(42)
    hours = np.arange(24)
    # 典型日内负荷曲线
    load = 12000 + 3000 * np.sin((hours - 14) * np.pi / 12) + np.random.normal(0, 200, 24)
    # 光伏曲线
    pv = np.array([
        max(0, 400 * np.sin((h - 6) * np.pi / 12)) if 6 <= h <= 18 else 0
        for h in hours
    ])

    print(f"  总负荷: {load.sum():.0f} MWh")
    print(f"  总光伏: {pv.sum():.0f} MWh")

    # 3. 计算
    print("\n[3] 计算净负荷...")
    result = calculator.calculate(load, pv)

    print(f"\n  净负荷: {result.total_net_load_mwh:.0f} MWh")
    print(f"  弃光: {result.total_curtailed_mwh:.1f} MWh")
    print(f"  储能充电: {result.total_storage_charged_mwh:.1f} MWh")
    print(f"  储能放电: {result.total_storage_discharged_mwh:.1f} MWh")
    print(f"  峰值: {result.peak_load_mw:.0f} MW")
    print(f"  谷值: {result.valley_load_mw:.0f} MW")
    print(f"  发电成本: ${result.total_generation_cost_usd:.0f}")
    print(f"  储能收益: ${result.storage_revenue_usd:.0f}")

    print(f"\n  逐小时:")
    print(f"  {'Hr':>3} {'Load':>8} {'PV':>7} {'NetLoad':>8} {'Charge':>7} {'Disch':>7} {'SOC%':>6} {'Cost$':>8}")
    for h in result.hourly:
        print(f"  {h.hour:3d} {h.load_forecast_mw:8.0f} {h.pv_generation_mw:7.0f} "
              f"{h.adjusted_net_load_mw:8.0f} {h.storage_charge_mw:7.0f} "
              f"{h.storage_discharge_mw:7.0f} {h.soc_percent:6.1f} {h.generation_cost_usd:8.0f}")

    print(f"\n  调度建议:")
    for a in result.dispatch_actions:
        print(f"  [{a['type']}] {a.get('description', '')}")
        if 'recommendation' in a:
            print(f"    → {a['recommendation']}")

    return calculator, result


if __name__ == "__main__":
    demo()
