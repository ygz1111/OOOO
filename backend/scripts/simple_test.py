from realtime_api.error_handling import ResourceNotFoundError, ValidationError

# 测试异常创建
try:
    raise ResourceNotFoundError("用户", "指定ID的用户不存在")
except Exception as e:
    print(f"Error code: {e.error_code.name} = {e.error_code.value}")
    print(f"Message: {e.message}")
    print(f"HTTP Status: {e.status_code}")
    print("Error handling module working correctly!")