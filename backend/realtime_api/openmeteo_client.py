"""
智能电网负荷预测系统 - Open-Meteo API 客户端

功能:
  1. 获取美国新英格兰地区 6 个气象站点的实时气象数据
  2. 支持历史数据获取 (past_days=7) 和预测数据获取 (forecast_days=2)
  3. 请求频率限制，避免 API 限流
  4. 自动重试机制，网络异常时指数退避重试
  5. 数据验证和基本清洗（范围检查、缺失值插值）
  6. 返回标准化 Pandas DataFrame，时区统一为 America/New_York

依赖:
  pip install requests pandas numpy

作者: 毕业设计项目
"""

import time
import logging
import json
import threading
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Union, Any, Tuple
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 导入配置管理器
from realtime_api.config_manager import config_manager


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
# 数据类定义
# ============================================================================

@dataclass
class WeatherLocation:
    """气象站点位置信息"""
    name: str
    lat: float
    lon: float

    def __repr__(self) -> str:
        return f"WeatherLocation(name='{self.name}', lat={self.lat}, lon={self.lon})"


@dataclass
class DataQualityReport:
    """数据质量报告"""
    location: str
    total_records: int = 0
    missing_values: int = 0
    outliers_detected: int = 0
    outliers_corrected: int = 0
    timestamps_expected: int = 0
    timestamps_actual: int = 0
    time_gaps: int = 0
    is_valid: bool = True
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'location': self.location,
            'total_records': self.total_records,
            'missing_values': self.missing_values,
            'outliers_detected': self.outliers_detected,
            'outliers_corrected': self.outliers_corrected,
            'timestamps_expected': self.timestamps_expected,
            'timestamps_actual': self.timestamps_actual,
            'time_gaps': self.time_gaps,
            'is_valid': self.is_valid,
            'issues': self.issues,
        }


# ============================================================================
# 主客户端类
# ============================================================================

class OpenMeteoClient:
    """
    Open-Meteo API 气象数据采集客户端

    用于获取美国新英格兰地区多个气象站点的实时和历史气象数据，
    支持请求频率限制、自动重试、数据验证和清洗。

    Attributes:
        locations: 气象站点列表
        timezone: 目标时区 (默认 America/New_York)
        api_url: Open-Meteo API 地址
        weather_params: 请求的气象参数列表
        past_days: 获取的历史天数
        forecast_days: 获取的预测天数
        rate_limit_interval: 请求间隔(秒)，避免 API 限流
        max_retries: 最大重试次数
        retry_backoff: 重试退避因子(秒)
        request_timeout: 请求超时(秒)
        session: requests Session 对象
    """

    # Open-Meteo API 基础地址
    API_URL = "https://api.open-meteo.com/v1/forecast"

    # 默认请求的气象参数
    DEFAULT_WEATHER_PARAMS = [
        "temperature_2m",        # 干球温度 (°C)
        "dew_point_2m",          # 露点温度 (°C)
        "relative_humidity_2m",   # 相对湿度 (%)
        "wind_speed_10m",         # 风速 (m/s)
        "wind_direction_10m",     # 风向 (°)
        "surface_pressure",       # 地面气压 (hPa)
        "cloud_cover",            # 云量 (%)
        "cloud_cover_low",        # 低层云量 (%) — 光伏 ML 模型特征
        "cloud_cover_mid",        # 中层云量 (%) — 光伏 ML 模型特征
        "cloud_cover_high",       # 高层云量 (%) — 光伏 ML 模型特征
        "shortwave_radiation",    # 短波辐射 (W/m²) ≈ GHI
        "direct_radiation",       # 直接辐射 (W/m²) ≈ DNI — 光伏 ML 模型特征
        "diffuse_radiation",      # 散射辐射 (W/m²) ≈ DHI — 光伏 ML 模型特征
    ]

    # 新英格兰地区气象参数合理范围（用于数据验证）
    VALIDATION_RANGES = {
        "temperature_2m":       (-40.0, 50.0),   # °C
        "dew_point_2m":         (-45.0, 35.0),   # °C
        "relative_humidity_2m": (0.0, 100.0),     # %
        "wind_speed_10m":       (0.0, 60.0),      # m/s
        "wind_direction_10m":   (0.0, 360.0),     # °
        "surface_pressure":     (900.0, 1100.0),  # hPa
        "cloud_cover":          (0.0, 100.0),     # %
        "cloud_cover_low":      (0.0, 100.0),     # %
        "cloud_cover_mid":      (0.0, 100.0),     # %
        "cloud_cover_high":     (0.0, 100.0),     # %
        "shortwave_radiation":  (0.0, 1400.0),    # W/m²
        "direct_radiation":     (0.0, 1200.0),    # W/m²
        "diffuse_radiation":    (0.0, 800.0),     # W/m²
    }

    def __init__(
        self,
        locations: Optional[List[Union[WeatherLocation, Dict]]] = None,
        weather_params: Optional[List[str]] = None,
        past_days: int = 7,
        forecast_days: int = 2,
        timezone_str: str = "America/New_York",
        rate_limit_interval: float = 1.5,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        request_timeout: int = 30,
        cache_ttl: int = 300,
    ):
        """
        初始化 Open-Meteo API 客户端

        Args:
            locations: 气象站点列表，可以是 WeatherLocation 对象或字典列表。
                       默认使用新英格兰地区 6 个站点。
            weather_params: 请求的气象参数列表，默认使用 6 个核心参数。
            past_days: 获取的历史天数，默认 7 天。
            forecast_days: 获取的预测天数，默认 2 天。
            timezone_str: 目标时区，默认 America/New_York。
            rate_limit_interval: 请求间隔(秒)，默认 1.5 秒（Open-Meteo 免费版安全值）。
            max_retries: 最大重试次数，默认 3 次。
            retry_backoff: 重试退避因子(秒)，默认 1.0 秒。
            request_timeout: 请求超时(秒)，默认 30 秒。
            cache_ttl: 缓存有效期(秒)，默认 300 秒（5 分钟）。
        """
        # 解析气象站点 - 优先使用传入的，其次使用配置，最后使用默认
        if locations is None:
            # 从配置管理器加载默认站点
            try:
                raw_locations = config_manager.get_weather_locations()
                self.locations = [
                    WeatherLocation(name=loc["name"], lat=loc["lat"], lon=loc["lon"])
                    for loc in raw_locations
                ]
                if not self.locations:
                    raise ValueError("配置文件中没有可用的气象站点")
            except Exception as e:
                # 配置加载失败，使用硬编码默认值作为后备方案
                logging.warning(f"配置加载失败: {e}，使用默认站点")
                self.locations = [
                    WeatherLocation(name="Boston", lat=42.3601, lon=-71.0589),
                    WeatherLocation(name="Hartford", lat=41.7637, lon=-72.6851),
                    WeatherLocation(name="Portland", lat=43.6615, lon=-70.2553),
                    WeatherLocation(name="Manchester", lat=42.9956, lon=-71.4548),
                    WeatherLocation(name="Providence", lat=41.8240, lon=-71.4128),
                    WeatherLocation(name="Burlington", lat=44.4759, lon=-73.2121),
                ]
        else:
            self.locations = [
                WeatherLocation(name=loc["name"], lat=loc["lat"], lon=loc["lon"])
                if isinstance(loc, dict) else loc
                for loc in locations
            ]

        # 气象参数
        self.weather_params = weather_params or list(self.DEFAULT_WEATHER_PARAMS)

        # API 参数
        self.past_days = past_days
        self.forecast_days = forecast_days
        self.timezone_str = timezone_str
        self.rate_limit_interval = rate_limit_interval
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.request_timeout = request_timeout

        # 上次请求时间（用于频率限制）
        self._last_request_time: float = 0.0
        self._rate_limit_lock = threading.Lock()

        # 天气数据缓存（避免短时间内重复请求 API）
        self._cache_ttl = cache_ttl
        self._cache_lock = threading.Lock()
        self._cached_df: Optional[pd.DataFrame] = None
        self._cached_reports: Optional[Dict[str, DataQualityReport]] = None
        self._cache_timestamp: float = 0.0

        # 并发单飞（2026-08 修复）：首屏多个请求（prediction/load、weather/current、
        # overview）会同时触发全量气象拉取，各自串行请求 6 站点（约 15-20s）。
        # 通过条件变量让并发请求共享同一次拉取结果，避免重复拉取与限流。
        # 复用 _cache_lock 作为条件变量底层锁，避免双锁交叉等待。
        self._fetch_cond = threading.Condition(self._cache_lock)
        self._fetching = False
        self._last_fetch_failed = False

        # 创建带重试机制的 requests Session
        self.session = self._create_session()

        logger.info(f"OpenMeteoClient 初始化完成")
        logger.info(f"  气象站点数: {len(self.locations)}")
        logger.info(f"  气象参数: {self.weather_params}")
        logger.info(f"  历史天数: {self.past_days}, 预测天数: {self.forecast_days}")
        logger.info(f"  时区: {self.timezone_str}")
        logger.info(f"  请求间隔: {self.rate_limit_interval}s, 超时: {self.request_timeout}s")

    # ========================================================================
    # Session 和重试机制
    # ========================================================================

    def _create_session(self) -> requests.Session:
        """
        创建带重试机制的 requests Session

        Returns:
            requests.Session: 配置了重试策略的 Session 对象
        """
        session = requests.Session()

        # 配置 urllib3 重试策略
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.retry_backoff,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _enforce_rate_limit(self) -> None:
        """执行请求频率限制，确保请求间隔（线程安全）"""
        with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.rate_limit_interval:
                sleep_time = self.rate_limit_interval - elapsed
                logger.debug(f"频率限制: 等待 {sleep_time:.2f}s")
                time.sleep(sleep_time)
            self._last_request_time = time.time()

    # ========================================================================
    # API 请求
    # ========================================================================

    def _fetch_single_location(
        self, location: WeatherLocation
    ) -> Optional[Dict[str, Any]]:
        """
        从 Open-Meteo API 获取单个气象站点的数据

        Args:
            location: 气象站点信息

        Returns:
            API 响应的 JSON 数据，失败时返回 None

        Raises:
            requests.RequestException: 当所有重试均失败时
        """
        params = {
            "latitude": location.lat,
            "longitude": location.lon,
            "hourly": ",".join(self.weather_params),
            "past_days": self.past_days,
            "forecast_days": self.forecast_days,
            "timezone": self.timezone_str,
        }

        # 执行频率限制（线程安全）
        self._enforce_rate_limit()

        # 手动重试逻辑（针对 429 限流，使用更长的退避时间）
        max_429_retries = 3
        for attempt in range(max_429_retries + 1):
            try:
                logger.info(f"请求气象数据: {location.name} ({location.lat}, {location.lon})" + 
                           (f" [重试 {attempt}/{max_429_retries}]" if attempt > 0 else ""))

                response = self.session.get(
                    self.API_URL,
                    params=params,
                    timeout=self.request_timeout,
                )

                # 专门处理 429 限流
                if response.status_code == 429:
                    if attempt < max_429_retries:
                        wait_time = 5 * (attempt + 1)  # 5s, 10s, 15s
                        logger.warning(
                            f"  ⚠️ {location.name}: API 限流 (429)，等待 {wait_time}s 后重试..."
                        )
                        time.sleep(wait_time)
                        self._enforce_rate_limit()
                        continue
                    else:
                        logger.error(f"  ❌ {location.name}: API 限流，已重试 {max_429_retries} 次仍失败")
                        return None

                response.raise_for_status()

                data = response.json()
                logger.info(f"  ✅ {location.name}: 获取成功")
                return data

            except requests.exceptions.Timeout:
                logger.error(f"  ❌ {location.name}: 请求超时 ({self.request_timeout}s)")
                return None
            except requests.exceptions.ConnectionError as e:
                logger.error(f"  ❌ {location.name}: 网络连接错误 - {e}")
                return None
            except requests.exceptions.HTTPError as e:
                logger.error(f"  ❌ {location.name}: HTTP错误 - {e}")
                return None
            except json.JSONDecodeError as e:
                logger.error(f"  ❌ {location.name}: JSON解析错误 - {e}")
                return None
            except Exception as e:
                logger.error(f"  ❌ {location.name}: 未知错误 - {e}")
                return None

        return None

    def fetch_weather_data(
        self,
        locations: Optional[List[WeatherLocation]] = None,
        force_refresh: bool = False,
    ) -> Tuple[pd.DataFrame, Dict[str, DataQualityReport]]:
        """
        获取所有气象站点的气象数据

        带缓存机制：如果距上次成功获取不到 cache_ttl 秒，直接返回缓存数据，
        避免短时间内重复调用 API 触发限流。

        Args:
            locations: 指定站点列表，默认使用初始化时的全部站点
            force_refresh: 强制刷新，绕过缓存直接请求 API（用户手动点击刷新时使用）

        Returns:
            Tuple[DataFrame, Dict]:
                - DataFrame: 合并后的标准化气象数据
                - Dict: 各站点的数据质量报告

        Example:
            >>> client = OpenMeteoClient()
            >>> df, reports = client.fetch_weather_data()
            >>> print(df.columns.tolist())
            ['timestamp', 'location', 'temperature_2m', 'dew_point_2m', ...]
            >>> print(f"总记录数: {len(df)}")
        """
        # ── 缓存检查：如果指定了全部站点且缓存有效，直接返回缓存 ──
        # force_refresh=True 时跳过缓存，强制请求 API
        full_location_request = locations is None
        if full_location_request:
            with self._cache_lock:
                if self._cached_df is not None and self._cached_reports is not None:
                    age = time.time() - self._cache_timestamp
                    if not force_refresh and age < self._cache_ttl:
                        logger.info(
                            f"📦 使用缓存气象数据 (年龄: {age:.0f}s, TTL: {self._cache_ttl}s)"
                        )
                        return self._cached_df.copy(), dict(self._cached_reports)

            # ── 并发单飞（2026-08 修复）──
            # 缓存未命中时，多个并发请求（首屏 prediction/load、weather/current、
            # overview 同时触发）共享同一次拉取：首个请求负责拉取并写缓存，
            # 其余请求等待其完成（条件变量）后直接复用缓存结果，避免重复请求 6 站点。
            with self._fetch_cond:
                waited = False
                while self._fetching:
                    waited = True
                    self._fetch_cond.wait(timeout=15)
                if waited and self._last_fetch_failed:
                    raise RuntimeError("并发气象更新失败，请稍后重试")
                # 重新校验年龄，不能把过期缓存永久当作并发请求的新结果。
                if self._cached_df is not None and self._cached_reports is not None:
                    age = time.time() - self._cache_timestamp
                    if (not force_refresh or waited) and age < self._cache_ttl:
                        return self._cached_df.copy(), dict(self._cached_reports)
                    if waited:
                        raise RuntimeError("并发气象更新失败，请稍后重试")
                self._fetching = True
                self._last_fetch_failed = True

        try:
            target_locations = locations or self.locations
            all_dfs: List[pd.DataFrame] = []
            quality_reports: Dict[str, DataQualityReport] = {}
            fetched_locations = []

            logger.info(f"=" * 60)
            logger.info(f"开始获取 {len(target_locations)} 个气象站点的数据")
            logger.info(f"=" * 60)

            for location in target_locations:
                # 1. 获取原始数据
                raw_data = self._fetch_single_location(location)

                if raw_data is None:
                    logger.error(f"跳过 {location.name}：数据获取失败")
                    quality_reports[location.name] = DataQualityReport(
                        location=location.name,
                        is_valid=False,
                        issues=["API请求失败，未获取到数据"],
                    )
                    continue

                # 2. 解析为 DataFrame
                df, report = self._parse_response(raw_data, location)

                # 3. 数据验证和清洗
                df, report = self._validate_and_clean(df, report)

                if df is not None and len(df) > 0 and report.is_valid:
                    all_dfs.append(df)
                    fetched_locations.append({"location": location.name,
                        "latitude": location.lat, "longitude": location.lon,
                        "received_at": datetime.now(timezone.utc).isoformat()})
                    quality_reports[location.name] = report
                    logger.info(
                        f"  📊 {location.name}: {len(df)} 条记录, "
                        f"时间范围 {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}"
                    )
                else:
                    logger.error(f"  ❌ {location.name}: 解析后数据为空或质量校验失败")
                    report.is_valid = False
                    if df is None or len(df) == 0:
                        report.issues.append("解析后数据为空")
                    quality_reports[location.name] = report

            # 合并所有站点数据
            if all_dfs:
                combined_df = pd.concat(all_dfs, ignore_index=True)
                combined_df.attrs["forecast_provenance"] = {
                    "source": "open_meteo_forecast", "endpoint": self.API_URL,
                    "timezone": self.timezone_str, "hourly_variables": list(self.weather_params),
                    "past_days": self.past_days, "forecast_days": self.forecast_days,
                    "locations": fetched_locations, "model_run": None,
                    "run_status": "not_exposed_by_endpoint",
                    "quality": [report.to_dict() for report in quality_reports.values()],
                }
                logger.info(f"\n✅ 数据获取完成: 共 {len(combined_df)} 条记录, "
                            f"{len(target_locations)} 个站点")
                self._print_summary(combined_df, quality_reports)

                # ── 更新缓存（获取全部站点时）──
                # 手动 force_refresh 的新结果也必须替换共享缓存；旧实现只把
                # 数据返回给当前请求，随后普通请求仍会读到刷新前的旧数据。
                if full_location_request:
                    with self._cache_lock:
                        self._cached_df = combined_df.copy()
                        self._cached_reports = dict(quality_reports)
                        self._cache_timestamp = time.time()
                        self._last_fetch_failed = False
                        logger.info(f"📦 气象数据已缓存 (TTL: {self._cache_ttl}s)")
            else:
                combined_df = pd.DataFrame()
                logger.error("❌ 所有站点数据获取失败，返回空DataFrame")

                # 不将无限期过期天气冒充实时输入；页面保留旧图并显示刷新错误。

            return combined_df, quality_reports
        finally:
            # 单飞发起者：无论成功失败都必须释放标志并唤醒等待者
            if full_location_request:
                with self._fetch_cond:
                    self._fetching = False
                    self._fetch_cond.notify_all()

    # ========================================================================
    # 数据解析
    # ========================================================================

    def _parse_response(
        self, raw_data: Dict[str, Any], location: WeatherLocation
    ) -> Tuple[Optional[pd.DataFrame], DataQualityReport]:
        """
        将 API JSON 响应解析为 DataFrame

        Args:
            raw_data: API 返回的 JSON 数据
            location: 气象站点信息

        Returns:
            Tuple[DataFrame, DataQualityReport]: 解析后的数据和初始质量报告
        """
        report = DataQualityReport(location=location.name)

        try:
            hourly_data = raw_data.get("hourly", {})
            if not hourly_data:
                report.is_valid = False
                report.issues.append("响应中没有 hourly 字段")
                logger.error(f"  {location.name}: 响应中没有 hourly 字段")
                return None, report

            # 获取时间戳列表
            timestamps = hourly_data.get("time", [])
            if not timestamps:
                report.is_valid = False
                report.issues.append("响应中没有时间戳数据")
                logger.error(f"  {location.name}: 响应中没有时间戳数据")
                return None, report

            report.timestamps_actual = len(timestamps)

            # 解析时间戳为 datetime
            try:
                dt_index = pd.to_datetime(timestamps)
            except Exception as e:
                report.is_valid = False
                report.issues.append(f"时间戳解析失败: {e}")
                logger.error(f"  {location.name}: 时间戳解析失败 - {e}")
                return None, report

            # 构建 DataFrame
            data_dict = {"timestamp": dt_index, "location": location.name}

            for param in self.weather_params:
                values = hourly_data.get(param, [])
                if len(values) != len(timestamps):
                    logger.warning(
                        f"  {location.name}: {param} 长度不匹配 "
                        f"({len(values)} != {len(timestamps)})"
                    )
                    # 补齐或截断
                    if len(values) < len(timestamps):
                        values = values + [None] * (len(timestamps) - len(values))
                    else:
                        values = values[:len(timestamps)]
                data_dict[param] = values

            df = pd.DataFrame(data_dict)

            report.total_records = len(df)
            report.timestamps_expected = (self.past_days + self.forecast_days) * 24

            logger.debug(f"  {location.name}: 解析完成, {len(df)} 条记录")
            return df, report

        except Exception as e:
            report.is_valid = False
            report.issues.append(f"解析异常: {e}")
            logger.error(f"  {location.name}: 解析异常 - {e}")
            return None, report

    # ========================================================================
    # 数据验证和清洗
    # ========================================================================

    def _validate_and_clean(
        self, df: pd.DataFrame, report: DataQualityReport
    ) -> Tuple[pd.DataFrame, DataQualityReport]:
        """
        数据验证和基本清洗

        检查项目:
          1. 时间连续性（检测时间间隔异常）
          2. 缺失值统计和插值
          3. 物理范围检查（超出合理范围的标记为异常）
          4. 异常值修正（用前后值线性插值替代）

        Args:
            df: 原始数据 DataFrame
            report: 数据质量报告

        Returns:
            Tuple[DataFrame, DataQualityReport]: 清洗后的数据和更新后的报告
        """
        if df is None or len(df) == 0:
            return df, report

        # Open-Meteo 响应中只要混入一个空字符串或非数字值，pandas 就可能把
        # 整列推断为 object。新版 pandas 禁止直接对 object 列插值，因此先把
        # 所有气象参数统一转换为数值；无法解析的值按缺失值进入后续插值流程。
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        param_cols = [c for c in df.columns if c in self.weather_params]
        for param in param_cols:
            df[param] = pd.to_numeric(df[param], errors="coerce")

        # ------ 1. 时间连续性检查 ------
        if len(df) > 1:
            time_diffs = df["timestamp"].diff().dt.total_seconds()
            # 期望间隔为 3600 秒（1 小时）
            gaps = (time_diffs != 3600.0) & (time_diffs.notna())
            gap_count = gaps.sum()
            report.time_gaps = int(gap_count)
            if gap_count > 0:
                report.issues.append(f"检测到 {gap_count} 个时间间隔异常")
                logger.warning(f"  {report.location}: {gap_count} 个时间间隔异常")

        # ------ 2. 缺失值统计和处理 ------
        total_missing = df[param_cols].isna().sum().sum()
        report.missing_values = int(total_missing)

        if total_missing > 0:
            logger.warning(
                f"  {report.location}: 检测到 {total_missing} 个缺失值, 执行线性插值"
            )
            # 使用时间索引进行线性插值
            df_indexed = df.set_index("timestamp")
            df_indexed[param_cols] = df_indexed[param_cols].interpolate(
                method="time", limit_direction="both"
            )
            df = df_indexed.reset_index()

        # ------ 3. 物理范围检查和异常值修正 ------
        for param in param_cols:
            if param not in self.VALIDATION_RANGES:
                continue

            min_val, max_val = self.VALIDATION_RANGES[param]
            mask_outlier = (df[param] < min_val) | (df[param] > max_val)
            outlier_count = mask_outlier.sum()

            if outlier_count > 0:
                report.outliers_detected += int(outlier_count)
                logger.warning(
                    f"  {report.location}: {param} 检测到 {outlier_count} 个异常值 "
                    f"(超出范围 [{min_val}, {max_val}])"
                )
                # 将异常值设为 NaN，然后线性插值
                df.loc[mask_outlier, param] = np.nan

                df_indexed = df.set_index("timestamp")
                df_indexed[param] = df_indexed[param].interpolate(
                    method="time", limit_direction="both"
                )
                df = df_indexed.reset_index()

                report.outliers_corrected += int(outlier_count)
                report.issues.append(
                    f"{param}: {outlier_count} 个异常值已修正"
                )

        # ------ 4. 露点温度逻辑检查 ------
        if "temperature_2m" in df.columns and "dew_point_2m" in df.columns:
            # 露点不应高于气温（物理约束）
            mask = df["dew_point_2m"] > df["temperature_2m"]
            count = mask.sum()
            if count > 0:
                logger.warning(
                    f"  {report.location}: 露点温度高于气温 {count} 次, 修正为等于气温"
                )
                df.loc[mask, "dew_point_2m"] = df.loc[mask, "temperature_2m"]
                report.outliers_corrected += int(count)
                report.issues.append(f"露点高于气温: {count} 次已修正")

        # ------ 5. 最终缺失值检查 ------
        final_missing = df[param_cols].isna().sum().sum()
        if final_missing > 0:
            # 插值后仍有缺失（如全部为 NaN），用前向/后向填充
            df[param_cols] = df[param_cols].ffill().bfill()
            logger.info(f"  {report.location}: 残留缺失值 {final_missing} 个已填充")

        # ------ 5.1 整列全 NaN（API 未返回该参数）------
        # 温度、露点、云量和短波辐射是三个生产模型的关键输入；整列缺失时
        # 不能用“晴天/常温”等默认值伪装成真实观测。该站点会被标为无效并
        # 在多站点合并时排除，让预测管线明确报数据不完整。非关键展示字段
        # 仍可使用物理合理默认值维持气象页面可用。
        critical_model_params = {
            "temperature_2m", "dew_point_2m", "cloud_cover", "shortwave_radiation"
        }
        critical_missing = []
        for param in param_cols:
            if df[param].isna().all():
                default = self._default_value_for(param)
                df[param] = default
                if param in critical_model_params:
                    critical_missing.append(param)
                    logger.error(
                        f"  {report.location}: 模型关键参数 {param} 整列缺失，站点数据无效"
                    )
                    report.issues.append(f"{param}: 模型关键参数整列缺失，站点数据无效")
                else:
                    logger.warning(
                        f"  {report.location}: 参数 {param} 整列缺失，填充默认值 {default}"
                    )
                    report.issues.append(f"{param}: 整列缺失，填充默认值")

        # 更新报告有效性
        report.is_valid = bool(
            report.is_valid
            and report.total_records > 0
            and df[param_cols].isna().sum().sum() == 0
            and not critical_missing
        )

        return df, report

    @staticmethod
    def _default_value_for(param: str) -> float:
        """整列缺失参数的安全默认值（物理合理）"""
        defaults = {
            "temperature_2m": 20.0,        # 常温
            "dew_point_2m": 10.0,          # 低于常温
            "relative_humidity_2m": 60.0,  # 中等湿度
            "wind_speed_10m": 3.0,         # 轻风
            "wind_direction_10m": 270.0,   # 西风（默认风向）
            "surface_pressure": 1013.25,   # 标准大气压
            "cloud_cover": 0.0,            # 晴
            "cloud_cover_low": 0.0,
            "cloud_cover_mid": 0.0,
            "cloud_cover_high": 0.0,
            "shortwave_radiation": 0.0,    # 无辐射
            "direct_radiation": 0.0,
            "diffuse_radiation": 0.0,
        }
        return defaults.get(param, 0.0)

    # ========================================================================
    # 输出和报告
    # ========================================================================

    def _print_summary(
        self,
        df: pd.DataFrame,
        reports: Dict[str, DataQualityReport],
    ) -> None:
        """打印数据获取汇总"""
        logger.info("\n" + "=" * 60)
        logger.info("📊 数据获取汇总")
        logger.info("=" * 60)
        logger.info(f"总记录数: {len(df)}")
        logger.info(f"站点数: {df['location'].nunique()}")
        logger.info(f"时间范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
        logger.info(f"参数列: {[c for c in df.columns if c not in ('timestamp', 'location')]}")
        logger.info("\n数据质量报告:")

        for name, report in reports.items():
            status = "✅ 有效" if report.is_valid else "❌ 异常"
            logger.info(
                f"  {name}: {status} | "
                f"记录={report.total_records}, 缺失={report.missing_values}, "
                f"异常={report.outliers_detected}, 修正={report.outliers_corrected}"
            )
            if report.issues:
                for issue in report.issues:
                    logger.info(f"    - {issue}")

    def get_quality_report_json(
        self, reports: Dict[str, DataQualityReport]
    ) -> str:
        """
        将数据质量报告转为 JSON 字符串

        Args:
            reports: 数据质量报告字典

        Returns:
            str: JSON 格式的质量报告
        """
        report_dict = {name: r.to_dict() for name, r in reports.items()}
        return json.dumps(report_dict, indent=2, ensure_ascii=False)

    # ========================================================================
    # 便捷方法
    # ========================================================================

    def fetch_single_location(
        self, location_name: str
    ) -> Tuple[pd.DataFrame, DataQualityReport]:
        """
        获取单个气象站点的数据

        Args:
            location_name: 站点名称 (如 "Boston")

        Returns:
            Tuple[DataFrame, DataQualityReport]: 该站点的数据和质量报告

        Example:
            >>> client = OpenMeteoClient()
            >>> df, report = client.fetch_single_location("Boston")
        """
        target = None
        for loc in self.locations:
            if loc.name.lower() == location_name.lower():
                target = loc
                break

        if target is None:
            available = [l.name for l in self.locations]
            raise ValueError(
                f"未找到站点: {location_name}. 可用站点: {available}"
            )

        df, reports = self.fetch_weather_data([target])
        report = reports.get(target.name, DataQualityReport(location=target.name))
        return df, report

    def fetch_all_as_dict(self) -> Dict[str, pd.DataFrame]:
        """
        获取所有站点数据，按站点名分组返回字典

        Returns:
            Dict[str, DataFrame]: {站点名: 数据}

        Example:
            >>> client = OpenMeteoClient()
            >>> data = client.fetch_all_as_dict()
            >>> boston_df = data["Boston"]
        """
        combined_df, _ = self.fetch_weather_data()

        result = {}
        for location in self.locations:
            loc_df = combined_df[combined_df["location"] == location.name].copy()
            if len(loc_df) > 0:
                result[location.name] = loc_df.reset_index(drop=True)

        return result

    def get_regional_average(self) -> pd.DataFrame:
        """
        获取所有站点的区域平均值（用于系统级预测）

        将 6 个站点的气象数据取平均值，代表新英格兰地区整体气象状况。

        Returns:
            DataFrame: 区域平均气象数据，列为 timestamp + 各气象参数

        Example:
            >>> client = OpenMeteoClient()
            >>> avg_df = client.get_regional_average()
            >>> print(avg_df.head())
        """
        combined_df, _ = self.fetch_weather_data()

        if combined_df.empty:
            logger.error("无数据可用于计算区域平均值")
            return pd.DataFrame()

        # 按时间戳分组，对气象参数取平均
        param_cols = [c for c in combined_df.columns if c in self.weather_params]
        regional_avg = combined_df.groupby("timestamp")[param_cols].mean().reset_index()
        regional_avg.insert(1, "location", "Regional_Average")

        logger.info(f"区域平均数据: {len(regional_avg)} 条记录")
        return regional_avg


# ============================================================================
# 主函数：演示用法
# ============================================================================

def main():
    """
    演示 OpenMeteoClient 的基本用法
    """
    print("=" * 60)
    print("Open-Meteo API 客户端演示")
    print("=" * 60)

    # 1. 创建客户端
    client = OpenMeteoClient(
        past_days=7,      # 获取过去 7 天
        forecast_days=2,  # 预测未来 2 天
    )

    # 2. 获取所有站点数据
    print("\n[1] 获取全部站点气象数据...")
    df, reports = client.fetch_weather_data()

    print(f"\n数据形状: {df.shape}")
    print(f"列名: {df.columns.tolist()}")
    print(f"\n前5行数据:")
    print(df.head().to_string())

    print(f"\n后5行数据 (预测部分):")
    print(df.tail().to_string())

    # 3. 获取区域平均数据
    print("\n[2] 获取区域平均气象数据...")
    regional_df = client.get_regional_average()
    print(f"区域平均数据形状: {regional_df.shape}")
    print(regional_df.head().to_string())

    # 4. 输出质量报告
    print("\n[3] 数据质量报告:")
    print(client.get_quality_report_json(reports))

    return df, reports


if __name__ == "__main__":
    main()
