# 配置管理指南

## 概述

本指南介绍智能电网负荷预测系统的配置管理机制。系统采用分层配置设计，支持环境变量、YAML文件、默认值三级配置来源。

## 配置架构

### 1. 配置层级
```
┌─────────────────┐
│ 环境变量        │ 优先级最高
├─────────────────┤
│ YAML 配置文件   │ 优先级中等
├─────────────────┤
│ 硬编码默认值    │ 优先级最低
└─────────────────┘
```

### 2. 配置源详解

#### 环境变量
优先级最高的环境变量会覆盖所有配置:

```bash
# 数据库配置
export MYSQL_HOST=192.168.1.100
export MYSQL_PORT=3306
export MYSQL_DATABASE=OOOO
export MYSQL_USER=root
export MYSQL_PASSWORD=secure_password

# 系统配置
export ENV=production
export LOG_LEVEL=WARNING
```

**支持的变量列表**:

| 变量名 | 说明 | 默认值 |
|--------|-----|--------|
| `MYSQL_HOST` | 数据库主机 | `localhost` |
| `MYSQL_PORT` | 数据库端口 | `3306` |
| `MYSQL_DATABASE` | 数据库名 | `OOOO` |
| `MYSQL_USER` | 用户 | `root` |
| `MYSQL_PASSWORD` | 密码 | `315131` |
| `ENV` | 环境 | `production` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `CONFIG_DIR` | 配置目录 | `config` |

#### YAML 配置文件

主配置文件: `config/application.yaml`

气象站点配置: `config/locations.yaml`

**配置示例**:

```yaml
# config/application.yaml
system:
  env: production
  log_level: INFO
  max_workers: 8

database:
  host: localhost
  port: 3306
  database: OOOO
  user: root
  password: 315131
  pool_size: 10
```

#### 默认值

当配置缺失时使用的内置默认值。

## 配置类型详解

### 1. 气象站点配置 (locations.yaml)

```yaml
locations:
  - name: "Boston"
    lat: 42.3601
    lon: -71.0589
    state: "MA"
    elevation: 43
    description: "波士顿市中心气象站"
    active: true  # 是否启用该站点

system:
  default_location: "Boston"     # 默认站点
  min_active_locations: 3        # 最少活跃站点数
```

**属性说明**:

- **name**: 站点名称（必须唯一）
- **lat**: 纬度 (-90 到 90)
- **lon**: 经度 (-180 到 180)
- **state**: 州缩写（可选）
- **elevation**: 海拔（米，可选）
- **description**: 描述（可选）
- **active**: 是否启用（true/false）

### 2. 区域分组

```yaml
regions:
  new_england:
    name: "新英格兰地区"
    description: "美国新英格兰地区6州"
    locations: ["Boston", "Hartford", "Portland", "Manchester", "Providence", "Burlington"]
  
  massachusetts:
    name: "马萨诸塞州"
    locations: ["Boston"]
```

**用途**:
- 按区域获取站点列表
- 批量操作气象站点
- 场景化预测（如单州 vs 多州）

### 3. 数据库配置

```yaml
database:
  host: localhost
  port: 3306
  database: OOOO
  user: root
  password: 315131
  pool_size: 10
  pool_reset_session: true
```

### 4. 模型配置

```yaml
model:
  model_dir: models                 # 模型文件目录
  device: cuda                      # 运行设备: cuda/cpu
  batch_size: 16                    # 批处理大小
  cache_ttl: 300                    # 缓存TTL(秒)
  
  # 集成学习权重
  ensemble_weights:
    lstm: 0.25
    bigru: 0.25
    tcn: 0.25
    transformer: 0.25
```

### 5. API 配置

```yaml
openmeteo:
  api_url: https://api.open-meteo.com/v1/forecast
  past_days: 7
  forecast_days: 1
  timezone: America/New_York
  rate_limit_interval: 0.5
  request_timeout: 10.0
  max_retries: 3
```

## 配置使用示例

### 代码中获取配置

```python
from realtime_api.config import get_config

# 获取配置管理器
config = get_config()

# 获取所有气象站点
locations = config.locations

# 获取指定站点
boston = config.get_location("Boston")

# 按州过滤
ma_locations = config.get_locations_by_state("MA")

# 获取数据库配置
db_config = config.database_config

# 获取模型配置
model_config = config.model_config

# 获取区域站点
new_england_sites = config.get_region_locations("new_england")
```

### 运行时重载配置

```python
# 重载配置（如配置文件更新后）
config.reload()
```

## 配置验证

### 站点数据验证规则

1. **经度范围**: -180 ~ 180
2. **纬度范围**: -90 ~ 90
3. **名称唯一性**: 站点名称不能重复
4. **最小站点数**: 至少需要 3 个活跃站点

### 配置检查脚本

```python
def validate_config():
    """验证配置完整性"""
    config = get_config()
    
    # 检查站点数量
    active_locations = config.get_active_locations()
    if len(active_locations) < 3:
        print(f"⚠️ 警告: 活跃站点不足3个 ({len(active_locations)}个)")
    
    # 检查默认站点
    default = config.get_default_location()
    if not default:
        print("❌ 错误: 未设置默认站点")
    
    # 显示配置信息
    info = config.get_config_info()
    print(f"✅ 配置信息: {info}")
```

## 多环境配置

### 开发环境

1. 复制配置模板:
```bash
cp config/locations.yaml config/locations-dev.yaml
```

2. 设置环境变量:
```bash
export CONFIG_DIR=config
export ENV=development
```

3. 修改开发配置:
```yaml
system:
  env: development
  log_level: DEBUG
```

### 生产环境

1. 使用安全配置:
```yaml
database:
  password: "${MYSQL_PASSWORD}"  # 从环境变量读取
```

2. 安全建议:
- 敏感信息使用环境变量
- 关闭DEBUG日志
- 启用监控和告警

## 配置最佳实践

### 1. 敏感信息管理

**推荐**: 使用环境变量
```bash
export MYSQL_PASSWORD="复杂密码"
```

**不推荐**:
```yaml
database:
  password: "明文密码"  # 禁止在配置文件中直接写密码
```

### 2. 版本控制

**应该提交**:
- `config/locations.yaml` 示例文件
- `config/application.yaml.example`

**不应该提交**:
- `config/application.yaml` (如果包含敏感信息)
- `.env`

### 3. 配置变更管理

1. **变更前备份**:
```bash
cp config/locations.yaml config/locations.yaml.bak
```

2. **新增站点规范**:
```yaml
# 标准格式
- name: "CityName"    # 首字母大写，无空格
  lat: 42.1234         # 保留4位小数
  lon: -71.1234        # 保留4位小数
  state: "XX"          # 标准2位州代码
  active: true         # 新站点默认启用
```

3. **批量操作**:
```python
# 批量禁用站点
for loc in locations:
    if loc.state == "NH":  # 禁用新罕布什尔州所有站
        loc.active = false
```

### 4. 监控与告警

配置文件变更应监控以下指标:

| 指标 | 阈值 | 动作 |
|------|------|------|
| 活跃站点数 | < 3 | 告警 |
| 响应时间 | > 5s | SlowLog |
| 配置加载失败 | 任何 | Error |

通过本指南，您应该能够全面理解和管理智能电网负荷预测系统的配置。

## 参考

- [PyYAML 文档](https://pyyaml.org/)
- [环境变量最佳实践](https://12factor.net/config)
