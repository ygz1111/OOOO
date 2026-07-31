# 高可用架构指南

## 概述

本指南介绍智能电网负荷预测系统的高可用架构设计、部署和运维。

### 架构目标

- ✅ **零单点故障**: 任一组件故障不影响整体服务
- ✅ **自动故障转移**: 故障检测和切换自动化
- ✅ **读写分离**: 数据库读写负载分担
- ✅ **服务发现**: 动态服务注册与发现
- ✅ **负载均衡**: 请求在多实例间均衡分发

### 高可用架构图

```
                                           ┌─────────────────────────┐
                                           │     Load Balancer       │
                                           │   (外部 Nginx/Caddy)    │
                                           └────────────┬────────────┘
                                                        │
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        │            │                │               │
        │            │                │               │
   ┌────┴───┐    ┌───┴───┐        ┌───┴───┐        ┌──┴────┐
   │API GW #1│    │API GW #2│    │API GW #3│        │Web UI │
   │         │    │         │    │         │        │       │
   └────┬───┘    └───┬───┘    └───┬───┘        └───────┬──────┘
        │             │            │                    │
        ┗━━━━━━━━━━━━━┿━━━━━━━━━━━━┛  服务注册        │
                      │             ┌──────────────────┘
                      └──────────►  │ ┌─────────────┐
                                    ├─┤Consul Server │
                      ┌──────────►  │ │  Cluster    │
                      │             ├─┤ (3节点)     │
                      │             │ └─────────────┘
                      │             │
                      │             │  ┌─────────────┐
                      │             ├─→│ Redis       │
                      │             │  │ Sentinel    │
                      │             │  │ (3节点)     │
                      │             │  └─────────────┘
                      │             │      │
                      │             │  ┌───┼─────────┐
                      │             │  │   │         │
                   ┌──▼─────┐    ┌──▼──┴──┐     ┌───┴─────┐
                   │Redis   │    │Redis   │     │Redis    │
                   │Master  │    │Slave #1│     │Slave #2 │
                   │        │◄──►│       │◄───►│         │
                   └────────┘    └────────┘     └─────────┘
                      ▲                             ▲
                      │                             │
              ┌───────┴──────┐               ┌────┴─────┐
              │MySQL Router  │               │Weather   │
              │(读写分离)    │               │Collector │
              └───────┬──────┘               │ 集群     │
                      │                      └───┬─────┘
    ╔══════════╗      │     ╔══════════╗        │
    ║  Application      ║      ║  Data Plane    ║        │
    ╚══════════╝      └──────┼─────────┐  ┌─────┴──────────┐
                          ┌───▼──┐ ┌───▼──┐ ┌──┴─────────┐
                          ├MySQL │ ├MySQL │ └──┬─────────┘
                          │Primry│ │Repli-│    │
                          │      │ │cate   │    │  ┌─────────┐
                          └─┬────┘ └──────┘    ├─→ │Feature  │
                            │  ▲          WAL     │  │Engine   │
                            │  └──────────┼──────┤  │集群     │
                      ┌─────┘             │      │  └────┬────┘
                      │                   │      │       │
                ┌─────▼─────┐       ┌─────▼────┐ ┌──────┴────┐
                │Backup     │       │WAL-G      │ │Model     │
                │Storage    │       │Archive    │ │Inference │
                │(S3/MinIO) │       │(S3)       │ │集群      │
                └───────────┘       └──────────┘ └───────────┘
```

## 组件说明

### 数据库高可用 (MySQL)

#### 架构
- **MySQL Primary**: 主库，处理所有写操作
- **MySQL Replica × 2**: 从库，处理读操作和故障转移
- **MySQL Router**: 读写分离代理

#### 特性
- ✅ **流复制**: 从库实时同步主库数据
- ✅ **半同步复制**: 至少一个从库确认后主库提交
- ✅ **自动failover**: MySQL Router检测主库故障并切换到从库
- ✅ **读写分离**: 应用透明地分离读写请求

### Redis高可用

#### 架构
- **Redis Master**: 主节点
- **Redis Slave × 2**: 从节点
- **Redis Sentinel × 3**: 哨兵集群

#### 特性
- ✅ **主从复制**: 从节点实时同步主节点
- ✅ **自动故障转移**: Sentinel检测主节点故障并选举新的主节点
- ✅ **读写分离**: 应用可配置从节点分担读负载
- ✅ **哨兵仲裁**: 3节点哨兵保证决策无冲突

### 服务发现 (Consul)

#### 架构
- **Consul Server × 3**: 服务发现集群
- **Consul Agent**: 每个服务节点运行

#### 特性
- ✅ **服务注册**: Service自动注册到Consul
- ✅ **健康检查**: 定期检测服务健康状态
- ✅ **服务发现**: 客户端查询健康可用服务
- ✅ **KV存储**: 配置信息分布式存储

### 业务服务高可用

#### 多实例部署
- **API Gateway × 3**: 3个实例
- **Weather Collector × 2**: 2个实例
- **Feature Engine × 2**: 2个实例
- **Model Inference × 2**: 2个实例

#### 特性
- ✅ **无状态**: 业务服务无本地状态
- ✅ **幂等性**: 重复执行结果一致
- ✅ **健康检查**: HTTP健康检查端点
- ✅ **滚动更新**: 不停机更新服务

## 部署指引

### 1. 前提条件

```bash
# 宿主机硬件要求
CPU: 8核以上
内存: 24GB以上
磁盘: 100GB以上
网络: 千兆网卡

# 软件依赖
docker >= 20.10.0
docker-compose >= 1.29.0
```

### 2. 启动高可用集群

```bash
# 1. 使用高可用配置文件启动
cd OOOOOO/docker
docker-compose -f docker-compose-ha.yml up -d

# 2. 检查服务状态
docker-compose -f docker-compose-ha.yml ps

# 3. 查看服务日志
docker logs -f grid-mysql-primary
docker logs -f grid-redis-master
docker logs -f grid-consul-1
```

### 3. 验证高可用功能

#### 数据库高可用测试

```bash
# 连接到 Router 写端口
mysql -h localhost -P 6447 -u griduser -p grid_pass123

# 写入测试数据
INSERT INTO test_ha VALUES ('ha_test_1');

# 模拟主库故障 (停止主库)
docker stop grid-mysql-primary

# Router 应该自动切换到从库
# 重新连接并继续操作
```

#### Redis高可用测试

```bash
# 连接到任何Redis节点
redis-cli -h localhost -p 6379 -a redis123

# 写入数据
SET test_key "ha_test_value"

# 模拟主节点故障
docker stop grid-redis-master

# Sentinel 应该自动选举新的主节点
# 客户端应该能够继续连接
```

### 4. 配置外部负载均衡器

```nginx
# nginx.conf 示例
upstream api_gateway {
    least_conn;           # 最少连接负载均衡
    server 172.21.0.1:8000 max_fails=3 fail_timeout=30s;
    server 172.21.0.2:8000 max_fails=3 fail_timeout=30s;
    server 172.21.0.3:8000 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;
    server_name api.grid-predict.com;

    location / {
        proxy_pass http://api_gateway;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## 监控与健康检查

### 健康检查端点

| 服务 | 端点 | 说明 |
|------|------|------|
| API Gateway | `/api/system/status` | 服务状态 |
| Weather Collector | `/health` | 健康检查 |
| Feature Engine | `/health` | 健康检查 |
| Model Inference | `/health` | 健康检查 |

### 关键指标

#### MySQL Router
```bash
# 查看连接状态
SELECT * FROM performance_schema.connection_pool_status;

# 检查后端健康状态
SHOW STATUS LIKE 'mysql%'
```

#### Redis Sentinel
```bash
# 查看主节点状态
redis-cli -p 26379 sentinel master mymaster

# 查看从节点状态
redis-cli -p 26379 sentinel slaves mymaster
```

#### Consul
```bash
# 查看所有服务
curl http://localhost:8500/v1/catalog/services

# 查看特定服务健康状态
curl http://localhost:8500/v1/health/service/api-gateway
```

## 故障排查

### 1. MySQL高可用问题

#### 问题: 从库复制延迟
```bash
# 查看复制状态
SHOW SLAVE STATUS\G

# 关键指标
- Slave_IO_Running
- Slave_SQL_Running
- Seconds_Behind_Master
```

#### 问题: Router无法连接到后端
```bash
# 检查后端连接
docker logs grid-mysql-router

# 验证后端健康
docker exec grid-mysql-primary mysql -u root -proot123 -e "SELECT 1;"
```

### 2. Redis高可用问题

#### 问题: Sentinel无法选举新主节点
```bash
# 检查哨兵状态
redis-cli -p 26379 info sentinel

# 验证网络连接
ping redis-master
ping redis-slave
```

#### 问题: 客户端连接超时
```bash
# 检查 Redis 进程
redis-cli -a redis123 info

# 检查内存使用
redis-cli -a redis123 info memory
```

### 3. Consul问题

#### 问题: 服务未注册
```bash
# 检查服务日志
docker logs grid-consul-1

# 验证服务状态
consul catalog services

# 检查健康检查
consul monitor
```

## 备份与恢复

### 1. MySQL备份

```bash
# 使用 mysqldump
mysqldump -h localhost -P 6447 -u griduser -p --all-databases > backup.sql

# 或从主库直接备份
mysqldump -h mysql-primary -u griduser -p --single-transaction --routines --triggers > backup.sql
```

### 2. Redis备份

```bash
# 从Slave备份(不影响性能)
redis-cli -h redis-slave -a redis123 SAVE
cp /var/lib/redis/dump.rdb /backup/redis-backup-$(date +%Y%m%d).rdb
```

### 3. Consul备份

```bash
# 使用 consul snapshot
consul snapshot save backup.snap
```

## 扩展性设计

### 1. 水平扩展API层

```yaml
# 增加API实例数量
deploy:
  replicas: 6        # 从3扩展到6个实例
  resources:
    limits:
      memory: 512M   # 每个实例内存
    reservations:
      memory: 256M
```

### 2. 扩展MySQL从库

```yaml
# 增加从库数量
deploy:
  replicas: 4        # 从2扩展到4个从库
  resources:
    limits:
      memory: 1G
      cpus: "1"
```

### 3. 增加Redis从节点

```yaml
# 扩展Redis集群
deploy:
  replicas: 4        # 从2扩展到4个从节点
  resources:
    limits:
      memory: 600M
```

## 安全配置

### 1. 网络策略

```bash
# 限制外部访问
# 只开放必要的端口
EXPOSE 8000    # API
EXPOSE 8500    # Consul UI
EXPOSE 26379   # Redis (仅内网)
EXPOSE 6446-6447 # MySQL Router (仅内网)
```

### 2. TLS加密

```yaml
# Redis TLS配置
command: redis-server --tls-port 6379 \
  --port 0 \
  --tls-cert-file /path/to/cert.pem \
  --tls-key-file /path/to/key.pem \
  --tls-ca-cert-file /path/to/ca.pem

# MySQL SSL配置
# 在主从配置中增加SSL相关参数
```

## 性能优化

### 1. MySQL性能调优

```ini
# my.cnf 性能优化
innodb_buffer_pool_size = 2G        # 70%内存
innodb_log_file_size = 256M
innodb_log_buffer_size = 32M
innodb_flush_log_at_trx_commit = 2  # 平衡性能和准确性
max_connections = 500
```

### 2. Redis性能调优

```bash
# redis.conf 优化
maxmemory 512mb
maxmemory-policy allkeys-lru
hz 10
activerehashing no
aof-rewrite-incremental-fsync yes
```

### 3. Docker资源限制

```yaml
# 为关键服务分配更多资源
services:
  model-inference:
    deploy:
      resources:
        limits:
          memory: 4G          # 更多内存给模型推理
          cpus: "8"          # 更多CPU核心
        reservations:
          memory: 2G
          cpus: "4"
```

## 监控告警

### 关键告警阈值

| 指标 | 警告阈值 | 严重阈值 | 动作 |
|------|----------|----------|------|
| MySQL复制延迟 | > 30秒 | > 300秒 | 扩容从库 |
| Redis内存 | > 80% | > 95% | 增加内存 |
| API响应时间 | > 3秒 | > 10秒 | 扩容API |
| 服务健康 | 1个失败 | 2个失败 | 故障转移 |
| CPU使用率 | > 80% | > 95% | 扩容 |

### Prometheus查询示例

```promql
# API请求延迟
rate(http_request_duration_seconds_sum[5m]) / rate(http_request_duration_seconds_count[5m])

# MySQL连接数
mysql_global_status_threads_connected

# Redis内存使用
redis_memory_used_bytes / redis_memory_max_bytes
```

## 升级策略

### 1. 滚动更新

```bash
# 逐个更新服务实例，保证始终有可用实例
docker-compose -f docker-compose-ha.yml up -d --scale api-gateway=6 --no-recreate
docker-compose -f docker-compose-ha.yml up -d --scale api-gateway=3
```

### 2. 蓝绿部署

```bash
# 准备新版本实例组
docker-compose -f docker-compose-ha-blue.yml up -d

# 切换流量
# 更新负载均衡器配置

# 验证新版本
# 测试API和新功能

# 停用旧版本
docker-compose -f docker-compose-ha-green.yml down
```

### 3. Canary发布

```bash
# 先部署到小部分流量
docker-compose -f docker-compose-ha.yml scale api-gateway=4

# 配置负载均衡器
# 将10%流量导向新版本

# 监控错误率和延迟
# 无问题则逐步增加流量
```

## 成本估算

### 1. 硬件成本

| 组件 | 数量 | 配置 | 月成本(¥) |
|------|------|------|----------|
| 计算节点 | 3台 | 8核32G | 4500 |
| 存储 | 1TB SSD | - | 800 |
| 网络 | 1GbE | - | 500 |
| **总计** | - | - | **5800** |

### 2. 维护成本

| 任务 | 频率 | 工时 | 成本 |
|------|------|------|------|
| 日常巡检 | 每天 | 0.5h | ¥50/天 |
| 性能优化 | 每周 | 2h | ¥400/周 |
| 故障处理 | 每月 | 4h | ¥800/月 |
| 版本升级 | 每季度 | 16h | ¥3200/季度 |

## 应急预案

### 场景1: MySQL主库完全宕机

1. **自动响应**:
   - MySQL Router检测连接失败
   - 自动切换到健康从库(提升为新主库)
   - 应用继续正常运行

2. **人工介入**:
   - 检查原主库故障原因
   - 修复后作为新从库重新加入集群
   - 更新监控告警联系人

### 场景2: Redis集群不可用

1. **自动响应**:
   - Sentinel选举新的主节点
   - 客户端自动重连到新主节点
   - 只读模式降级运行

2. **人工介入**:
   - 检查网络分区问题
   - 手动强制切换(如有需要)
   - 恢复数据一致性

### 场景3: 单个区域故障

1. **预防**:
   - 跨可用区部署
   - 同步全局数据
   - 配置区域健康检查

2. **恢复**:
   - 自动切换到备用区域
   - 数据同步追赶
   - 相关告警通知

---

## 总结

本高可用架构实现了:

- ✅ **服务无单点故障**
- ✅ **自动故障转移**
- ✅ **读写分离**
- ✅ **服务发现与注册**
- ✅ **水平扩展能力**
- ✅ **完善的监控告警**

**可用性目标**: 99.99% (全年停机 < 52分钟)

---

**附录**

- 相关文档: `docker-compose-ha.yml`
- 配置文件: `docker/mysql/`, `docker/redis/`
- 监控面板: Grafana dashboard ID: grid-ha-overview