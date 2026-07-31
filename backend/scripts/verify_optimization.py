import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from realtime_api.config_manager import get_config
    config = get_config()
    print(f"Config loaded: {config.get('system.name')}")
    
    from realtime_api.error_handling import ResourceNotFoundError
    print("Error handling module loaded")
    
    from realtime_api.health_check import HealthCheckService
    health = HealthCheckService()
    print("Health check module loaded") 
    
    from realtime_api.structured_logger import get_logger
    logger = get_logger("test")
    print("Structured logging module loaded")
    
    print("All optimization modules working correctly!")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()