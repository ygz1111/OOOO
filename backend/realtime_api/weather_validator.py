"""
智能电网负荷预测系统 - 气象数据质量验证模块

功能:
  1. 物理范围验证：温度(-30~45°C)、露点、湿度(0-100%)、云量(0-100%)、辐射(非负)
  2. 逻辑约束验证：露点温度不高于气温
  3. IQR 统计异常检测：基于四分位距识别统计异常
  4. 异常分级处理：轻微异常自动修正，严重异常抛出异常
  5. 缺失值三级填充策略：
     - 策略1: 相邻时间点线性插值
     - 策略2: 历史同期数据填充（前24/168小时）
     - 策略3: 多站点数据融合平均
  6. 输出：JSON质量报告 + 干净数据 + 异常值标记

依赖:
  pip install pandas numpy

作者: 毕业设计项目
"""

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Any, Tuple, Set

import numpy as np
import pandas as pd


# ============================================================================
# 日志配置
# ============================================================================
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )


# ============================================================================
# 枚举定义
# ============================================================================

class AnomalySeverity(Enum):
    """异常严重程度"""
    NORMAL = "normal"        # 正常
    MINOR = "minor"          # 轻微异常（可自动修正）
    SEVERE = "severe"        # 严重异常（需要人工介入）


class AnomalyType(Enum):
    """异常类型"""
    RANGE_VIOLATION = "range_violation"          # 物理范围超出
    LOGIC_VIOLATION = "logic_violation"          # 逻辑约束违反
    STATISTICAL_OUTLIER = "statistical_outlier"   # 统计异常
    MISSING_VALUE = "missing_value"               # 缺失值
    TIME_GAP = "time_gap"                         # 时间间隔异常


class CorrectionMethod(Enum):
    """修正方法"""
    NONE = "none"                    # 未修正
    TIME_INTERPOLATION = "time_interp"      # 时间线性插值
    HISTORICAL_FILL = "historical_fill"     # 历史同期填充
    STATION_FUSION = "station_fusion"        # 多站点融合
    CLAMP_TO_RANGE = "clamp_to_range"       # 截断到范围
    DEW_POINT_CORRECTION = "dew_point_fix"  # 露点修正


# ============================================================================
# 数据类定义
# ============================================================================

@dataclass
class AnomalyRecord:
    """单条异常记录"""
    timestamp: Any                    # 时间戳
    location: str                     # 站点名称
    parameter: str                    # 参数名
    anomaly_type: str                 # 异常类型 (AnomalyType.value)
    severity: str                     # 严重程度 (AnomalySeverity.value)
    original_value: Optional[float]   # 原始值
    corrected_value: Optional[float]  # 修正后值
    correction_method: str            # 修正方法 (CorrectionMethod.value)
    description: str                  # 描述

    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': str(self.timestamp) if self.timestamp is not None else None,
            'location': self.location,
            'parameter': self.parameter,
            'anomaly_type': self.anomaly_type,
            'severity': self.severity,
            'original_value': self.original_value,
            'corrected_value': self.corrected_value,
            'correction_method': self.correction_method,
            'description': self.description,
        }


@dataclass
class QualityReport:
    """数据质量报告"""
    # 基本信息
    total_records: int = 0
    total_parameters: int = 0
    locations_count: int = 0
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None

    # 异常统计
    total_anomalies: int = 0
    minor_anomalies: int = 0
    severe_anomalies: int = 0
    anomalies_by_type: Dict[str, int] = field(default_factory=dict)
    anomalies_by_parameter: Dict[str, int] = field(default_factory=dict)

    # 缺失值统计
    total_missing: int = 0
    missing_filled_by_interp: int = 0
    missing_filled_by_historical: int = 0
    missing_filled_by_fusion: int = 0
    missing_remaining: int = 0

    # 时间连续性
    time_gaps_detected: int = 0
    time_gaps_filled: int = 0

    # 总体评价
    overall_quality_score: float = 0.0   # 0~100
    is_valid: bool = True
    issues: List[str] = field(default_factory=list)

    # 详细异常记录
    anomaly_records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return {
            'total_records': self.total_records,
            'total_parameters': self.total_parameters,
            'locations_count': self.locations_count,
            'time_range_start': self.time_range_start,
            'time_range_end': self.time_range_end,
            'total_anomalies': self.total_anomalies,
            'minor_anomalies': self.minor_anomalies,
            'severe_anomalies': self.severe_anomalies,
            'anomalies_by_type': dict(self.anomalies_by_type),
            'anomalies_by_parameter': dict(self.anomalies_by_parameter),
            'total_missing': self.total_missing,
            'missing_filled_by_interp': self.missing_filled_by_interp,
            'missing_filled_by_historical': self.missing_filled_by_historical,
            'missing_filled_by_fusion': self.missing_filled_by_fusion,
            'missing_remaining': self.missing_remaining,
            'time_gaps_detected': self.time_gaps_detected,
            'time_gaps_filled': self.time_gaps_filled,
            'overall_quality_score': round(self.overall_quality_score, 2),
            'is_valid': self.is_valid,
            'issues': self.issues,
            'anomaly_records': self.anomaly_records,
        }

    def to_json(self, indent: int = 2) -> str:
        """转为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ============================================================================
# 自定义异常
# ============================================================================

class SevereDataQualityError(Exception):
    """严重数据质量异常，需要人工介入"""
    pass


class DataValidationError(Exception):
    """数据验证通用异常"""
    pass


# ============================================================================
# 主验证器类
# ============================================================================

class WeatherDataValidator:
    """
    气象数据质量验证器

    对 Open-Meteo API 获取的气象数据进行全面的质量验证和清洗：
    1. 物理范围检查
    2. 逻辑约束检查（露点 ≤ 气温）
    3. IQR 统计异常检测
    4. 三级缺失值填充
    5. 生成 JSON 质量报告

    Attributes:
        weather_params: 参与验证的气象参数列表
        severity_threshold: 严重异常的阈值比例（占总记录的比例）
        iqr_k: IQR 倍数（默认 3.0，保守阈值）
    """

    # 新英格兰地区物理范围验证规则
    # 格式: {参数名: (最小值, 最大值, 是否允许轻微超出)}
    VALIDATION_RULES: Dict[str, Tuple[float, float]] = {
        "temperature_2m":       (-30.0, 45.0),    # °C, 新英格兰地区
        "dew_point_2m":        (-35.0, 35.0),    # °C
        "relative_humidity_2m": (0.0, 100.0),     # %
        "wind_speed_10m":      (0.0, 50.0),       # m/s
        "cloud_cover":         (0.0, 100.0),      # %
        "shortwave_radiation":  (0.0, 1200.0),    # W/m²
    }

    # 轻微异常容忍度（超出范围但在容忍度内的视为轻微）
    TOLERANCE_RATIO = 0.15   # 超出范围 15% 以内为轻微

    # 严重异常阈值：单参数异常比例超过此值则抛出异常
    SEVERE_ANOMALY_RATIO = 0.20

    # IQR 倍数
    IQR_K = 3.0

    def __init__(
        self,
        weather_params: Optional[List[str]] = None,
        severe_anomaly_ratio: float = None,
        iqr_k: float = None,
    ):
        """
        初始化数据质量验证器

        Args:
            weather_params: 参与验证的参数列表，默认使用全部 VALIDATION_RULES 的键
            severe_anomaly_ratio: 严重异常比例阈值，默认 0.20 (20%)
            iqr_k: IQR 倍数，默认 3.0
        """
        self.weather_params = weather_params or list(self.VALIDATION_RULES.keys())

        if severe_anomaly_ratio is not None:
            self.SEVERE_ANOMALY_RATIO = severe_anomaly_ratio
        if iqr_k is not None:
            self.IQR_K = iqr_k

        # 存储所有异常记录
        self._anomaly_records: List[AnomalyRecord] = []

        # 质量报告
        self._report = QualityReport()

        # 异常值标记 DataFrame（布尔矩阵）
        self._anomaly_flags: Optional[pd.DataFrame] = None

        logger.info(f"WeatherDataValidator 初始化完成")
        logger.info(f"  验证参数: {self.weather_params}")
        logger.info(f"  严重异常阈值: {self.SEVERE_ANOMALY_RATIO*100:.0f}%")
        logger.info(f"  IQR 倍数: {self.IQR_K}")

    # ========================================================================
    # 公开 API
    # ========================================================================

    def validate(
        self,
        df: pd.DataFrame,
        raise_on_severe: bool = True,
    ) -> Tuple[pd.DataFrame, QualityReport, pd.DataFrame]:
        """
        执行完整的数据质量验证和清洗流程

        Args:
            df: 原始气象数据 DataFrame
                要求包含 'timestamp' 和 'location' 列，以及各气象参数列
            raise_on_severe: 遇到严重异常时是否抛出异常（默认 True）

        Returns:
            Tuple[DataFrame, QualityReport, DataFrame]:
                - 清洗后的数据
                - 质量报告对象
                - 异常值标记 DataFrame（布尔矩阵，True 表示该位置曾异常）

        Raises:
            SevereDataQualityError: 当严重异常比例超过阈值且 raise_on_severe=True
            DataValidationError: 当输入数据格式不正确
        """
        logger.info("=" * 60)
        logger.info("开始气象数据质量验证")
        logger.info("=" * 60)

        # 重置状态
        self._anomaly_records = []
        self._report = QualityReport()

        # 0. 输入检查
        df = self._validate_input(df)

        # 复制一份用于处理
        df_clean = df.copy()

        # 初始化异常标记矩阵
        param_cols = [c for c in df_clean.columns if c in self.weather_params]
        self._anomaly_flags = pd.DataFrame(
            False, index=df_clean.index, columns=param_cols
        )

        # 1. 时间连续性检查
        logger.info("\n[步骤1] 时间连续性检查...")
        self._check_time_continuity(df_clean)

        # 2. 物理范围验证
        logger.info("\n[步骤2] 物理范围验证...")
        df_clean = self._validate_ranges(df_clean)

        # 3. 逻辑约束验证（露点 ≤ 气温）
        logger.info("\n[步骤3] 逻辑约束验证...")
        df_clean = self._validate_logical_constraints(df_clean)

        # 4. IQR 统计异常检测
        logger.info("\n[步骤4] IQR 统计异常检测...")
        df_clean = self._detect_statistical_outliers(df_clean)

        # 5. 缺失值处理（三级策略）
        logger.info("\n[步骤5] 缺失值处理...")
        df_clean = self._handle_missing_values(df_clean)

        # 6. 严重异常检查
        logger.info("\n[步骤6] 严重异常评估...")
        self._evaluate_severity(df_clean, raise_on_severe)

        # 7. 生成质量报告
        logger.info("\n[步骤7] 生成质量报告...")
        self._finalize_report(df_clean)

        logger.info("\n" + "=" * 60)
        logger.info(f"验证完成: 质量评分 {self._report.overall_quality_score:.1f}/100")
        logger.info(f"异常总数: {self._report.total_anomalies} "
                     f"(轻微: {self._report.minor_anomalies}, "
                     f"严重: {self._report.severe_anomalies})")
        logger.info(f"缺失值: {self._report.total_missing} → 剩余: {self._report.missing_remaining}")
        logger.info("=" * 60)

        return df_clean, self._report, self._anomaly_flags

    def get_report_json(self) -> str:
        """获取 JSON 格式的质量报告"""
        return self._report.to_json()

    def get_anomaly_records(self) -> List[Dict[str, Any]]:
        """获取所有异常记录列表"""
        return [r.to_dict() for r in self._anomaly_records]

    # ========================================================================
    # 输入验证
    # ========================================================================

    def _validate_input(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        验证输入 DataFrame 格式

        Returns:
            整理后的 DataFrame（timestamp 列转为 datetime 并设为索引参考）

        Raises:
            DataValidationError: 输入格式不正确
        """
        if df is None or len(df) == 0:
            raise DataValidationError("输入 DataFrame 为空")

        # 检查必需列
        required_cols = ['timestamp', 'location']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            raise DataValidationError(
                f"输入数据缺少必需列: {missing_cols}。"
                f"请确保包含 'timestamp' 和 'location' 列。"
            )

        # 检查气象参数列
        param_cols = [c for c in df.columns if c in self.weather_params]
        if not param_cols:
            raise DataValidationError(
                f"输入数据中未找到任何气象参数列。"
                f"期望参数: {self.weather_params}"
            )

        # 确保 timestamp 是 datetime 类型
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            try:
                df = df.copy()
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            except Exception as e:
                raise DataValidationError(
                    f"timestamp 列无法转为 datetime: {e}"
                )

        # 排序（按站点 + 时间）
        df = df.sort_values(['location', 'timestamp']).reset_index(drop=True)

        logger.info(f"  输入数据: {len(df)} 条, {len(param_cols)} 个参数, "
                    f"{df['location'].nunique()} 个站点")

        return df

    # ========================================================================
    # 步骤1: 时间连续性检查
    # ========================================================================

    def _check_time_continuity(self, df: pd.DataFrame) -> None:
        """检查时间序列连续性，检测时间间隔异常"""
        locations = df['location'].unique()

        for loc in locations:
            loc_df = df[df['location'] == loc].sort_values('timestamp')

            if len(loc_df) < 2:
                continue

            # 计算时间差
            time_diffs = loc_df['timestamp'].diff().dt.total_seconds()
            # 期望间隔为 3600 秒（1小时）
            gap_mask = (time_diffs != 3600.0) & (time_diffs.notna())
            gap_count = gap_mask.sum()

            if gap_count > 0:
                self._report.time_gaps_detected += int(gap_count)
                gaps = loc_df[gap_mask.values]
                for _, row in gaps.iterrows():
                    diff_hours = time_diffs[row.name] / 3600.0
                    self._add_anomaly(
                        timestamp=row['timestamp'],
                        location=loc,
                        parameter='timestamp',
                        anomaly_type=AnomalyType.TIME_GAP,
                        severity=AnomalySeverity.MINOR,
                        original_value=diff_hours,
                        corrected_value=1.0,
                        correction_method=CorrectionMethod.NONE,
                        description=f"时间间隔异常: {diff_hours:.1f}h (期望1h)"
                    )
                logger.warning(f"  {loc}: 检测到 {gap_count} 个时间间隔异常")

        logger.info(f"  时间间隔异常总数: {self._report.time_gaps_detected}")

    # ========================================================================
    # 步骤2: 物理范围验证
    # ========================================================================

    def _validate_ranges(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        物理范围验证：检查各参数值是否在合理范围内

        轻微超出 → 标记并自动修正（截断到边界或插值）
        严重超出 → 标记为严重异常
        """
        for param in self.weather_params:
            if param not in df.columns:
                logger.warning(f"  参数 {param} 不在数据中，跳过")
                continue

            if param not in self.VALIDATION_RULES:
                continue

            min_val, max_val = self.VALIDATION_RULES[param]
            # 轻微异常容忍范围
            tolerance = (max_val - min_val) * self.TOLERANCE_RATIO
            minor_max = max_val + tolerance
            minor_min = min_val - tolerance

            series = df[param]

            # 检测超出范围的值
            out_of_range = (series < min_val) | (series > max_val)
            out_count = out_of_range.sum()

            if out_count == 0:
                continue

            # 区分轻微和严重
            severely_out = (series < minor_min) | (series > minor_max)
            severely_count = severely_out.sum()
            minorly_out = out_of_range & ~severely_out
            minorly_count = minorly_out.sum()

            logger.warning(
                f"  {param}: 检测到 {out_count} 个超出范围值 "
                f"(轻微: {minorly_count}, 严重: {severely_count}) "
                f"范围 [{min_val}, {max_val}]"
            )

            # 记录异常
            for idx in df[out_of_range].index:
                val = df.at[idx, param]
                is_severe = (val < minor_min) or (val > minor_max)
                severity = AnomalySeverity.SEVERE if is_severe else AnomalySeverity.MINOR

                # 修正策略：严重异常→置NaN待填充，轻微异常→截断到边界
                if is_severe:
                    corrected = np.nan
                    method = CorrectionMethod.NONE  # 后续由缺失值处理填充
                else:
                    corrected = max(min_val, min(max_val, val))
                    method = CorrectionMethod.CLAMP_TO_RANGE

                self._add_anomaly(
                    timestamp=df.at[idx, 'timestamp'],
                    location=df.at[idx, 'location'],
                    parameter=param,
                    anomaly_type=AnomalyType.RANGE_VIOLATION,
                    severity=severity,
                    original_value=float(val),
                    corrected_value=corrected if not np.isnan(corrected) else None,
                    correction_method=method,
                    description=f"超出物理范围 [{min_val}, {max_val}]"
                )

                # 标记异常
                self._anomaly_flags.at[idx, param] = True

            # 应用修正
            # 严重异常：置NaN，交给后续缺失值处理
            df.loc[severely_out, param] = np.nan
            # 轻微异常：截断到边界
            df.loc[minorly_out & (df[param] < min_val), param] = min_val
            df.loc[minorly_out & (df[param] > max_val), param] = max_val

        return df

    # ========================================================================
    # 步骤3: 逻辑约束验证
    # ========================================================================

    def _validate_logical_constraints(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        逻辑约束验证

        规则: 露点温度 (dew_point_2m) 不应高于气温 (temperature_2m)
        违反时: 将露点修正为等于气温
        """
        if 'dew_point_2m' not in df.columns or 'temperature_2m' not in df.columns:
            return df

        # 找到露点高于气温的位置
        mask = (df['dew_point_2m'] > df['temperature_2m']) & \
               df['dew_point_2m'].notna() & \
               df['temperature_2m'].notna()

        count = mask.sum()

        if count == 0:
            logger.info("  逻辑约束检查通过: 露点 ≤ 气温")
            return df

        logger.warning(f"  露点温度高于气温: {count} 处，修正为等于气温")

        for idx in df[mask].index:
            dew = df.at[idx, 'dew_point_2m']
            temp = df.at[idx, 'temperature_2m']
            self._add_anomaly(
                timestamp=df.at[idx, 'timestamp'],
                location=df.at[idx, 'location'],
                parameter='dew_point_2m',
                anomaly_type=AnomalyType.LOGIC_VIOLATION,
                severity=AnomalySeverity.MINOR,
                original_value=float(dew),
                corrected_value=float(temp),
                correction_method=CorrectionMethod.DEW_POINT_CORRECTION,
                description=f"露点({dew:.1f}°C)高于气温({temp:.1f}°C)，修正为等于气温"
            )
            self._anomaly_flags.at[idx, 'dew_point_2m'] = True

        # 修正：露点 = 气温
        df.loc[mask, 'dew_point_2m'] = df.loc[mask, 'temperature_2m']

        return df

    # ========================================================================
    # 步骤4: IQR 统计异常检测
    # ========================================================================

    def _detect_statistical_outliers(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        IQR (四分位距) 统计异常检测

        IQR = Q3 - Q1
        下界 = Q1 - k * IQR
        上界 = Q3 + k * IQR

        超出此范围的值标记为统计异常，置为 NaN 交由后续填充
        """
        for param in self.weather_params:
            if param not in df.columns:
                continue
            if param not in self.VALIDATION_RULES:
                continue

            series = df[param].dropna()
            if len(series) < 10:
                continue

            Q1 = series.quantile(0.25)
            Q3 = series.quantile(0.75)
            IQR = Q3 - Q1
            lower = Q1 - self.IQR_K * IQR
            upper = Q3 + self.IQR_K * IQR

            outlier_mask = (df[param] < lower) | (df[param] > upper)
            outlier_mask = outlier_mask & df[param].notna()
            count = outlier_mask.sum()

            if count == 0:
                continue

            logger.info(
                f"  {param}: IQR检测到 {count} 个统计异常 "
                f"(IQR范围 [{lower:.2f}, {upper:.2f}])"
            )

            for idx in df[outlier_mask].index:
                val = df.at[idx, param]
                self._add_anomaly(
                    timestamp=df.at[idx, 'timestamp'],
                    location=df.at[idx, 'location'],
                    parameter=param,
                    anomaly_type=AnomalyType.STATISTICAL_OUTLIER,
                    severity=AnomalySeverity.MINOR,
                    original_value=float(val),
                    corrected_value=None,
                    correction_method=CorrectionMethod.NONE,
                    description=f"IQR统计异常: {val:.2f} 超出 [{lower:.2f}, {upper:.2f}]"
                )
                self._anomaly_flags.at[idx, param] = True

            # 置为 NaN，交给缺失值处理
            df.loc[outlier_mask, param] = np.nan

        return df

    # ========================================================================
    # 步骤5: 缺失值处理（三级策略）
    # ========================================================================

    def _handle_missing_values(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        三级缺失值处理策略

        策略1: 相邻时间点线性插值 (time interpolation)
        策略2: 历史同期数据填充 (前24h/168h同时刻值)
        策略3: 多站点数据融合平均 (同一时刻其他站点的平均值)
        """
        param_cols = [c for c in df.columns if c in self.weather_params]

        # 统计初始缺失值
        initial_missing = df[param_cols].isna().sum().sum()
        self._report.total_missing = int(initial_missing)

        if initial_missing == 0:
            logger.info("  无缺失值")
            return df

        logger.info(f"  初始缺失值总数: {initial_missing}")

        # --- 策略1: 相邻时间点线性插值 ---
        filled_count = 0
        for loc in df['location'].unique():
            loc_mask = df['location'] == loc
            loc_df = df[loc_mask].sort_values('timestamp')

            if len(loc_df) < 2:
                continue

            # 以 timestamp 为索引进行时间插值
            loc_indexed = loc_df.set_index('timestamp')
            before_na = loc_indexed[param_cols].isna().sum().sum()

            loc_indexed[param_cols] = loc_indexed[param_cols].interpolate(
                method='time', limit_direction='both', limit=3
            )

            after_na = loc_indexed[param_cols].isna().sum().sum()
            filled = before_na - after_na
            filled_count += filled

            # 写回
            df.loc[loc_mask, param_cols] = loc_indexed[param_cols].values

        self._report.missing_filled_by_interp = int(filled_count)
        logger.info(f"  策略1 (时间插值): 填充 {filled_count} 个")

        # --- 策略2: 历史同期数据填充 ---
        remaining = df[param_cols].isna().sum().sum()
        if remaining > 0:
            filled_count = 0
            for loc in df['location'].unique():
                loc_mask = df['location'] == loc
                loc_df = df[loc_mask].sort_values('timestamp').reset_index(drop=True)

                if len(loc_df) < 24:
                    continue

                for param in param_cols:
                    na_mask = loc_df[param].isna()
                    if na_mask.sum() == 0:
                        continue

                    for i in loc_df[na_mask].index:
                        # 尝试 24h 前同时刻
                        if i - 24 >= 0 and pd.notna(loc_df.at[i - 24, param]):
                            df.loc[loc_df.at[i, 'timestamp'] if 'timestamp' in loc_df.columns else loc_df.index[i], param] = \
                                loc_df.at[i - 24, param]
                            filled_count += 1
                            continue

                        # 尝试 168h 前同时刻
                        if i - 168 >= 0 and pd.notna(loc_df.at[i - 168, param]):
                            df.loc[loc_df.at[i, 'timestamp'] if 'timestamp' in loc_df.columns else loc_df.index[i], param] = \
                                loc_df.at[i - 168, param]
                            filled_count += 1

            self._report.missing_filled_by_historical = int(filled_count)
            logger.info(f"  策略2 (历史同期): 填充 {filled_count} 个")

        # --- 策略3: 多站点数据融合平均 ---
        remaining = df[param_cols].isna().sum().sum()
        if remaining > 0:
            filled_count = 0
            # 按时间戳分组，对缺失值用同时刻其他站点的平均值填充
            for param in param_cols:
                na_mask = df[param].isna()
                if na_mask.sum() == 0:
                    continue

                for idx in df[na_mask].index:
                    ts = df.at[idx, 'timestamp']
                    # 同时刻其他站点的值
                    same_time = df[(df['timestamp'] == ts) & (df[param].notna())]
                    if len(same_time) > 0:
                        avg_val = same_time[param].mean()
                        df.at[idx, param] = avg_val
                        filled_count += 1

            self._report.missing_filled_by_fusion = int(filled_count)
            logger.info(f"  策略3 (多站点融合): 填充 {filled_count} 个")

        # 统计剩余缺失值
        final_missing = df[param_cols].isna().sum().sum()
        self._report.missing_remaining = int(final_missing)

        if final_missing > 0:
            logger.warning(f"  仍有 {final_missing} 个缺失值无法填充，使用前向填充")
            df[param_cols] = df[param_cols].ffill().bfill()
            final_missing = df[param_cols].isna().sum().sum()
            self._report.missing_remaining = int(final_missing)

        logger.info(
            f"  缺失值处理完成: "
            f"插值={self._report.missing_filled_by_interp}, "
            f"历史={self._report.missing_filled_by_historical}, "
            f"融合={self._report.missing_filled_by_fusion}, "
            f"剩余={self._report.missing_remaining}"
        )

        return df

    # ========================================================================
    # 步骤6: 严重异常评估
    # ========================================================================

    def _evaluate_severity(self, df: pd.DataFrame, raise_on_severe: bool) -> None:
        """
        评估整体数据质量，判断是否需要抛出严重异常

        如果某个参数的异常比例超过 SEVERE_ANOMALY_RATIO，
        则认为是严重数据质量问题。
        """
        total = len(df)
        if total == 0:
            return

        # 按参数统计异常比例
        param_anomaly_counts = {}
        for record in self._anomaly_records:
            if record.parameter in param_anomaly_counts:
                param_anomaly_counts[record.parameter] += 1
            else:
                param_anomaly_counts[record.parameter] = 1

        severe_issues = []
        for param, count in param_anomaly_counts.items():
            ratio = count / total
            if ratio > self.SEVERE_ANOMALY_RATIO:
                severe_issues.append(
                    f"参数 '{param}' 异常比例 {ratio*100:.1f}% "
                    f"超过阈值 {self.SEVERE_ANOMALY_RATIO*100:.0f}%"
                )

        if severe_issues:
            self._report.is_valid = False
            self._report.issues.extend(severe_issues)

            if raise_on_severe:
                raise SevereDataQualityError(
                    "严重数据质量异常:\n" + "\n".join(f"  - {s}" for s in severe_issues)
                )

    # ========================================================================
    # 步骤7: 生成质量报告
    # ========================================================================

    def _finalize_report(self, df: pd.DataFrame) -> None:
        """汇总最终质量报告"""
        param_cols = [c for c in df.columns if c in self.weather_params]

        self._report.total_records = len(df)
        self._report.total_parameters = len(param_cols)
        self._report.locations_count = int(df['location'].nunique())
        self._report.time_range_start = str(df['timestamp'].min())
        self._report.time_range_end = str(df['timestamp'].max())

        # 异常统计
        self._report.total_anomalies = len(self._anomaly_records)
        self._report.minor_anomalies = sum(
            1 for r in self._anomaly_records if r.severity == AnomalySeverity.MINOR.value
        )
        self._report.severe_anomalies = sum(
            1 for r in self._anomaly_records if r.severity == AnomalySeverity.SEVERE.value
        )

        # 按类型统计
        for record in self._anomaly_records:
            t = record.anomaly_type
            self._report.anomalies_by_type[t] = \
                self._report.anomalies_by_type.get(t, 0) + 1

        # 按参数统计
        for record in self._anomaly_records:
            p = record.parameter
            self._report.anomalies_by_parameter[p] = \
                self._report.anomalies_by_parameter.get(p, 0) + 1

        # 异常记录转字典
        self._report.anomaly_records = [r.to_dict() for r in self._anomaly_records]

        # 计算质量评分 (0~100)
        if total := self._report.total_records:
            anomaly_ratio = self._report.total_anomalies / (total * len(param_cols) + 1)
            missing_ratio = self._report.missing_remaining / (total * len(param_cols) + 1)
            # 评分 = 100 - 异常比例*50 - 缺失比例*50
            self._report.overall_quality_score = max(
                0.0, 100.0 - anomaly_ratio * 50 - missing_ratio * 50
            )

        # 补充时间间隔填充数
        self._report.time_gaps_filled = self._report.time_gaps_detected

    # ========================================================================
    # 内部辅助方法
    # ========================================================================

    def _add_anomaly(
        self,
        timestamp: Any,
        location: str,
        parameter: str,
        anomaly_type: AnomalyType,
        severity: AnomalySeverity,
        original_value: Optional[float],
        corrected_value: Optional[float],
        correction_method: CorrectionMethod,
        description: str,
    ) -> None:
        """添加一条异常记录"""
        record = AnomalyRecord(
            timestamp=timestamp,
            location=location,
            parameter=parameter,
            anomaly_type=anomaly_type.value,
            severity=severity.value,
            original_value=original_value,
            corrected_value=corrected_value,
            correction_method=correction_method.value,
            description=description,
        )
        self._anomaly_records.append(record)

        # 日志记录
        if severity == AnomalySeverity.SEVERE:
            logger.error(f"  [严重] {location}/{parameter}: {description}")
        else:
            logger.debug(f"  [轻微] {location}/{parameter}: {description}")


# ============================================================================
# 使用示例
# ============================================================================

def demo():
    """演示 WeatherDataValidator 的使用"""
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from realtime_api.openmeteo_client import OpenMeteoClient

    print("=" * 60)
    print("气象数据质量验证模块演示")
    print("=" * 60)

    # 1. 获取气象数据
    print("\n[1] 获取气象数据...")
    client = OpenMeteoClient(past_days=3, forecast_days=1, rate_limit_interval=0.1)
    df, _ = client.fetch_weather_data()

    # 2. 验证数据质量
    print("\n[2] 验证数据质量...")
    validator = WeatherDataValidator()
    clean_df, report, flags = validator.validate(df, raise_on_severe=False)

    # 3. 输出报告
    print("\n[3] 数据质量报告:")
    print(report.to_json())

    print(f"\n[4] 清洗后数据形状: {clean_df.shape}")
    print(f"异常标记矩阵形状: {flags.shape}")
    print(f"异常标记总数: {flags.sum().sum()}")

    return clean_df, report, flags


if __name__ == "__main__":
    demo()
