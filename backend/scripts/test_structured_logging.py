#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from realtime_api.structured_logger import get_logger, logging_manager

# 测试结构化日志
def test_structured_logging():
    print("测试结构化日志...")
    
    logger = get_logger("test.module")
    
    # 基础日志测试
    logger.info("这是信息日志")
    logger.warning("这是警告日志")
    logger.error("这是错误日志")
    
    # 带上下文的日志测试
    context_logger = logger.bind(user_id="user123", session_id="session456")
    context_logger.info("带用户信息的日志")
    
    # 带标签的日志测试
    tagged_logger = logger.add_tag("prediction").add_tag("async")
    tagged_logger.info("带标签的预测日志")
    
    print("结构化日志测试完成!")

if __name__ == "__main__":
    test_structured_logging()