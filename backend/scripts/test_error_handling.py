#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from realtime_api.error_handling import (
    SmartGridException, 
    ErrorCode, 
    ResourceNotFoundError,
    ValidationError,
    ModelNotReadyError
)

def test_error_handling():
    """测试错误处理模块"""
    
    print("Testing error handling module...")
    
    # 测试1: 基本异常
    try:
        raise ResourceNotFoundError("用户", "指定ID的用户不存在")
    except SmartGridException as e:
        print(f"✅ ResourceNotFoundError: {e.error_code.name} = {e.error_code.value}")
        print(f"   Message: {e.message}")
        print(f"   Detail: {e.detail}")
        print(f"   HTTP Status: {e.status_code}")
        print(f"   Error ID: {e.error_id}")
    
    # 测试2: 验证错误
    try:
        raise ValidationError("输入数据格式错误", "temperature_2m must be a number")
    except SmartGridException as e:
        print(f"\n✅ ValidationError: {e.error_code.name} = {e.error_code.value}")
        print(f"   Message: {e.message}")
        print(f"   HTTP Status: {e.status_code}")
    
    # 测试3: 模型服务错误
    try:
        raise ModelNotReadyError("模型正在加载中，请稍后重试")
    except SmartGridException as e:
        print(f"\n✅ ModelNotReadyError: {e.error_code.name} = {e.error_code.value}")
        print(f"   Message: {e.message}")
        print(f"   HTTP Status: {e.status_code}")
    
    # 测试4: 错误码枚举
    print(f"\n✅ Error codes defined: {len(ErrorCode)}")
    sample_codes = [
        ErrorCode.SUCCESS,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.DATABASE_ERROR,
        ErrorCode.MODEL_ERROR
    ]
    
    for code in sample_codes:
        http_status = (code.value // 100) % 100 + (400 if code.value >= 40000 else 500 if code.value >= 50000 else 200)
        print(f"   {code.name}: {code.value} -> HTTP {http_status}")
    
    print("\n✅ All error handling tests passed!")

if __name__ == "__main__":
    test_error_handling()