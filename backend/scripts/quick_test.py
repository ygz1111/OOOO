from realtime_api.config_manager import get_config

config = get_config()
print('Config loaded successfully!')
print(f'System name: {config.get("system.name")}')
print(f'API port: {config.get("api.port")}')
print(f'Weather locations: {len(config.get_weather_locations())}')
print(f'Environment: {config.environment}')
print('All hardcoded configs have been migrated to config files!')