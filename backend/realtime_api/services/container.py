"""
智能电网负荷预测系统 - 全局服务容器

管理所有业务模块的生命周期，由 app.py 的 lifespan 初始化。
路由模块通过此容器访问共享服务实例。

作者: 毕业设计项目
"""

import os
import sys
import logging
from typing import Optional
from zoneinfo import ZoneInfo
from datetime import datetime

# 项目路径
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from realtime_api.config_manager import get_config
from realtime_api.openmeteo_client import OpenMeteoClient
from realtime_api.weather_validator import WeatherDataValidator
from realtime_api.feature_generator import FeatureGenerator
from realtime_api.normalization_adapter import NormalizationAdapter
from realtime_api.prediction_service import ModelInferenceService
from realtime_api.pv_inference_service import PVInferenceService
from realtime_api.wind_estimator import WindPowerEstimator

logger = logging.getLogger(__name__)

# ============================================================================
# 时区工具函数
# ============================================================================

_EST = ZoneInfo("America/New_York")


def eastern_now() -> datetime:
    """返回当前新英格兰地区时间（naive datetime，不含时区信息）"""
    return datetime.now(_EST).replace(tzinfo=None)


def eastern_now_hour() -> datetime:
    """返回当前新英格兰地区时间，截断到整点（分钟/秒/微秒归零）

    用于预测时间戳对齐：Open-Meteo 返回整点数据，
    预测 target_timestamp 也必须是整点，
    否则历史负荷合并 (df.index.map) 会因时间戳不匹配而失败。
    """
    now = eastern_now()
    return now.replace(minute=0, second=0, microsecond=0)


# ============================================================================
# 光伏发电物理估算器
# ============================================================================

class SolarEstimator:
    """
    光伏发电估算器（物理模型回退）

    基于短波辐射估算光伏发电量:
      PV_output = (radiation / 1000) * installed_capacity * performance_ratio

    新英格兰地区参数:
      - 装机容量: 500 MW (公用事业级)
      - 性能比: 0.80 (考虑损耗)
      - 温度衰减: 高温时效率下降
    """

    def __init__(
        self,
        installed_capacity_mw: float = 500.0,
        performance_ratio: float = 0.80,
    ):
        self.installed_capacity = installed_capacity_mw
        self.performance_ratio = performance_ratio

    def estimate(self, radiation: float, temperature: float = 25.0) -> float:
        """
        估算光伏发电量

        Args:
            radiation: 短波辐射 (W/m²)
            temperature: 温度 (°C)，用于温度衰减

        Returns:
            光伏发电量 (MW)
        """
        if radiation <= 0:
            return 0.0

        base_output = (radiation / 1000.0) * self.installed_capacity * self.performance_ratio
        temp_loss = max(0, (temperature - 25.0) * 0.004)
        actual_output = base_output * (1.0 - temp_loss)

        return max(0, actual_output)


# ============================================================================
# 全局服务容器
# ============================================================================

class ServiceContainer:
    """服务容器：管理所有业务模块的生命周期"""

    # 业务服务
    openmeteo_client: Optional[OpenMeteoClient] = None
    weather_validator: Optional[WeatherDataValidator] = None
    feature_generator: Optional[FeatureGenerator] = None
    normalizer: Optional[NormalizationAdapter] = None
    inference_service: Optional[ModelInferenceService] = None
    pv_inference_service: Optional[PVInferenceService] = None

    # 估算器
    solar_estimator: Optional[SolarEstimator] = None
    wind_estimator: Optional[WindPowerEstimator] = None

    # 运行时状态
    start_time: float = 0.0


# 全局单例
services = ServiceContainer()


# ============================================================================
# 初始化服务（在 lifespan 中调用）
# ============================================================================

def init_services() -> None:
    """初始化所有业务服务（不含数据库，数据库由 init_database 异步初始化）"""
    config = get_config()

    # 1. OpenMeteoClient
    logger.info("[1/8] 初始化 OpenMeteoClient...")
    locations = config.get_weather_locations()
    openmeteo_config = config.get_openmeteo_config()
    services.openmeteo_client = OpenMeteoClient(
        past_days=openmeteo_config.get('past_days', 7),
        forecast_days=openmeteo_config.get('forecast_days', 2),
        rate_limit_interval=openmeteo_config.get('rate_limit_interval', 1.5),
        cache_ttl=openmeteo_config.get('cache_ttl', 300),
    )

    # 2. WeatherDataValidator
    logger.info("[2/8] 初始化 WeatherDataValidator...")
    services.weather_validator = WeatherDataValidator()

    # 3. FeatureGenerator
    logger.info("[3/8] 初始化 FeatureGenerator...")
    services.feature_generator = FeatureGenerator()

    # 4. NormalizationAdapter
    logger.info("[4/8] 初始化 NormalizationAdapter...")
    services.normalizer = NormalizationAdapter()

    # 5. 负荷预测模型
    logger.info("[5/8] 加载负荷预测模型 (可能需要几秒)...")
    services.inference_service = ModelInferenceService()
    services.inference_service.load_models()

    # 6. 光伏 ML 预测模型
    logger.info("[6/8] 加载光伏 ML 预测模型...")
    try:
        services.pv_inference_service = PVInferenceService()
        services.pv_inference_service.load_models()
    except Exception as e:
        logger.warning(f"⚠️ 光伏 ML 模型加载失败: {e}，将退回物理模型")
        services.pv_inference_service = None

    # 7. 光伏物理估算器
    logger.info("[7/8] 初始化光伏物理估算器...")
    solar_config = config.get_solar_config()
    services.solar_estimator = SolarEstimator(
        installed_capacity_mw=solar_config.get('installed_capacity_mw', 500.0),
        performance_ratio=solar_config.get('performance_ratio', 0.80)
    )

    # 8. 风电估算器
    logger.info("[8/8] 初始化风电估算器...")
    wind_config = config.get_wind_config() if hasattr(config, 'get_wind_config') else {}
    services.wind_estimator = WindPowerEstimator(
        latitude=42.36,
        longitude=-71.06,
        elevation=300.0,
        installed_capacity_mw=wind_config.get('installed_capacity_mw', 1500.0),
        turbine_type=wind_config.get('turbine_type', 'onshore_2mw'),
        wind_shear_alpha=wind_config.get('wind_shear_alpha', 0.22),
        wake_loss=wind_config.get('wake_loss', 0.10),
        availability=wind_config.get('availability', 0.95),
    )

    logger.info("=" * 60)
    logger.info("✅ 服务容器初始化完成")
    logger.info(f"   负荷推理设备: {services.inference_service.device}")
    logger.info(f"   负荷模型数量: {len(services.inference_service.models)}")
    if services.pv_inference_service:
        logger.info(f"   光伏 ML 模型: ✅ 已加载 ({len(services.pv_inference_service.models)} 个模型)")
    else:
        logger.info(f"   光伏 ML 模型: ❌ 未加载 (使用物理模型)")
    logger.info("=" * 60)


def release_services() -> None:
    """释放服务资源（在 lifespan 关闭时调用）"""
    logger.info("释放服务资源...")
    if services.inference_service:
        services.inference_service.release()
    logger.info("✅ 服务资源已释放")
