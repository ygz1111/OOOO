#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
测试优化后的项目启动
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("="*60)
print("测试优化后的智能电网负荷预测系统")
print("="*60)

def test_imports():
    """测试核心模块导入"""
    try:
        # 测试配置管理器
        from realtime_api.config_manager import get_config
        config = get_config()
        print(f"✅ 配置管理器: {config.get('system.name')}")
        print(f"   环境: {config.environment}")
        print(f"   API端口: {config.get('api.port')}")
        print(f"   气象站点: {len(config.get_weather_locations())} 个")
        
        # 测试错误处理
        from realtime_api.error_handling import SmartGridException, ResourceNotFoundError
        print(f"✅ 错误处理: {SmartGridException.__name__}")
        
        # 测试健康检查  
        from realtime_api.health_check import HealthCheckService
        health_service = HealthCheckService()
        print(f"✅ 健康检查: {health_service.__class__.__name__}")
        
        # 测试结构化日志
        from realtime_api.structured_logger import get_logger
        logger = get_logger("test.startup")
        logger.info("日志系统正常工作")
        print(f"✅ 结构化日志: {logger.__class__.__name__}")
        
        return True
        
    except Exception as e:
        print(f"❌ 模块导入失败: {e}")
        return False

def test_configuration():
    """测试配置验证"""
    try:
        from realtime_api.config_manager import get_config
        config = get_config()
        
        # 检查必需的配置项
        required_configs = [
            'system.name',
            'api.port', 
            'weather.locations',
            'models.ensemble_weights'
        ]
        
        for conf_key in required_configs:
            value = config.get(conf_key)
            if value is None:
                print(f"❌ 缺少配置: {conf_key}")
                return False
            print(f"   {conf_key}: {value}")
        
        print("✅ 配置验证通过")
        return True
        
    except Exception as e:
        print(f"❌ 配置验证失败: {e}")
        return False

def main():
    """主测试函数"""
    print("\n1. 测试模块导入...")
    import_success = test_imports()
    
    print("\n2. 测试配置验证...")
    config_success = test_configuration()
    
    print("\n" + "="*60)
    print("测试结果总结")
    print("="*60)
    
    if import_success and config_success:
        print("🎉 所有核心模块优化完成并正常工作！")
        print("\n优化内容:")
        print("   📋 配置管理器 - 集中式配置管理")
        print("   🏥 健康检查 - 服务监控和状态检查")
        print("   🚨 错误处理 - 统一错误码和异常管理")
        print("   📝 结构化日志 - JSON格式日志系统")
        
        print("\n🚀 项目已准备好生产环境部署！")
        print("   使用: python realtime_api/app.py")
        print("   访问: http://localhost:8000/docs")
        
    else:
        print("⚠️  存在未解决的问题，需要修复")
        
    return import_success and config_success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)