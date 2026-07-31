#!/usr/bin/env python3
"""
配置系统测试脚本

测试内容:
1. 配置文件加载
2. 气象站点解析
3. 环境变量覆盖
4. 默认值回退

使用方法:
python realtime_api/test_config.py
"""

import os
import sys
import logging
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    # 导入配置模块
    from realtime_api.config import ConfigManager, get_locations, get_default_location
    
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    print("提示: 请确保已安装依赖: pip install PyYAML")
    sys.exit(1)

def test_config_loading():
    """测试配置加载"""
        logger.info("\n" + "=" * 50)
        logger.info("🔍 开始配置系统测试")
        
        try:
            # 获取配置管理器
            config = ConfigManager()
            
            # 测试配置信息
            info = config.get_config_info()
            logger.info(f"✅ 配置管理器初始化成功")
            logger.info(f"  - 配置目录: {info['config_dir']}")
            logger.info(f"  - 总站点数: {info['locations_count']}")
            logger.info(f"  - 活跃站点: {info['active_locations_count']}")
            logger.info(f"  - 版本: {info['config_version']}")
            
            return config
            
        except Exception as e:
            logger.error(f"❌ 配置加载失败: {e}")
            return None
    
def test_locations(config):
    """测试气象站点"""
        logger.info("\n📍 测试气象站点...")
        
        try:
            # 获取所有站点
            locations = config.locations
            logger.info(f"✅ 加载 {len(locations)} 个气象站点: ")
            
            for i, loc in enumerate(locations, 1):
                logger.info(f"  {i:2d}. {loc.name:15} ({loc.lat:8.4f}, {loc.lon:8.4f})")
                if loc.state:
                    logger.info(f"      州: {loc.state}")
                if loc.description:
                    logger.info(f"      描述: {loc.description}")
                logger.info(f"      状态: {'活跃' if loc.active else '禁用'}")
                logger.info("")
            
            # 测试站点查询
            boston = config.get_location("Boston")
            if boston:
                logger.info(f"✅ 站点查询成功: Boston -> ({boston.lat}, {boston.lon})")
            else:
                logger.error("❌ 无法查询 Boston 站点")
            
            # 测试默认站点
            default = config.get_default_location()
            if default:
                logger.info(f"✅ 默认站点: {default.name}")
            else:
                logger.warning("⚠️ 未设置默认站点")
            
            # 按州过滤
            ma_locs = config.get_locations_by_state("MA")
            logger.info(f"✅ 按州过滤 MA: {len(ma_locs)} 个站点")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 站点测试失败: {e}")
            return False
    
def test_regions(config):
    """测试区域分组"""
        logger.info("\n🗺️  测试区域分组...")
        
        try:
            regions = config.get_regions()
            logger.info(f"✅ 加载 {len(regions)} 个区域定义:")
            
            for region_name, region_info in regions.items():
                logger.info(f"  - {region_name}: {region_info.get('name', '')}")
                locs = region_info.get('locations', [])
                logger.info(f"    站点数: {len(locs)}")
            
            # 测试获取区域站点
            if 'new_england' in regions:
                ne_locs = config.get_region_locations('new_england')
                logger.info(f"✅ 新英格兰地区获取到 {len(ne_locs)} 个站点")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 区域测试失败: {e}")
            return False
    
def test_database_config(config):
    """测试数据库配置"""
        logger.info("\n🗄️  测试数据库配置...")
        
        try:
            db_config = config.database_config
            logger.info(f"✅ 数据库配置加载成功:")
            logger.info(f"  - 主机: {db_config.host}")
            logger.info(f"  - 端口: {db_config.port}")
            logger.info(f"  - 数据库: {db_config.database}")
            logger.info(f"  - 用户: {db_config.user}")
            logger.info(f"  - 连接池: {db_config.pool_size}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 数据库配置测试失败: {e}")
            return False
    
def test_system_config(config):
    """测试系统配置"""
        logger.info("\n⚙️  测试系统配置...")
        
        try:
            sys_config = config.system_config
            logger.info(f"✅ 系统配置加载成功:")
            logger.info(f"  - 环境: {sys_config.env}")
            logger.info(f"  - 日志级别: {sys_config.log_level}")
            logger.info(f"  - 时区: {sys_config.timezone}")
            logger.info(f"  - 最大工作线程: {sys_config.max_workers}")
            logger.info(f"  - 监控启用: {sys_config.enable_monitoring}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 系统配置测试失败: {e}")
            return False
    
def test_model_config(config):
    """测试模型配置"""
        logger.info("\n🤖 测试模型配置...")
        
        try:
            model_config = config.model_config
            logger.info(f"✅ 模型配置加载成功:")
            logger.info(f"  - 模型目录: {model_config.model_dir}")
            logger.info(f"  - 设备: {model_config.device}")
            logger.info(f"  - 批处理: {model_config.batch_size}")
            logger.info(f"  - 缓存TTL: {model_config.cache_ttl}秒")
            
            weights = model_config.ensemble_weights
            logger.info(f"  - 集成权重: {weights}")
            total_weight = sum(weights.values())
            logger.info(f"  - 权重总和: {total_weight}")
            
            if abs(total_weight - 1.0) > 0.001:
                logger.warning(f"⚠️  集成权重总和不为1: {total_weight}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 模型配置测试失败: {e}")
            return False
    
def test_env_overrides():
    """测试环境变量覆盖"""
        logger.info("\n🌐 测试环境变量覆盖...")
        
        try:
            # 设置测试环境变量
            os.environ['MYSQL_HOST'] = 'test-host'
            os.environ['ENV'] = 'test'
            
            # 重新加载配置
            config = ConfigManager()
            config.reload()
            
            # 检查覆盖效果
            db_config = config.database_config
            if db_config.host == 'test-host':
                logger.info(f"✅ 环境变量覆盖成功: host={db_config.host}")
            else:
                logger.warning(f"⚠️ 环境变量未生效: host={db_config.host}")
            
            # 清理环境变量
            del os.environ['MYSQL_HOST']
            del os.environ['ENV']
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 环境变量测试失败: {e}")
            return False

def test_config_validation():
    """配置验证"""
        logger.info("\n🔍 配置验证...")
        
        try:
            config = ConfigManager()
            locations = config.get_active_locations()
            
            # 检查活跃站点数量
            min_locations = 3
            if len(locations) >= min_locations:
                logger.info(f"✅ 活跃站点数量充足: {len(locations)} >= {min_locations}")
            else:
                logger.warning(f"⚠️ 活跃站点不足: {len(locations)} < {min_locations}")
            
            # 验证地理范围
            valid_count = 0
            for loc in locations:
                if -90 <= loc.lat <= 90 and -180 <= loc.lon <= 180:
                    valid_count += 1
                else:
                    logger.warning(f"⚠️ 无效的经纬度: {loc.name} ({loc.lat}, {loc.lon})")
            
            logger.info(f"✅ 坐标验证: {valid_count}/{len(locations)} 有效")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 配置验证失败: {e}")
            return False
    
    def main():
    """主测试函数"""
    logger.info("🧪 智能电网负荷预测系统 - 配置系统测试套件")
        logger.info("时间: %s", __import__('datetime').datetime.now())
        
        results = {
            'config_loading': False,
            'locations': False,
            'regions': False,
            'database': False,
            'system': False,
            'model': False,
            'env_overrides': False,
            'validation': False,
        }
        
        # 1. 配置加载
        config = test_config_loading()
        results['config_loading'] = bool(config)
        
        if config:
            # 2. 测试各配置项
            results['locations'] = test_locations(config)
            results['regions'] = test_regions(config)
            results['database'] = test_database_config(config)
            results['system'] = test_system_config(config)
            results['model'] = test_model_config(config)
            results['validation'] = test_config_validation()
        
        # 3. 环境变量测试
        results['env_overrides'] = test_env_overrides()
        
        # 4. 测试总结
        logger.info("\n" + "=" * 60)
        logger.info("📋 测试结果汇总:")
        
        passed = 0
        for test_name, result in results.items():
            status = "✅ 通过" if result else "❌ 失败"
            logger.info(f"  - {test_name:15} {status}")
            if result:
                passed += 1
        
        logger.info("\n" + "=" * 60)
        logger.info(f"🎯 覆盖率: {passed}/{len(results)} ({100*passed/len(results):.1f}%)")
        
        if passed == len(results):
            logger.info("🎉 所有测试通过!")
            return 0
        else:
            logger.warning("⚠️  有测试未通过，请检查配置问题")
            return 1
    
if __name__ == "__main__":
    exit(main())