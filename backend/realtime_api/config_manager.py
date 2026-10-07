#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 配置管理器

集中管理所有配置，支持环境变量覆盖和配置文件读取

作者: 毕业设计项目
"""

import os
import yaml
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path

from dotenv import load_dotenv


# 配置模块也可能被维护脚本、测试工具或某个子模块直接导入，不能只依赖
# FastAPI 入口负责加载环境变量。这里使用确定的项目根目录，不依赖当前工作
# 目录；默认 override=False，仍尊重由部署环境显式注入的变量。
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=False)


class ConfigManager:
    """配置管理器 - 单例模式"""
    
    _instance = None
    _config = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._config:
            self._load_config()
            self._load_locations()

    def _load_locations(self):
        """从 locations.yaml 加载气象站点（与 app_config.yaml 同目录）

        站点数据统一维护在 locations.yaml；app_config.yaml 仅含非站点配置。
        """
        self._locations = []
        try:
            _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            loc_file = os.path.join(_backend_dir, 'config', 'locations.yaml')
            with open(loc_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            self._locations = [
                loc for loc in data.get('locations', [])
                if loc.get('active', True)
            ]
            logging.info(f"✅ 气象站点加载成功: {len(self._locations)} 个站点")
        except Exception as e:
            logging.warning(f"locations.yaml 加载失败: {e}")
    
    def _load_config(self):
        """加载配置文件"""
        try:
            # 查找配置文件
            _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_paths = [
                os.path.join(_backend_dir, 'config', 'app_config.yaml'),
                '/etc/smartgrid/config.yaml',
                'config.yaml'
            ]
            
            config_file = None
            for path in config_paths:
                if os.path.exists(path):
                    config_file = path
                    break
            
            if not config_file:
                raise FileNotFoundError(f"配置文件未找到，尝试路径: {config_paths}")
            
            # 读取YAML配置文件
            with open(config_file, 'r', encoding='utf-8') as f:
                file_config = yaml.safe_load(f)
            
            if not file_config:
                raise ValueError("配置文件为空或格式错误")
            
            # 应用环境变量覆盖
            self._config = self._apply_env_overrides(file_config)
            
            logging.info(f"✅ 配置加载成功: {config_file}")
            
        except Exception as e:
            logging.error(f"❌ 配置加载失败: {e}")
            # 使用默认配置
            self._config = self._get_default_config()
            logging.warning("使用默认配置")
    
    def _apply_env_overrides(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """应用环境变量覆盖"""
        
        # 系统环境覆盖
        if env_env := os.getenv('SYSTEM_ENVIRONMENT'):
            config['system']['environment'] = env_env
        
        # API配置覆盖
        if api_port := os.getenv('API_PORT'):
            config['api']['port'] = int(api_port)
        
        if api_debug := os.getenv('API_DEBUG'):
            config['api']['debug'] = api_debug.lower() == 'true'
        
        # 数据库配置覆盖。统一使用 database.py、.env.example 和 Compose 中的
        # MYSQL_* 命名；同时保留旧 DATABASE_* 变量作为兼容别名。
        mysql_config = config.setdefault('database', {}).setdefault('mysql', {})
        database_overrides = {
            'host': os.getenv('MYSQL_HOST') or os.getenv('DATABASE_HOST'),
            'port': os.getenv('MYSQL_PORT') or os.getenv('DATABASE_PORT'),
            'database': os.getenv('MYSQL_DATABASE') or os.getenv('DATABASE_NAME'),
            'user': os.getenv('MYSQL_USER') or os.getenv('DATABASE_USER'),
            'password': os.getenv('MYSQL_PASSWORD') or os.getenv('DATABASE_PASSWORD'),
            'pool_size': os.getenv('MYSQL_POOL_SIZE') or os.getenv('DATABASE_POOL_SIZE'),
        }
        for key, value in database_overrides.items():
            if value is not None and value != '':
                mysql_config[key] = int(value) if key in {'port', 'pool_size'} else value
        
        # Redis配置覆盖
        if redis_host := os.getenv('REDIS_HOST'):
            config['cache']['redis']['host'] = redis_host
        if redis_port := os.getenv('REDIS_PORT'):
            config['cache']['redis']['port'] = int(redis_port)
        if redis_db := os.getenv('REDIS_DB'):
            config['cache']['redis']['db'] = int(redis_db)
        if redis_password := os.getenv('REDIS_PASSWORD'):
            config['cache']['redis']['password'] = redis_password
        if redis_protocol := os.getenv('REDIS_PROTOCOL'):
            config['cache']['redis']['protocol'] = int(redis_protocol)
        
        # 认证配置覆盖 (注意: 生产环境必须使用强密钥)
        if jwt_secret := os.getenv('AUTH_JWT_SECRET_KEY'):
            config['auth']['jwt']['secret_key'] = jwt_secret
        
        # 日志级别覆盖
        if log_level := os.getenv('LOGGING_LEVEL'):
            config['logging']['level'] = log_level
        
        return config
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'system': {
                'name': '智能电网负荷预测系统',
                'version': '1.1.0',
                'environment': 'development'
            },
            'api': {
                'host': '0.0.0.0',
                'port': 8000,
                'debug': False
            },
            'weather': {
                'locations': [
                    {'name': 'Boston', 'lat': 42.3601, 'lon': -71.0589}
                ]
            }
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持点分隔符）"""
        keys = key.split('.')
        value = self._config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_system_config(self) -> Dict[str, Any]:
        """获取系统配置"""
        return self.get('system', {})
    
    def get_api_config(self) -> Dict[str, Any]:
        """获取API配置"""
        return self.get('api', {})
    
    def get_weather_locations(self) -> List[Dict[str, Any]]:
        """获取气象站点配置（来自 locations.yaml）"""
        return self._locations
    
    def get_openmeteo_config(self) -> Dict[str, Any]:
        """获取OpenMeteo配置"""
        return self.get('weather.openmeteo', {})
    
    def get_model_config(self) -> Dict[str, Any]:
        """获取模型配置"""
        return self.get('models', {})
    
    def get_ensemble_weights(self) -> Dict[str, float]:
        """获取集成模型权重"""
        return self.get('models.ensemble_weights', {})
    
    def get_database_config(self) -> Dict[str, Any]:
        """获取数据库配置"""
        return self.get('database.mysql', {})
    
    def get_cache_config(self) -> Dict[str, Any]:
        """获取缓存配置"""
        return self.get('cache.redis', {})
    
    def get_auth_config(self) -> Dict[str, Any]:
        """获取认证配置"""
        return self.get('auth.jwt', {})
    
    def get_monitoring_config(self) -> Dict[str, Any]:
        """获取监控配置"""
        return self.get('monitoring', {})
    
    def get_logging_config(self) -> Dict[str, Any]:
        """获取日志配置"""
        return self.get('logging', {})
    
    def get_backup_config(self) -> Dict[str, Any]:
        """获取备份配置"""
        return self.get('backup', {})
    
    def get_solar_config(self) -> Dict[str, Any]:
        """获取光伏发电配置"""
        return self.get('solar', {})
    
    @property
    def environment(self) -> str:
        """获取当前环境"""
        return self.get('system.environment', 'development')
    
    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.environment == 'production'
    
    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.environment == 'development'


# 全局配置实例
config_manager = ConfigManager()


def get_config() -> ConfigManager:
    """获取配置管理器实例"""
    return config_manager


# ============================================================================
# 便捷函数
# ============================================================================

def get_weather_locations() -> List[Dict[str, Any]]:
    """获取气象站点列表"""
    return config_manager.get_weather_locations()


def get_api_port() -> int:
    """获取API端口"""
    return config_manager.get('api.port', 8000)


def get_database_url() -> str:
    """构建数据库URL"""
    db_config = config_manager.get_database_config()
    return f"mysql+aiomysql://{db_config.get('user', 'root')}:{db_config.get('password', '')}@{db_config.get('host', 'localhost')}:{db_config.get('port', 3306)}/{db_config.get('database', 'smart_grid_db')}"


def get_jwt_secret() -> str:
    """获取JWT密钥（优先 AUTH_JWT_SECRET_KEY 环境变量）"""
    # 动态读取环境变量，避免配置单例在 .env 加载前被其他模块间接导入时缓存
    # 旧值。正常启动时 app.py 会先加载 .env；动态读取同时让脚本、测试和
    # WSGI/ASGI 工具以不同导入顺序启动时仍使用同一把密钥。
    secret = os.getenv('AUTH_JWT_SECRET_KEY') or config_manager.get(
        'auth.jwt.secret_key', None
    )
    if not secret or secret in ('your-secret-key', 'default-secret-key',
                                'your-secret-key-change-in-production'):
        logging.warning(
            "JWT 密钥未通过 AUTH_JWT_SECRET_KEY 环境变量配置，正在使用不安全的默认值。"
            "生产环境必须设置强随机密钥。"
        )
        return 'default-secret-key'
    return secret


def is_production() -> bool:
    """检查是否为生产环境"""
    return config_manager.is_production


def get_logging_level() -> str:
    """获取日志级别"""
    return config_manager.get('logging.level', 'INFO')
