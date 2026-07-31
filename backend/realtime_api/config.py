"""
智能电网负荷预测系统 - 配置管理模块

统一管理系统配置，支持:
- YAML配置文件
- 环境变量
- 默认值
- 配置版本管理
- 配置验证

作者: 毕业设计项目
"""

import os
import yaml
import logging
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

# 配置日志
logger = logging.getLogger(__name__)


@dataclass
class WeatherLocation:
    """气象站点数据类"""
    name: str
    lat: float
    lon: float
    state: str = ""
    elevation: float = 0.0
    description: str = ""
    active: bool = True

    def __post_init__(self):
        # 验证经纬度范围
        if not (-90 <= self.lat <= 90):
            raise ValueError(f"纬度 {self.lat} 超出有效范围 [-90, 90]")
        if not (-180 <= self.lon <= 180):
            raise ValueError(f"经度 {self.lon} 超出有效范围 [-180, 180]")


@dataclass
class DatabaseConfig:
    """数据库配置"""
    host: str = "localhost"
    port: int = 3306
    database: str = "OOOO"
    user: str = "root"
    password: str = ""
    pool_size: int = 10
    pool_reset_session: bool = True
    autocommit: bool = True
    use_unicode: bool = True
    charset: str = 'utf8mb4'


@dataclass
class OpenMeteoConfig:
    """OpenMeteo API配置"""
    api_url: str = "https://api.open-meteo.com/v1/forecast"
    past_days: int = 7
    forecast_days: int = 2
    timezone: str = "America/New_York"
    rate_limit_interval: float = 1.5
    request_timeout: float = 10.0
    max_retries: int = 3
    cache_ttl: int = 300


@dataclass
class ModelConfig:
    """模型配置"""
    model_dir: str = "models"
    device: str = "cuda"
    batch_size: int = 16
    cache_ttl: int = 300
    ensemble_weights: Dict[str, float] = field(
        default_factory=lambda: {
            "lstm": 0.25,
            "bigru": 0.25,
            "tcn": 0.25,
            "transformer": 0.25
        }
    )


@dataclass
class SystemConfig:
    """系统配置"""
    env: str = "production"
    log_level: str = "INFO"
    timezone: str = "Asia/Shanghai"
    max_workers: int = 8
    request_timeout: int = 30
    enable_monitoring: bool = True
    secret_key: str = os.getenv("AUTH_JWT_SECRET_KEY", "your-secret-key")
    default_location: str = "Boston"


class ConfigManager:
    """
    配置管理器 - 单例模式
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.config_dir = Path(os.environ.get('CONFIG_DIR', 'config'))
            self._config_data: Dict[str, Any] = {}
            self._locations: List[WeatherLocation] = []
            self._load_config()
            self._initialized = True

    def _load_config(self) -> None:
        """加载配置文件"""
        logger.info("正在加载系统配置...")

        try:
            # 1. 加载位置配置文件
            locations_file = self.config_dir / 'locations.yaml'
            if locations_file.exists():
                with open(locations_file, 'r', encoding='utf-8') as f:
                    locations_config = yaml.safe_load(f)
                    self._load_locations(locations_config)
                    logger.info(f"✅ 位置配置加载成功: {len(self._locations)} 个活跃站点")
            else:
                logger.warning(f"⚠️  配置文件不存在: {locations_file}")
                self._load_default_locations()

            # 2. 加载环境变量覆盖
            self._load_env_overrides()

            logger.info("✅ 系统配置加载完成")

        except Exception as e:
            logger.error(f"❌ 配置加载失败: {e}")
            logger.warning("使用默认配置")
            self._load_default_locations()

    def _load_locations(self, config: Dict[str, Any]) -> None:
        """解析气象站点配置"""
        self._config_data = config

        if 'locations' not in config:
            raise ValueError("配置文件中缺少 locations 字段")

        locations_list = config['locations']
        for loc_data in locations_list:
            try:
                location = WeatherLocation(**loc_data)
                if location.active:
                    self._locations.append(location)
            except Exception as e:
                logger.warning(f"解析站点配置失败 {loc_data.get('name', 'unknown')}: {e}")

        # 按名称排序
        self._locations.sort(key=lambda x: x.name)

    def _load_default_locations(self) -> None:
        """加载默认气象站点(向后兼容)"""
        logger.info("加载默认气象站点配置")

        default_locations = [
            WeatherLocation(name="Boston", lat=42.3601, lon=-71.0589, state="MA"),
            WeatherLocation(name="Hartford", lat=41.7637, lon=-72.6851, state="CT"),
            WeatherLocation(name="Portland", lat=43.6615, lon=-70.2553, state="ME"),
            WeatherLocation(name="Manchester", lat=42.9956, lon=-71.4548, state="NH"),
            WeatherLocation(name="Providence", lat=41.8240, lon=-71.4128, state="RI"),
            WeatherLocation(name="Burlington", lat=44.4759, lon=-73.2121, state="VT"),
        ]

        self._locations = [loc for loc in default_locations if loc.active]

    def _load_env_overrides(self) -> None:
        """环境变量覆盖"""
        # 数据库配置
        if os.environ.get('MYSQL_HOST'):
            self._config_data.setdefault('database', {})['host'] = os.environ['MYSQL_HOST']
        if os.environ.get('MYSQL_PORT'):
            self._config_data.setdefault('database', {})['port'] = int(os.environ['MYSQL_PORT'])
        if os.environ.get('MYSQL_DATABASE'):
            self._config_data.setdefault('database', {})['database'] = os.environ['MYSQL_DATABASE']
        if os.environ.get('MYSQL_USER'):
            self._config_data.setdefault('database', {})['user'] = os.environ['MYSQL_USER']
        if os.environ.get('MYSQL_PASSWORD'):
            self._config_data.setdefault('database', {})['password'] = os.environ['MYSQL_PASSWORD']

        # 系统配置
        if os.environ.get('ENV'):
            self._config_data.setdefault('system', {})['env'] = os.environ['ENV']
        if os.environ.get('LOG_LEVEL'):
            self._config_data.setdefault('system', {})['log_level'] = os.environ['LOG_LEVEL']

    @property
    def locations(self) -> List[WeatherLocation]:
        """获取所有活跃气象站点"""
        return self._locations.copy()

    def get_location(self, name: str) -> Optional[WeatherLocation]:
        """按名称获取气象站点"""
        for location in self._locations:
            if location.name == name:
                return location
        return None

    def get_locations_by_state(self, state: str) -> List[WeatherLocation]:
        """按州获取气象站点"""
        return [loc for loc in self._locations if loc.state.upper() == state.upper()]

    def get_default_location(self) -> Optional[WeatherLocation]:
        """获取默认站点"""
        system_config = self._config_data.get('system', {})
        default_name = system_config.get('default_location', 'Boston')
        return self.get_location(default_name) or (self._locations[0] if self._locations else None)

    def get_active_locations(self) -> List[WeatherLocation]:
        """获取所有活跃站点"""
        return [loc for loc in self._locations if loc.active]

    @property
    def database_config(self) -> DatabaseConfig:
        """获取数据库配置"""
        db_config = self._config_data.get('database', {})
        return DatabaseConfig(**db_config)

    @property
    def openmeteo_config(self) -> OpenMeteoConfig:
        """获取OpenMeteo配置"""
        om_config = self._config_data.get('openmeteo', {})
        return OpenMeteoConfig(**om_config)

    @property
    def model_config(self) -> ModelConfig:
        """获取模型配置"""
        model_config = self._config_data.get('model', {})
        # 处理嵌套字段
        weights = model_config.get('ensemble_weights', {
            "lstm": 0.25, "bigru": 0.25, "tcn": 0.25, "transformer": 0.25
        })
        model_config['ensemble_weights'] = weights
        return ModelConfig(**model_config)

    @property
    def system_config(self) -> SystemConfig:
        """获取系统配置"""
        sys_config = self._config_data.get('system', {})
        # 过滤未知字段，避免 TypeError
        known_fields = {f.name for f in SystemConfig.__dataclass_fields__.values()}
        filtered = {k: v for k, v in sys_config.items() if k in known_fields}
        return SystemConfig(**filtered)

    def get_regions(self) -> Dict[str, Any]:
        """获取区域定义"""
        return self._config_data.get('regions', {})

    def get_region_locations(self, region_name: str) -> List[WeatherLocation]:
        """获取指定区域的站点列表"""
        regions = self.get_regions()
        if region_name not in regions:
            logger.warning(f"未知区域: {region_name}")
            return []

        region_locations = regions[region_name].get('locations', [])
        return [loc for loc in self._locations if loc.name in region_locations and loc.active]

    def reload(self) -> None:
        """重新加载配置文件"""
        logger.info("重新加载配置文件...")
        self._initialized = False
        self.__init__()

    def get_config_info(self) -> Dict[str, Any]:
        """获取配置信息(用于监控和调试)"""
        return {
            'config_dir': str(self.config_dir),
            'locations_count': len(self._locations),
            'active_locations_count': len(self.get_active_locations()),
            'regions_count': len(self.get_regions()),
            'config_version': self._config_data.get('version', 'unknown'),
            'last_updated': self._config_data.get('last_updated', 'unknown'),
        }


# 全局配置管理器实例
config_manager = ConfigManager()


def get_config() -> ConfigManager:
    """获取配置管理器实例"""
    return config_manager


# 为方便使用，导出常用属性
def get_locations() -> List[WeatherLocation]:
    """获取所有气象站点"""
    return config_manager.locations


def get_location(name: str) -> Optional[WeatherLocation]:
    """获取指定站点"""
    return config_manager.get_location(name)


def get_default_location() -> Optional[WeatherLocation]:
    """获取默认站点"""
    return config_manager.get_default_location()


__all__ = [
    'ConfigManager',
    'WeatherLocation',
    'DatabaseConfig',
    'OpenMeteoConfig',
    'ModelConfig',
    'SystemConfig',
    'config_manager',
    'get_config',
    'get_locations',
    'get_location',
    'get_default_location',
]