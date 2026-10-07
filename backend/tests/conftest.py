# -*- coding: utf-8 -*-
"""
pytest 全局配置：路径与环境

说明：
- 默认测试不依赖真实 MySQL / 外部 API，数据库和网络操作通过 mock 验证。
- 模型契约测试会加载已有权重并进行小规模推理，不训练或改写模型。
- test_api_e2e.py 使用真实服务且会写入数据库，必须显式启用并使用隔离库。
"""
import os
import sys
import logging
from pathlib import Path

# 项目后端根目录加入 sys.path（tests/ 的上一级）
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 加载 .env（项目根目录），保证 MYSQL_PASSWORD / AUTH_JWT_SECRET_KEY 等一致
try:
    from dotenv import load_dotenv
    _ROOT = BACKEND_DIR.parent
    load_dotenv(_ROOT / ".env")
except Exception:
    pass

# 测试期间静音业务日志，避免噪音
logging.disable(logging.CRITICAL)
