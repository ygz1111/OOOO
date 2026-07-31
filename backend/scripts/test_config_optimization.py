#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置优化功能测试

验证硬编码配置到配置文件的迁移是否成功

作者: 毕业设计项目
"""

import os
import sys
import yaml
from pathlib import Path

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def test_config_files():
    """测试配置文件存在性和格式"""
    print("🔍 测试1: 配置文件存在性和格式")
    
    config_file = PROJECT_ROOT / "config" / "app_config.yaml"
    
    if not config_file.exists():
        print("❌ 配置文件不存在")
        return False
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 检查必需的配置节
        required_sections = [
            'system', 'api', 'weather', 'models', 
            'database', 'cache', 'auth', 'monitoring'
        ]
        
        missing_sections = []
        for section in required_sections:
            if section not in config:
                missing_sections.append(section)
        
        if missing_sections:
            print(f"❌ 配置文件中缺少必需的配置节: {missing_sections}")
            return False
        
        print(f"✅ 配置文件验证通过")
        print(f"   包含 {len(config)} 个配置节")
        print(f"   气象站点数量: {len(config['weather']['locations'])}")
        print(f"   模型权重: {config['models']['ensemble_weights']}")
        
        return True
        
    except yaml.YAMLError as e:
        print(f"❌ 配置文件格式错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 配置文件读取错误: {e}")
        return False

def test_config_manager():
    """测试配置管理器功能"""
    print("\n🔍 测试2: 配置管理器功能")
    
    try:
        from realtime_api.config_manager import ConfigManager, get_config
        
        # 测试单例模式
        config1 = ConfigManager()
        config2 = get_config()
        
        if config1 is not config2:
            print("❌ 配置管理器单例模式失败")
            return False
        
        # 测试基本配置获取
        system_config = config1.get_system_config()
        if not system_config:
            print("❌ 无法获取系统配置")
            return False
        
        # 测试特定配置
        api_port = config1.get('api.port')
        if api_port != 8000:
            print(f"❌ API端口配置错误: {api_port}")
            return False
        
        # 测试气象站点配置
        locations = config1.get_weather_locations()
        if len(locations) < 6:
            print(f"❌ 气象站点配置不足: {len(locations)}")
            return False
        
        # 测试环境判断
        env = config1.environment
        print(f"✅ 配置管理器验证通过")
        print(f"   当前环境: {env}")
        print(f"   是否为生产环境: {config1.is_production}")
        print(f"   系统名称: {config1.get('system.name')}")
        print(f"   API端口: {api_port}")
        print(f"   气象站点: {len(locations)} 个")
        
        return True
        
    except Exception as e:
        print(f"❌ 配置管理器测试失败: {e}")
        return False

def test_app_config_integration():
    """测试应用配置集成"""
    print("\n🔍 测试3: 应用配置集成")
    
    app_file = PROJECT_ROOT / "realtime_api" / "app.py"
    
    if not app_file.exists():
        print("❌ app.py 文件不存在")
        return False
    
    try:
        with open(app_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查配置管理器导入
        if 'from realtime_api.config_manager import get_config' not in content:
            print("❌ app.py 未导入配置管理器")
            return False
        
        # 检查配置使用
        config_usages = [
            'config.get_weather_locations()',
            'config.get_logging_config()',
            'config.get_api_config()',
            'api_config.get('
        ]
        
        missing_usages = []
        for usage in config_usages:
            if usage not in content:
                missing_usages.append(usage)
        
        if missing_usages:
            print(f"❌ app.py 中缺少配置使用: {missing_usages}")
            return False
        
        print(f"✅ 应用配置集成验证通过")
        print(f"   检测到配置管理器导入")
        print(f"   气象站点配置集成")
        print(f"   日志配置集成") 
        print(f"   API配置集成")
        
        return True
        
    except Exception as e:
        print(f"❌ 应用配置集成测试失败: {e}")
        return False

def test_hardcoded_removal():
    """测试硬编码配置的移除"""
    print("\n🔍 测试4: 硬编码配置移除")
    
    app_file = PROJECT_ROOT / "realtime_api" / "app.py"
    
    if not app_file.exists():
        print("❌ app.py 文件不存在")
        return False
    
    try:
        with open(app_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查旧硬编码模式是否已移除
        hardcoded_patterns = [
            'past_days=7, forecast_days=1, rate_limit_interval=0.3',
            'SolarEstimator()  # 无参数',
            'port=8000, reload=False'
        ]
        
        found_hardcoded = []
        for pattern in hardcoded_patterns:
            if pattern in content:
                found_hardcoded.append(pattern)
        
        if found_hardcoded:
            print(f"❌ 仍存在硬编码配置: {found_hardcoded}")
            return False
        
        print(f"✅ 硬编码配置移除验证通过")
        print(f"   气象数据参数已移至配置")
        print(f"   光伏参数已移至配置")
        print(f"   API端口已移至配置")
        
        return True
        
    except Exception as e:
        print(f"❌ 硬编码移除测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("="*60)
    print("智能电网负荷预测系统 - 配置优化测试")
    print("="*60)
    
    test_results = []
    
    # 执行各项测试
    test_results.append(test_config_files())
    test_results.append(test_config_manager())
    test_results.append(test_app_config_integration())
    test_results.append(test_hardcoded_removal())
    
    # 生成报告
    passed_tests = sum(test_results)
    total_tests = len(test_results)
    
    print(f"\n" + "="*60)
    print(f"测试结果总结")
    print(f"="*60)
    
    if passed_tests == total_tests:
        print(f"✨ 所有测试通过 ({passed_tests}/{total_tests})")
        print(f"✅ 配置优化成功完成！")
        print(f"\n优化内容:")
        print(f"   📋 创建了集中式配置文件 (config/app_config.yaml)")
        print(f"   🔧 实现了配置管理器 (realtime_api/config_manager.py)")
        print(f"   🎯 移除了硬编码的气象站点配置")
        print(f"   🛠️  移除了硬编码的API参数")
        print(f"   📝 提供了环境变量覆盖支持")
        print(f"   📄 创建了配置示例文件 (.env.example)")
        
        print(f"\n下一步建议:")
        print(f"   1. 根据实际环境修改 config/app_config.yaml")
        print(f"   2. 创建 .env 文件配置敏感信息")
        print(f"   3. 验证应用启动时的配置加载")
        
    else:
        print(f"⚠️  部分测试失败 ({passed_tests}/{total_tests})")
        print(f"❌ 需要修复失败的配置")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)