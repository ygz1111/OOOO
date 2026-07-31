#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 测试套件初始化

本模块为整个测试套件提供:
  - 测试环境配置
  - 通用测试工具
  - 测试数据工厂
  - 测试执行钩子

测试类型覆盖:
  1. 单元测试 (Unit Tests) - 测试单个组件功能
  2. 集成测试 (Integration Tests) - 测试组件间交互 
  3. 端到端测试 (E2E Tests) - 测试完整工作流
  4. 性能测试 (Performance Tests) - 测试系统性能指标
  5. 异常测试 (Exception Tests) - 测试错误处理和恢复能力

作者: 毕业设计项目
版本: 1.0.0
"""

import sys
import os
from pathlib import Path

# 将项目根目录添加到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def setup_test_environment():
    """设置测试环境"""
    # 设置测试模式环境变量
    os.environ['TEST_MODE'] = 'true'
    os.environ['API_TEST_MODE'] = 'true'
    
    # 禁用外部API调用
    os.environ['DISABLE_EXTERNAL_APIS'] = 'true'
    
    print("✅ 测试环境已配置")

# 自动执行环境设置
setup_test_environment()

__version__ = "1.0.0"
__author__ = "毕业设计项目"