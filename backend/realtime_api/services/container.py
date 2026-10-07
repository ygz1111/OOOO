"""
智能电网负荷预测系统 - 全局服务容器

管理所有业务模块的生命周期，由 app.py 的 lifespan 初始化。
路由模块通过此容器访问共享服务实例。

作者: 毕业设计项目
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Any, Optional
from zoneinfo import ZoneInfo
from datetime import datetime

# 项目路径
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from realtime_api.config_manager import get_config
from realtime_api.openmeteo_client import OpenMeteoClient
from realtime_api.weather_validator import WeatherDataValidator

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
# 全局服务容器
# ============================================================================

class ServiceContainer:
    """服务容器：管理所有业务模块的生命周期"""

    # 业务服务
    openmeteo_client: Optional[OpenMeteoClient] = None
    weather_validator: Optional[WeatherDataValidator] = None
    # TensorFlow 模型服务 (MMXX 训练产物接入, 2026-09)
    tf_load_price_service: Optional[Any] = None
    tf_pv_service: Optional[Any] = None
    tf_realtime_feature_provider: Optional[Any] = None

    # 运行时状态
    start_time: float = 0.0


# 全局单例
services = ServiceContainer()


# ============================================================================
# TF 引擎开关辅助 (2026-09: 独立负荷、电价与 pv_v2 接入)
# ============================================================================

def tf_engines_enabled() -> bool:
    """总开关: 配置 models.engines.enabled 且未被环境变量 TF_ENGINE_DISABLED 关闭"""
    if os.getenv('TF_ENGINE_DISABLED', '').strip().lower() == 'true':
        return False
    cfg = get_config().get('models.engines', {}) if hasattr(get_config(), 'get') else {}
    return bool(cfg.get('enabled', True))


def get_engine_config() -> dict:
    """返回模型引擎配置的普通字典。"""
    config = get_config()
    cfg = config.get('models.engines', {}) if hasattr(config, 'get') else {}
    return cfg if isinstance(cfg, dict) else {}


def selected_load_backend() -> str:
    backend = str(get_engine_config().get('load_backend', 'tf_split_v1')).strip().lower()
    return backend if backend in ('tf_v2', 'tf_split_v1') else 'tf_split_v1'


def selected_pv_backend() -> str:
    return 'tf_pv'


def prediction_backend_ready() -> bool:
    """判断当前 TensorFlow 负荷预测引擎是否就绪。"""
    return bool(services.tf_load_price_service and services.tf_load_price_service.is_ready)


def active_load_service() -> Optional[Any]:
    """返回当前 TensorFlow 负荷预测服务。"""
    return services.tf_load_price_service


def active_model_runtime_stats() -> dict:
    """为状态页提供当前生产模型的统一运行统计和独立模型明细。"""
    backend = selected_load_backend()
    if backend in ('tf_v2', 'tf_split_v1'):
        load_service = services.tf_load_price_service
        load_status = load_service.get_status() if load_service else {}
        if load_service:
            raw_details = load_service.get_model_info()
        elif backend == 'tf_split_v1':
            raw_details = {
                'tf_load_split_v1': {'label': 'TensorFlow 负荷预测模型（TF Split v1）', 'task': '未来24小时负荷预测', 'architecture': 'BiGRU-GRU', 'loaded': False},
                'tf_price_split_v1': {'label': 'TensorFlow 电价预测模型（TF Split v1）', 'task': '未来24小时P10/P50/P90电价预测', 'architecture': 'BiGRU-GRU Quantile', 'loaded': False},
            }
        else:
            raw_details = {'tf_v2': {'label': 'TensorFlow TF v2 负荷+电价联合模型', 'task': '负荷与电价联合预测', 'architecture': 'GRU-192', 'loaded': False}}

        model_details = [
            {
                'id': model_id,
                'name': info.get('label') or info.get('name') or model_id,
                'task': info.get('task', '预测'),
                'architecture': info.get('architecture') or info.get('config', {}).get('encoder', ''),
                'framework': 'TensorFlow',
                'loaded': bool(info.get('loaded', False)),
            }
            for model_id, info in raw_details.items()
        ]

        if selected_pv_backend() == 'tf_pv':
            pv_info = services.tf_pv_service.get_model_info() if services.tf_pv_service else {
                'pv_v2': {'label': 'TensorFlow 光伏预测模型（PV v2）', 'loaded': False}
            }
            for model_id, info in pv_info.items():
                model_details.append({
                    'id': model_id,
                    'name': info.get('label') or info.get('name') or 'TensorFlow 光伏预测模型（PV v2）',
                    'task': info.get('task', '未来24小时光伏发电预测'),
                    'architecture': info.get('architecture') or info.get('config', {}).get('encoder', 'TCN-GRU-Attention'),
                    'framework': 'TensorFlow',
                    'loaded': bool(info.get('loaded', False)),
                })

        loaded_details = [item for item in model_details if item['loaded']]
        status_times = [float(load_status.get('average_inference_time_ms', 0.0))]
        total_inferences = int(load_status.get('total_inferences', 0))
        if services.tf_pv_service:
            pv_status = services.tf_pv_service.get_status()
            status_times.append(float(pv_status.get('average_inference_time_ms', 0.0)))
            total_inferences += int(pv_status.get('total_inferences', 0))
        return {
            'models_loaded': len(loaded_details),
            'models_total': len(model_details),
            'device': 'tensorflow',
            'total_inferences': total_inferences,
            'average_time_ms': max(status_times, default=0.0),
            'ensemble_weights': {item['id']: 1.0 for item in loaded_details},
            'model_details': model_details,
            'backend': backend,
        }
    return {
        'models_loaded': 0,
        'models_total': 1,
        'device': backend,
        'total_inferences': 0,
        'average_time_ms': 0.0,
        'ensemble_weights': {},
        'model_details': [],
        'backend': backend,
    }


def tf_load_backend_active() -> bool:
    """负荷+电价默认引擎是否为 tf_v2 (且服务可用)"""
    if not tf_engines_enabled():
        return False
    if not (services.tf_load_price_service and services.tf_load_price_service.is_ready):
        return False
    return selected_load_backend() in ('tf_v2', 'tf_split_v1')


def tf_pv_backend_active() -> bool:
    """光伏默认引擎是否为 tf_pv (pv_v2) (且服务可用)"""
    if not tf_engines_enabled():
        return False
    if not (services.tf_pv_service and services.tf_pv_service.is_ready):
        return False
    return selected_pv_backend() == 'tf_pv'


# ============================================================================
# 初始化服务（在 lifespan 中调用）
# ============================================================================

def init_services() -> None:
    """初始化所有业务服务（不含数据库，数据库由 init_database 异步初始化）"""
    config = get_config()

    # 1. OpenMeteoClient
    logger.info("[1/4] 初始化 OpenMeteoClient...")
    locations = config.get_weather_locations()
    openmeteo_config = config.get_openmeteo_config()
    services.openmeteo_client = OpenMeteoClient(
        # 独立 TF 模型需要 168h 输入及其中的 168h 滞后/滚动特征。
        past_days=max(openmeteo_config.get('past_days', 7), 16)
        if selected_load_backend() in ('tf_v2', 'tf_split_v1') else openmeteo_config.get('past_days', 7),
        forecast_days=openmeteo_config.get('forecast_days', 2),
        rate_limit_interval=openmeteo_config.get('rate_limit_interval', 1.5),
        cache_ttl=openmeteo_config.get('cache_ttl', 300),
    )

    # 2. WeatherDataValidator
    logger.info("[2/4] 初始化 WeatherDataValidator...")
    services.weather_validator = WeatherDataValidator()

    engine_cfg = get_engine_config()
    load_backend = selected_load_backend()
    pv_backend = selected_pv_backend()
    strict_startup = bool(engine_cfg.get('strict_startup', True))

    # 各 TensorFlow 服务加载自己的冻结特征契约和 Scaler。
    # 旧 38 维特征/MinMax 工具仅供离线研究，不应成为生产启动依赖。
    # 3. TensorFlow 负荷与电价模型。
    if tf_engines_enabled() and load_backend in ('tf_v2', 'tf_split_v1'):
        logger.info("[3/4] 加载 TensorFlow 负荷+电价模型 (%s)...", load_backend)
        try:
            if load_backend == 'tf_split_v1':
                from realtime_api.tf_split_service import TFSplitService
                services.tf_load_price_service = TFSplitService()
            else:
                from realtime_api.tf_load_price_service import TFLoadPriceService
                services.tf_load_price_service = TFLoadPriceService()
            services.tf_load_price_service.load_models()
        except Exception as e:
            services.tf_load_price_service = None
            if strict_startup:
                raise RuntimeError(f"TF v2 负荷+电价模型加载失败: {e}") from e
            logger.error(f"❌ TF v2 负荷+电价模型加载失败: {e}")
    else:
        services.tf_load_price_service = None

    # 4. TensorFlow 光伏模型。
    if tf_engines_enabled() and pv_backend == 'tf_pv':
        logger.info("[4/4] 加载 TensorFlow pv_v2 光伏模型 (TCN-GRU-Attention)...")
        try:
            from realtime_api.tf_pv_v2_service import TFPVV2Service
            services.tf_pv_service = TFPVV2Service()
            services.tf_pv_service.load_models()
        except Exception as e:
            services.tf_pv_service = None
            if strict_startup:
                raise RuntimeError(f"TF pv_v2 光伏模型加载失败: {e}") from e
            logger.error(f"❌ TF pv_v2 光伏模型加载失败: {e}")
    else:
        services.tf_pv_service = None

    # 在线特征适配器不加载/训练模型，仅在 live 推理时访问 ISO-NE。
    services.tf_realtime_feature_provider = None
    if tf_engines_enabled() and (load_backend in ('tf_v2', 'tf_split_v1') or pv_backend == 'tf_pv'):
        from realtime_api.tf_realtime_feature_provider import TFRealtimeFeatureProvider
        services.tf_realtime_feature_provider = TFRealtimeFeatureProvider(
            cache_ttl=openmeteo_config.get('cache_ttl', 300)
        )

    logger.info("=" * 60)
    logger.info("✅ 服务容器初始化完成")
    runtime = active_model_runtime_stats()
    logger.info(f"   负荷引擎: {runtime['backend']}")
    logger.info(f"   负荷推理设备: {runtime['device']}")
    logger.info(f"   生产模型数量: {runtime['models_loaded']}/{runtime['models_total']}")
    for detail in runtime.get('model_details', []):
        marker = '✅' if detail['loaded'] else '❌'
        logger.info(f"   {marker} {detail['name']} [{detail['id']}]")
    logger.info("=" * 60)


def release_services() -> None:
    """释放服务资源（在 lifespan 关闭时调用）"""
    logger.info("释放服务资源...")
    for svc in (services.tf_load_price_service,
                services.tf_pv_service):
        if svc is not None and hasattr(svc, 'release'):
            try:
                svc.release()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"释放服务失败(非阻塞): {e}")
    logger.info("✅ 服务资源已释放")
