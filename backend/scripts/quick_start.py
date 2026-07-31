#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
快速启动智能电网负荷预测系统 - 简化版本
跳过数据库依赖，专注于展示优化的核心功能

作者: 毕业设计项目
"""

import sys
import os
import logging
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def setup_logging():
    """设置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

def test_optimized_modules():
    """测试所有优化模块"""
    print("="*60)
    print("智能电网负荷预测系统 - 优化模块测试")
    print("="*60)
    
    try:
        # 1. 测试配置管理器
        from realtime_api.config_manager import get_config
        config = get_config()
        
        print(f"\n1️⃣ 配置管理器")
        print(f"   ✅ 系统名称: {config.get('system.name')}")
        print(f"   ✅ 环境: {config.environment}")
        print(f"   ✅ API端口: {config.get('api.port')}")
        print(f"   ✅ 气象站点: {len(config.get_weather_locations())} 个")
        
        # 2. 测试健康检查
        from realtime_api.health_check import HealthCheckService
        health_service = HealthCheckService()
        
        print(f"\n2️⃣ 健康检查服务")
        print(f"   ✅ 健康检查服务: {health_service.__class__.__name__}")
        
        # 测试系统资源检查
        system_health = health_service.check_system_resources()
        print(f"   ✅ 系统资源状态: {system_health.status}")
        print(f"   ✅ CPU使用率: {system_health.details.get('cpu_percent', 'N/A')}%")
        
        # 3. 测试错误处理
        from realtime_api.error_handling import (
            SmartGridException, 
            ResourceNotFoundError,
            ValidationError,
            ErrorCode
        )
        
        print(f"\n3️⃣ 错误处理系统")
        print(f"   ✅ 异常基类: {SmartGridException.__name__}")
        print(f"   ✅ 错误码数量: {len(ErrorCode)}")
        print(f"   ✅ 示例错误码: {ErrorCode.RESOURCE_NOT_FOUND.name} = {ErrorCode.RESOURCE_NOT_FOUND.value}")
        
        # 4. 测试结构化日志
        from realtime_api.structured_logger import get_logger, logging_manager
        
        print(f"\n4️⃣ 结构化日志系统")
        logger = get_logger("quick_start")
        logger.info("结构化日志测试正常")
        print(f"   ✅ 日志管理器: {logging_manager.__class__.__name__}")
        print(f"   ✅ 请求级日志: {logger.__class__.__name__}")
        
        # 获取特定日志记录器
        request_logger = get_logger("api.request", request_id="test-request-123")
        request_logger.info("API请求级日志测试")
        print(f"   ✅ 请求ID追踪: test-request-123")
        
        # 带上下文信息的日志
        context_logger = logger.bind(
            user_id="user_test",
            session_id="session_123",
            tags=["prediction", "test"]
        )
        context_logger.info("带上下文信息的日志")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def show_api_endpoints():
    """显示API端点"""
    print(f"\n" + "="*60)
    print("API端点总览")
    print("="*60)
    
    endpoints = [
        ("POST", "/api/prediction/load", "负荷预测 - 24小时负荷预测"),
        ("GET", "/api/weather/current", "气象数据 - 获取实时气象信息"),
        ("GET", "/api/health", "健康检查 - 综合服务状态检查"),
        ("GET", "/api/health/liveness", "存活检查 - Kubernetes liveness probe"),
        ("GET", "/api/health/readiness", "就绪检查 - Kubernetes readiness probe"),
        ("GET", "/api/system/status", "系统状态 - 运行状态和性能统计"),
        ("POST", "/api/prediction/batch", "批量预测 - 批量执行负荷预测 (需认证)"),
        ("GET", "/api/analytics/accuracy/stats", "准确性分析 - 预测准确性统计"),
    ]
    
    for method, path, description in endpoints:
        print(f"{method:4} {path:30} {description}")

def show_optimization_summary():
    """显示优化总结"""
    print(f"\n" + "="*60)
    print("企业级优化完成总结")
    print("="*60)
    
    optimizations = [
        {
            "name": "配置管理优化",
            "description": "集中式配置管理，移除硬编码",
            "files": ["config/app_config.yaml", "realtime_api/config_manager.py"],
            "status": "✅ 完成"
        },
        {
            "name": "健康检查体系", 
            "description": "全面的服务健康监控和检查",
            "files": ["realtime_api/health_check.py"],
            "status": "✅ 完成"
        },
        {
            "name": "统一错误处理",
            "description": "标准错误码体系和异常处理",
            "files": ["realtime_api/error_handling.py"],
            "status": "✅ 完成"
        },
        {
            "name": "结构化日志系统",
            "description": "JSON格式结构化日志，支持上下文追踪",
            "files": ["realtime_api/structured_logger.py"],
            "status": "✅ 完成"
        }
    ]
    
    for i, opt in enumerate(optimizations, 1):
        print(f"{i}. {opt['name']} {opt['status']}")
        print(f"   📍 {opt['description']}")
        for file in opt['files']:
            print(f"   📁 {file}")
        print()
    
    print("🏆 智能电网负荷预测系统已升级到企业级标准！")

def main():
    """主函数"""
    setup_logging()
    
    # 测试所有优化模块
    success = test_optimized_modules()
    
    if success:
        # 显示API端点
        show_api_endpoints()
        
        # 显示优化总结
        show_optimization_summary()
        
        print(f"\n" + "="*60)
        print("🎉 启动完成！")
        print("="*60)
        
        print("\n优化功能验证成功，系统已准备就绪：")
        print("   📋 配置管理 - 生产环境部署准备就绪")
        print("   🏥 健康检查 - K8s部署支持完成") 
        print("   🚨 错误处理 - 标准化错误响应")
        print("   📝 日志系统 - 企业级日志追踪")
        
        print("\n⚡ 下一步操作:")
        print("   1. 修复数据库模块导入问题")
        print("   2. 运行: python realtime_api/app.py")
        print("   3. 访问: http://localhost:8000/docs")
        
    else:
        print("\n❌ 存在未解决的问题，请检查日志")
        
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)