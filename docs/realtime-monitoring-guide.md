# 智能电网负荷预测系统 - 监控面板实时跟踪

## 📋 目录

- [监控架构概览](#monitoring-architecture)
- [快速启动指南](#quick-start)
- [监控组件详解](#monitoring-components)
- [可视化仪表板](#dashboard)
- [性能指标说明](#metrics)
- [告警配置](#alerting)
- [故障排除](#troubleshooting)

---

## 🏗️ 监控架构概览 <a name="monitoring-architecture"></a>

### 架构组成

```
┌─────────────────┐
│  Prometheus     │ ← 指标收集
│  (端口 9090)    │
└────────┬────────┘
         │
         ↓
┌─────────────────┐      ┌─────────────────┐
│  Grafana        │ ←─── │  Smart Grid API │
│  (端口 3000)    │      │  (端口 8000)    │
└────────┬────────┘      └────────┬────────┘
         │                        │
         ↓                        ↓
┌─────────────────┐      ┌─────────────────┐
│  PostgreSQL     │      │  Redis          │
│  (端口 5432)    │      │  (端口 6379)    │
└─────────────────┘      └─────────────────┘
         │                        │
         └────────┬───────────────┘
                  ↓
         ┌─────────────────┐
         │  Monitoring     │
         │  Dashboard      │
         │  (端口 8001)    │
         └─────────────────┘
```

### 监控数据流

1. **指标采集**: Prometheus定期抓取API的`/metrics`端点
2. **数据存储**: PostgreSQL存储历史数据和Redis缓存实时数据
3. **可视化**: Grafana从Prometheus读取数据并展示
4. **实时推送**: WebSocket推送实时数据到监控仪表板

---

## 🚀 快速启动指南 <a name="quick-start"></a>

### 方法一: Docker Compose启动 (推荐)

```bash
# 1. 启动所有监控服务
docker-compose up -d

# 2. 查看服务状态
docker-compose ps

# 3. 查看日志
docker-compose logs -f smartgrid-api
```

### 方法二: 手动启动

```bash
# 1. 启动PostgreSQL
docker run -d --name postgres \
  -e POSTGRES_DB=smartgrid \
  -e POSTGRES_USER=admin \
  -e POSTGRES_PASSWORD=password \
  -p 5432:5432 \
  postgres:15-alpine

# 2. 启动Redis
docker run -d --name redis \
  -p 6379:6379 \
  redis:7-alpine

# 3. 启动Prometheus
docker run -d --name prometheus \
  -p 9090:9090 \
  -v $(pwd)/docker/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus:latest

# 4. 启动Grafana
docker run -d --name grafana \
  -p 3000:3000 \
  -e GF_SECURITY_ADMIN_PASSWORD=admin123 \
  grafana/grafana:latest

# 5. 启动监控仪表板
python realtime_api/app_dashboard.py
```

### 访问监控界面

| 服务 | 地址 | 用户名/密码 |
|------|------|------------|
| **监控仪表板** | http://localhost:8001 | - |
| **Grafana** | http://localhost:3000 | admin/admin123 |
| **Prometheus** | http://localhost:9090 | - |
| **API指标** | http://localhost:8000/metrics | - |

---

## 🔧 监控组件详解 <a name="monitoring-components"></a>

### 1. 监控服务 (`monitoring_service.py`)

**核心功能**:
- 系统性能监控 (CPU, 内存, GPU)
- API性能指标收集
- 模型推理统计
- 缓存性能分析
- 实时预警

**主要类**:

```python
class MonitoringService:
    """实时监控服务"""
    
    # 系统指标
    def _collect_system_metrics() -> SystemMetrics
    
    # API指标
    def _collect_api_metrics() -> APIMetrics
    
    # 模型指标
    def _collect_model_metrics() -> ModelMetrics
    
    # 预警检查
    def _check_alerts()
    
    # WebSocket广播
    def _broadcast_metrics()
```

### 2. Prometheus配置

**配置文件**: `docker/prometheus.yml`

**关键配置**:

```yaml
global:
  scrape_interval: 15s  # 采集间隔
  evaluation_interval: 15s  # 规则评估间隔

scrape_configs:
  - job_name: 'smartgrid-api'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['smartgrid-api:8000']
```

### 3. Grafana仪表板

**仪表板文件**: `docker/grafana/dashboards/smartgrid-dashboard.json`

**主要面板**:

1. **系统资源使用率**: CPU和内存实时曲线
2. **API响应时间分布**: P50/P95/P99响应时间
3. **模型推理性能**: 推理时间和成功率
4. **缓存命中率**: Redis缓存效果
5. **性能预警**: 实时告警展示

---

## 📊 可视化仪表板 <a name="dashboard"></a>

### 实时监控仪表板 (端口 8001)

**访问**: http://localhost:8001

**功能特点**:

- ⚡ **实时更新**: WebSocket推送，秒级刷新
- 📈 **可视化图表**: Chart.js动态图表
- 🚨 **预警提示**: 实时性能告警
- 📱 **响应式设计**: 支持移动设备

**主要指标展示**:

```
┌─────────────────────────────────────────┐
│  智能电网负荷预测系统 - 实时监控        │
├─────────────────────────────────────────┤
│  CPU: 45.2%    内存: 62.1%             │
│  响应时间: 850ms  缓存命中率: 68.5%     │
├─────────────────────────────────────────┤
│  系统资源使用趋势图    API响应时间分布  │
│  [实时曲线图]          [柱状图]         │
├─────────────────────────────────────────┤
│  性能预警:                              │
│  ⚠️ CPU使用率超过80%                    │
└─────────────────────────────────────────┘
```

### Grafana仪表板 (端口 3000)

**访问**: http://localhost:3000

**预设仪表板**:

1. **系统概览**: 整体性能一目了然
2. **API性能**: 详细的API指标分析
3. **模型监控**: 推理性能和准确率
4. **资源监控**: 系统资源使用情况

---

## 📈 性能指标说明 <a name="metrics"></a>

### 系统性能指标

| 指标 | 描述 | 阈值 |
|------|------|------|
| `cpu_percent` | CPU使用率 (%) | <80% 正常 |
| `memory_percent` | 内存使用率 (%) | <85% 正常 |
| `gpu_memory_used_mb` | GPU显存使用 (MB) | <80% 总显存 |
| `gpu_utilization_percent` | GPU利用率 (%) | >50% 高效 |

### API性能指标

| 指标 | 描述 | 目标值 |
|------|------|--------|
| `api_total_requests_total` | 总请求数 | N/A |
| `api_successful_requests_total` | 成功请求数 | >95% |
| `api_failed_requests_total` | 失败请求数 | <5% |
| `api_response_time_ms{p50}` | 第50百分位响应时间 | <1000ms |
| `api_response_time_ms{p95}` | 第95百分位响应时间 | <15000ms |
| `api_response_time_ms{p99}` | 第99百分位响应时间 | <30000ms |
| `api_requests_per_second` | 请求吞吐量 | >10 RPS |

### 模型推理指标

| 指标 | 描述 | 目标值 |
|------|------|--------|
| `model_total_inferences_total` | 总推理次数 | N/A |
| `model_inference_time_ms` | 平均推理时间 | <1000ms |
| `model_cache_hit_ratio` | 缓存命中率 | >60% |
| `gpu_inferences` | GPU推理次数 | >80% |

---

## 🚨 告警配置 <a name="alerting"></a>

### 预警规则

**系统资源告警**:

```python
alert_thresholds = {
    'cpu_percent': {
        'warning': 80,  # 80% CPU使用率警告
        'critical': 95  # 95% CPU使用率严重
    },
    'memory_percent': {
        'warning': 85,  # 85% 内存使用率警告
        'critical': 95  # 95% 内存使用率严重
    }
}
```

**API性能告警**:

```python
{
    'response_time_ms': {
        'warning': 25000,  # 25秒响应时间警告
        'critical': 35000  # 35秒响应时间严重
    },
    'error_rate': {
        'warning': 0.05,   # 5% 错误率警告
        'critical': 0.1    # 10% 错误率严重
    }
}
```

### 告警通知

**WebSocket实时推送**:

```javascript
// WebSocket消息格式
{
    "type": "metrics_update",
    "alerts": [
        {
            "alert_type": "warning",
            "metric_name": "cpu_percent",
            "current_value": 85.2,
            "threshold": 80,
            "message": "CPU使用率警告: 85.2%"
        }
    ]
}
```

---

## 🔍 故障排除 <a name="troubleshooting"></a>

### 常见问题

#### 1. Prometheus无法采集指标

**症状**: Prometheus targets显示down

**解决方案**:

```bash
# 检查API服务是否正常运行
curl http://localhost:8000/health

# 检查metrics端点
curl http://localhost:8000/metrics

# 检查Prometheus配置
docker exec -it smartgrid-prometheus cat /etc/prometheus/prometheus.yml
```

#### 2. Grafana无法连接数据源

**症状**: Grafana仪表板显示"No data"

**解决方案**:

```bash
# 检查Prometheus连接
docker exec -it smartgrid-grafana curl http://prometheus:9090/-/healthy

# 重新配置数据源
# 访问 Grafana -> Configuration -> Data Sources
```

#### 3. WebSocket连接失败

**症状**: 监控仪表板无实时数据

**解决方案**:

```javascript
// 检查浏览器控制台
// 查看WebSocket连接状态
console.log('WebSocket状态:', ws.readyState);

// 手动重连
function reconnectWebSocket() {
    ws = new WebSocket('ws://localhost:8001/ws/dashboard');
}
```

#### 4. GPU监控无数据

**症状**: GPU指标显示为0

**解决方案**:

```bash
# 检查GPU是否可用
python -c "import torch; print(torch.cuda.is_available())"

# 检查nvidia-ml-py库
pip install nvidia-ml-py3

# 重启监控服务
docker-compose restart smartgrid-api
```

### 性能调优

#### Prometheus优化

```yaml
# 调整采集间隔
global:
  scrape_interval: 30s  # 减少采集频率

# 调整存储保留时间
storage:
  tsdb:
    retention: 15d  # 减少存储时间
```

#### Grafana优化

```ini
# grafana.ini
[database]
max_open_conn = 10
max_idle_conn = 5

[session]
session_provider = memory
```

---

## 📚 扩展阅读

### 监控最佳实践

1. **分层监控**: 从系统 → 应用 → 业务逐层监控
2. **合理阈值**: 根据实际业务设定告警阈值
3. **定期审查**: 每月审查监控配置的有效性
4. **容量规划**: 根据监控数据预测资源需求

### 进一步优化

- **添加更多数据源**: 如PostgreSQL exporter, Redis exporter
- **自定义告警规则**: 根据业务特点定制告警
- **仪表板定制**: 创建业务特定的监控视图
- **性能基线**: 建立性能基线用于异常检测

---

**🎉 现在您已经拥有一个完整的实时监控系统，可以全面跟踪智能电网负荷预测系统的性能和健康状态！**