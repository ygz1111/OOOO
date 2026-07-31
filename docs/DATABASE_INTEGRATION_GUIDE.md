# 智能电网负荷预测系统 - MySQL数据库集成指南

## 目录

- [概述](#概述)
- [数据库架构](#数据库架构)
- [系统配置](#系统配置)
- [API文档](#api文档)
- [部署指南](#部署指南)
- [运维监控](#运维监控)
- [故障排查](#故障排查)

## 概述

本项目已完成MySQL数据库的企业级集成，实现完整的预测结果持久化功能。

### 核心功能

- ✅ **预测结果持久化**: 所有负荷预测结果自动保存到MySQL
- ✅ **历史数据查询**: 支持时间范围、模型类型等多条件查询
- ✅ **高性能CRUD**: 批量插入优化、连接池管理
- ✅ **企业级监控**: 系统指标、API日志、性能预警
- ✅ **数据完整视图**: 提供多个数据分析视图
- ✅ **可扩展架构**: 同步/异步混合模式，支持高并发

### 技术栈

- **数据库**: MySQL 8.0 + mysql-connector-python
- **连接池**: 异步连接池管理，支持高并发
- **数据架构**: 7大核心数据表，完整生命周期管理
- **API**: FastAPI + Pydantic + 异步数据库操作

---

## 数据库架构

### 表结构

#### 1. 气象数据表 (weather_data)

```sql
CREATE TABLE weather_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    location VARCHAR(100) NOT NULL,          -- 气象站位置
    latitude DECIMAL(10, 8) DEFAULT 42.36,  -- 纬度
    longitude DECIMAL(11, 8) DEFAULT -71.06, -- 经度
    
    -- 核心气象参数
    temperature_2m DECIMAL(6, 2),            -- 2米高度温度(℃)
    relative_humidity_2m DECIMAL(5, 2),      -- 相对湿度(%)
    wind_speed_10m DECIMAL(6, 2),            -- 10米风速(m/s)
    cloud_cover DECIMAL(5, 2),               -- 云覆盖率(%)
    shortwave_radiation DECIMAL(8, 2),       -- 短波辐射(W/m²)
    
    data_quality_score DECIMAL(3, 2) DEFAULT 0.95, -- 数据质量评分
    is_validated BOOLEAN DEFAULT FALSE,       -- 是否已验证
    data_source VARCHAR(50) DEFAULT 'openmeteo',  -- 数据源
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

#### 2. 负荷预测表 (load_predictions)

```sql
CREATE TABLE load_predictions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    prediction_id CHAR(36) DEFAULT (UUID()),  -- 批次ID
    prediction_timestamp DATETIME NOT NULL,   -- 预测生成时间
    target_timestamp DATETIME NOT NULL,       -- 预测目标时间
    
    load_forecast_mw DECIMAL(10, 3),          -- 负荷预测值(MW)
    pv_estimation_mw DECIMAL(10, 3),          -- 光伏估算(MW)
    net_load_mw DECIMAL(10, 3),               -- 净负荷(MW)
    confidence_lower_mw DECIMAL(10, 3),       -- 置信下限
    confidence_upper_mw DECIMAL(10, 3),       -- 置信上限
    
    model_type VARCHAR(50) DEFAULT 'ensemble', -- 模型类型
    model_weights JSON,                        -- 模型权重(支持多模型集成)
    inference_time_ms DECIMAL(10, 3),         -- 推理耗时(毫秒)
    cache_hit BOOLEAN DEFAULT FALSE,           -- 缓存命中
    data_source VARCHAR(50),                   -- 数据源
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### 3. 其他核心表

- **model_performance**: 模型性能指标记录
- **api_request_logs**: API请求完整日志
- **system_metrics**: 系统资源监控指标
- **cache_performance**: 缓存系统性能
- **performance_alerts**: 性能预警和告警

### 索引设计

```sql
-- 高效查询索引
CREATE INDEX idx_weather_location_timestamp ON weather_data(location, timestamp);
CREATE INDEX idx_predictions_target_timestamp ON load_predictions(target_timestamp);
CREATE INDEX idx_predictions_model_type ON load_predictions(model_type);
CREATE INDEX idx_api_logs_timestamp ON api_request_logs(timestamp);
CREATE INDEX idx_system_metrics_timestamp ON system_metrics(timestamp);
```

### 视图定义

```sql
-- 最新气象数据视图
drop view if exists latest_weather_data;
CREATE VIEW latest_weather_data AS
SELECT location, timestamp, temperature_2m, relative_humidity_2m,
       wind_speed_10m, cloud_cover, shortwave_radiation, data_quality_score
FROM weather_data
WHERE DATE(timestamp) = CURDATE()
ORDER BY location, timestamp DESC;

-- 今日预测结果视图
drop view if exists today_predictions;
CREATE VIEW today_predictions AS
SELECT prediction_timestamp, target_timestamp, load_forecast_mw,
       pv_estimation_mw, net_load_mw, model_type, inference_time_ms
FROM load_predictions
WHERE DATE(prediction_timestamp) = CURDATE()
ORDER BY target_timestamp;

-- 系统健康状态视图
drop view if exists system_health;
CREATE VIEW system_health AS
SELECT timestamp, cpu_percent, memory_percent, gpu_memory_used_mb,
       gpu_utilization_percent
FROM system_metrics
WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
ORDER BY timestamp DESC
LIMIT 100;
```

---

## 系统配置

### 环境变量

```bash
# MySQL数据库配置
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DATABASE=OOOO
MYSQL_USER=root
MYSQL_PASSWORD=315131
MYSQL_POOL_SIZE=10

# 应用配置
ENV=production
LOG_LEVEL=INFO
TZ=Asia/Shanghai

# GPU配置
NVIDIA_VISIBLE_DEVICES=all
CUDA_VISIBLE_DEVICES=0

# 性能配置
OMP_NUM_THREADS=4
MKL_NUM_THREADS=4
MAX_WORKERS=8
BATCH_SIZE=16
CACHE_TTL=300
```

### Docker配置

```yaml
# MySQL服务配置
mysql:
  image: mysql:8.0
  container_name: smartgrid-mysql
  restart: unless-stopped
  environment:
    MYSQL_ROOT_PASSWORD: 315131
    MYSQL_DATABASE: OOOO
    TZ: Asia/Shanghai
  
  volumes:
    - mysql-data:/var/lib/mysql
    - ./docker/init-db.sql:/docker-entrypoint-initdb.d/init.sql:ro
  
  ports:
    - "3306:3306"
  
  healthcheck:
    test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-p315131"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 30s
  
  deploy:
    resources:
      limits:
        cpus: '1.0'
        memory: 1G
  
  command: >
    --character-set-server=utf8mb4
    --collation-server=utf8mb4_unicode_ci
    --explicit_defaults_for_timestamp=1
    --default-time-zone=+08:00
```

### 连接池参数

```python
# 数据库连接池配置
pool_size = 10                               # 最大连接数
pool_reset_session = True                    # 会话重置
autocommit = True                            # 自动提交
charset = 'utf8mb4'                          # 字符集
connection_timeout = 30                      # 连接超时(秒)
max_allowed_packet = 64 * 1024 * 1024        # 64MB最大包大小
```

---

## API文档

### 历史数据查询API

#### 1. 历史负荷预测查询

```http
GET /api/prediction/history
```

**查询参数:**

| 参数 | 类型 | 必填 | 描述 | 示例 |
|------|------|------|------|------|
| start_time | string | 否 | 开始时间(ISO8601) | `2026-07-25T00:00:00` |
| end_time | string | 否 | 结束时间(ISO8601) | `2026-07-25T23:59:59` |
| model_type | string | 否 | 模型类型过滤 | `ensemble` |
| limit | integer | 否 | 返回数量(1-1000) | `100` |

**响应示例:**

```json
{
  "success": true,
  "message": "成功获取历史预测数据，共15条记录",
  "data": [
    {
      "id": 1,
      "prediction_id": "550e8400-e29b-41d4-a716-446655440000",
      "prediction_timestamp": "2026-07-25 10:00:00",
      "target_timestamp": "2026-07-25 11:00:00",
      "load_forecast_mw": 1200.5,
      "pv_estimation_mw": 150.2,
      "net_load_mw": 1050.3,
      "model_type": "ensemble",
      "inference_time_ms": 125.5,
      "created_at": "2026-07-25 10:00:00"
    }
  ],
  "timestamp": "2026-07-25T15:30:00"
}
```

#### 2. 历史气象数据查询

```http
GET /api/weather/history
```

**查询参数:**

| 参数 | 类型 | 必填 | 描述 | 示例 |
|------|------|------|------|------|
| location | string | 否 | 位置名称 | `Boston` |
| hours | integer | 否 | 小时数(1-720) | `24` |
| limit | integer | 否 | 返回数量(1-1000) | `100` |

#### 3. 系统监控指标查询

```http
GET /api/system/metrics
```

**查询参数:**

| 参数 | 类型 | 描述 |
|------|------|------|
| hours | integer | 查询时间范围(小时) |
| limit | integer | 返回数量限制 |

### 预测执行API

#### 负荷预测执行

```http
POST /api/prediction/load
```

**请求体:**

```json
{
  "location": "Boston",
  "target_date": "2026-07-25",
  "hours_ahead": 24,
  "include_pv": true,
  "model_type": "ensemble"
}
```

**功能:**
- 执行24小时负荷预测
- **自动保存预测结果到MySQL**
- 支持光伏估算
- 返回置信区间

---

## 部署指南

### 1. 数据库初始化

```bash
# 使用DBeaver或其他MySQL客户端
# 1. 创建数据库
CREATE DATABASE OOOO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

# 2. 执行初始化脚本
mysql -u root -p OOOO < docker/init-db.sql

# 3. 验证表结构
USE OOOO;
SHOW TABLES;
```

### 2. 应用部署

#### 方式A: Docker Compose（推荐）

```bash
# 启动完整服务栈
docker-compose up -d

# 查看服务状态
docker-compose ps

docker-compose logs smartgrid-api
```

#### 方式B: 本地直接运行

```bash
# 安装依赖
pip install mysql-connector-python SQLAlchemy pymysql fastapi uvicorn pydantic

# 启动应用
cd realtime_api
python app.py

# 或直接使用uvicorn
uvicorn realtime_api.app:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 数据库连接测试

```bash
# 运行数据库功能测试
python test_database.py

# 预期输出:
# ✅ 数据库连接        通过
# ✅ 气象数据CRUD      通过
# ✅ 负荷预测CRUD      通过
# ✅ 模型性能CRUD      通过
# ✅ API日志CRUD       通过
# ✅ 批量操作          通过
# 总结: 6/6 项测试通过
```

---

## 运维监控

### 数据库性能监控

```sql
-- 查看慢查询(执行时间>1s)
SELECT * FROM performance_schema.events_statements_summary_by_digest
WHERE AVG_TIMER_WAIT > 1000000000
ORDER BY AVG_TIMER_WAIT DESC;

-- 查看表空间使用情况
SELECT 
    table_name,
    round(((data_length + index_length) / 1024 / 1024), 2) "Size (MB)"
FROM information_schema.TABLES 
WHERE table_schema = "OOOO";

-- 查看连接池使用情况
SHOW STATUS LIKE 'Threads_%';
SHOW STATUS LIKE 'Connections';
```

### API监控指标

```sql
-- 查询API调用统计
SELECT 
    endpoint,
    method,
    COUNT(*) as call_count,
    AVG(response_time_ms) as avg_response_time_ms,
    AVG(status_code) as avg_status_code
FROM api_request_logs 
WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
GROUP BY endpoint, method;

-- 查询错误率
SELECT 
    status_code,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM api_request_logs 
                              WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)), 2) as percentage
FROM api_request_logs 
WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
GROUP BY status_code;
```

### 预测性能监控

```sql
-- 模型推理性能统计
SELECT 
    model_type,
    COUNT(*) as predictions_count,
    AVG(inference_time_ms) as avg_inference_time_ms,
    MIN(inference_time_ms) as min_inference_time_ms,
    MAX(inference_time_ms) as max_inference_time_ms
FROM load_predictions 
WHERE prediction_timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
GROUP BY model_type;

-- 缓存命中率
SELECT 
    COUNT(*) as total_predictions,
    SUM(cache_hit) as cache_hits,
    ROUND(SUM(cache_hit) * 100.0 / COUNT(*), 2) as cache_hit_rate
FROM load_predictions 
WHERE prediction_timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR);
```

---

## 故障排查

### 常见问题

#### 1. 数据库连接失败

**症状:** `Can't connect to MySQL server`

**解决方案:**

```bash
# 检查MySQL服务状态
systemctl status mysql

# 检查端口监听
netstat -tlnp | grep 3306

# 测试连接
mysql -u root -p -h localhost OOOO

# 检查防火墙
sudo ufw status | grep 3306
sudo ufw allow 3306
```

#### 2. 连接池耗尽

**症状:** `Too many connections`

**解决方案:**

```sql
-- 查看当前连接数
SHOW STATUS LIKE 'Threads_%';
SHOW PROCESSLIST;

-- 临时增加最大连接数
SET GLOBAL max_connections = 200;

-- 永久修改
# 在 /etc/mysql/mysql.conf.d/mysqld.cnf 中添加
[mysqld]
max_connections = 200
```

#### 3. 插入数据失败

**症状:** 预测结果未保存

**解决方案:**

```bash
# 检查MySQL错误日志
tail -f /var/log/mysql/error.log

# 测试数据库权限
mysql -u root -p -e "SHOW GRANTS FOR CURRENT_USER;"

# 检查数据表状态
USE OOOO;
CHECK TABLE load_predictions;
ANALYZE TABLE load_predictions;
```

#### 4. 查询性能慢

**症状:** 历史数据查询响应慢

**解决方案:**

```sql
-- 检查索引使用情况
EXPLAIN SELECT * FROM load_predictions WHERE target_timestamp > '2026-07-24';

-- 优化查询
-- 确保使用索引
CREATE INDEX idx_predictions_timestamp_type ON load_predictions(target_timestamp, model_type);

-- 分区表 (大数据量时使用)
ALTER TABLE load_predictions 
PARTITION BY RANGE (TO_DAYS(target_timestamp)) (
    PARTITION p2026_07 VALUES LESS THAN (TO_DAYS('2026-08-01')),
    PARTITION p2026_08 VALUES LESS THAN (TO_DAYS('2026-09-01')),
    PARTITION p_future VALUES LESS THAN MAXVALUE
);
```

### 性能优化建议

1. **连接池调优:**
   - `pool_size = CPU核心数 * 2`
   - 监控连接使用情况，动态调整

2. **索引优化:**
   - 避免过度索引
   - 使用复合索引覆盖常用查询
   - 定期分析慢查询日志

3. **查询优化:**
   - 使用分页避免大结果集
   - 在应用层实现缓存
   - 避免SELECT *

4. **硬件建议:**
   - InnoDB buffer pool至少占总内存50%
   - 使用SSD存储
   - 合理配置IO参数

---

## 附录

### A. MySQL用户权限配置

```sql
-- 创建只读用户
CREATE USER 'smartgrid_readonly'@'%' IDENTIFIED BY 'readonly_password';
GRANT SELECT ON OOOO.* TO 'smartgrid_readonly'@'%';

-- 创建读写用户
CREATE USER 'smartgrid_readwrite'@'%' IDENTIFIED BY 'readwrite_password';
GRANT SELECT, INSERT, UPDATE, DELETE ON OOOO.* TO 'smartgrid_readwrite'@'%';

FLUSH PRIVILEGES;
```

### B. 备份与恢复

```bash
# 全量备份
mysqldump -u root -p --single-transaction OOOO > backup_$(date +%Y%m%d).sql

# 恢复
mysql -u root -p OOOO < backup_file.sql

# 定时备份脚本
#!/bin/bash
mysqldump -u root -pPASSWORD --single-transaction OOOO | \
gzip > /backup/OOOO_$(date +%Y%m%d_%H%M%S).sql.gz
find /backup -name "*.sql.gz" -mtime +30 -delete
```

### C. 常用MySQL配置

```ini
# /etc/mysql/mysql.conf.d/mysqld.cnf
[mysqld]

# 基本设置
character-set-server=utf8mb4
collation-server=utf8mb4_unicode_ci
default-time-zone=+08:00

# InnoDB设置
innodb_buffer_pool_size = 2G
innodb_log_file_size = 256M
innodb_flush_method = O_DIRECT

# 连接设置
max_connections = 200
wait_timeout = 600
interactive_timeout = 600

# 日志设置
log_error = /var/log/mysql/error.log
general_log = OFF
general_log_file = /var/log/mysql/general.log

# 性能监控
performance_schema = ON
```

---

**维护团队** | 智能电网负荷预测项目组
**最后更新** | 2026年7月25日
**版本** | v1.0.0-MySQL
**联系方式** | dev@smartgrid.edu