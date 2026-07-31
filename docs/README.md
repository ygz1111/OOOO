# 智能电网负荷预测系统

基于深度学习的电力负荷预测系统：4 模型集成（EnhancedLSTM / BiGRU / DeepTCN / SpatialTransformer）
预测未来 24 小时系统负荷，整合 Open-Meteo 实时气象、光伏/风电估算，提供 FastAPI 实时预测服务与
React 可视化前端。

---

## 一、项目概述

### 1.1 核心目标
- **负荷预测**：基于 ISO New England 电网数据（2023-2025），4 模型加权集成预测未来 24 小时负荷
- **实时集成**：通过 Open-Meteo API 获取新英格兰 6 城市实时气象，动态预测
- **光伏/风电融合**：光伏 ML 预测（4 模型）+ 物理模型回退，风电物理估算，净负荷计算
- **生产部署**：FastAPI + MySQL + Redis + Docker Compose 全栈编排

### 1.2 项目现状
- ✅ 数据处理管道完成（产物在 `processed/`，无需重跑）
- ✅ 4 模型训练完成（权重在 `backend/models/models/*.pth`）
- ✅ FastAPI 实时预测服务（认证 + 6 组路由 + 预测入库）
- ✅ React 前端（8 个页面，登录/仪表盘/预测/天气/光伏/风电/系统状态/历史分析）
- ✅ 测试套件（299 个测试，`backend/tests/`）

### 1.3 技术规格
- **数据**：3 年小时级数据，26,304 行，38 个特征
- **模型**：EnhancedLSTM / BiGRU / DeepTCN / SpatialTransformer 加权集成
- **预测精度**（测试集 2017 序列，反归一化真实 MW）：集成 MAPE 7.41%、R² 0.714；
  最优单模型 SpatialTransformer MAPE 4.43%、R² 0.880
- **接口**：REST API（JWT 认证）+ OpenAPI 文档（`/docs`）
- **硬件**：GPU/CPU 推理自适应（无 GPU 时自动 CPU）

---

## 二、项目结构

```
OOOOOO/
├── backend/
│   ├── realtime_api/          # FastAPI 后端（主链路）
│   │   ├── app.py             # 入口（lifespan、中间件、异常处理、路由挂载）
│   │   ├── auth/              # JWT 认证（中间件白名单 + RBAC 依赖）
│   │   ├── routers/           # auth/analytics/prediction/weather/system/generation
│   │   ├── services/          # container（服务容器）、prediction_pipeline（预测管线）
│   │   ├── crud/              # 数据库访问层
│   │   ├── schemas/           # Pydantic 模型
│   │   ├── tasks/             # 后台定时任务（系统监控/性能预警）
│   │   ├── config.py          # 配置管理器（YAML + 环境变量）
│   │   ├── database.py        # MySQL 连接池 + SQLAlchemy async
│   │   ├── openmeteo_client.py    # Open-Meteo 气象客户端
│   │   ├── feature_generator.py   # 实时特征工程（38 维）
│   │   ├── normalization_adapter.py # 归一化/逆归一化
│   │   ├── prediction_service.py  # 模型推理服务
│   │   ├── pv_estimator.py        # 光伏物理估算
│   │   ├── wind_estimator.py      # 风电物理估算
│   │   ├── weather_validator.py   # 气象数据质量校验
│   │   └── monitoring_service.py  # 监控/准确率跟踪
│   ├── models/
│   │   ├── four_models.py     # 4 个模型定义（训练与推理共用）
│   │   ├── visualization.py   # 论文图表可视化
│   │   └── models/            # 训练产物：4 个 .pth + final_results.json（真实指标）
│   ├── train_four_models.py   # 4 模型训练入口
│   ├── scripts/recompute_final_metrics.py  # 测试集真实指标重算（权威指标）
│   ├── tests/                 # 299 个单元测试（pytest）
│   ├── config/                # app_config.yaml / locations.yaml
│   └── requirements.txt
├── frontend/                  # React 18 + Vite + TS + Tailwind + Recharts
│   └── src/
│       ├── pages/             # Login/Dashboard/LoadForecast/WeatherMonitor/
│       │                      # SolarGeneration/WindGeneration/SystemStatus/HistoricalAnalysis
│       ├── components/        # 通用组件 + cyber/（登录页赛博风）
│       ├── contexts/          # ApiContext（轮询）/ AuthContext（登录态）
│       ├── services/api.ts    # Axios API 封装
│       └── types/
├── docs/                      # 项目文档
├── docker-compose.yml         # API + MySQL + Redis + Prometheus + Grafana 编排
└── start.ps1                  # 一键启动（Windows）
```

---

## 三、数据处理

6 步离线管道（脚本已归档，产物在 `processed/`）：
1. **加载**：3 年 Excel 合并（26,304 行）
2. **清洗**：类型统一、夏令时处理、异常检测
3. **时间特征**：小时/星期/年积日正余弦编码
4. **特征工程**：滞后/滚动/气象衍生（38 特征 + 1 目标）
5. **划分**：按时间顺序 train/val/test + MinMaxScaler（仅训练集 fit）
6. **序列化**：168 步滑动窗口 → `step6_sequences.pkl`

关键决策：
- 时间序列**按序划分**，禁止随机打乱（防泄漏）
- Scaler 只在训练集 fit；滞后特征用 `shift()`（防泄漏）
- 目标列：`System_Load`（MW）

---

## 四、模型架构与训练结果

### 4.1 模型架构（`backend/models/four_models.py`）

| 模型 | 结构要点 | 参数量 |
|------|----------|--------|
| EnhancedLSTM | 3 层 LSTM(128) + 注意力 + 残差 | ~1.1M |
| BiGRU | 3 层 BiGRU(128) + 注意力 | ~1.4M |
| DeepTCN | 4 层因果膨胀卷积 [64,128,64,32] | ~0.16M |
| SpatialTransformer | 4 层 Transformer(d_model=128) + 位置编码 | ~2.3M |

统一输入：`(batch, 168, 38)`，输出 `(batch, 24)`。

### 4.2 训练配置

| 参数 | 值 | 说明 |
|------|-----|------|
| HORIZON | 24 小时 | 预测步长 |
| LOOKBACK | 168 小时 | 输入窗口（7 天） |
| BATCH_SIZE | 64 | 批大小 |
| LEARNING_RATE | 1e-3（Transformer 5e-4） | 初始学习率 |
| PATIENCE | 10 | 早停 |
| LOSS | Huber | 对异常值鲁棒 |
| 调度 | ReduceLROnPlateau | 验证损失平台期降 LR |

### 4.3 性能指标（测试集，真实口径）

> 指标在**反归一化后的真实 MW 单位**计算（2017 个测试序列），MAPE 使用 `|y_true|>1` 掩码防除零。
> 由 `backend/scripts/recompute_final_metrics.py` 生成，数据见 `backend/models/models/final_results.json`。

| 模型 | MAPE (%) | RMSE (MW) | R² | MAE (MW) |
|------|----------|-----------|-----|----------|
| EnhancedLSTM | 7.58 | 1244.7 | 0.680 | 1020.4 |
| BiGRU | 10.28 | 1587.2 | 0.480 | 1337.3 |
| SpatialTransformer | **4.43** | **762.6** | **0.880** | **586.1** |
| DeepTCN | 10.41 | 1653.8 | 0.436 | 1397.7 |
| **集成模型** | **7.41** | **1176.6** | **0.714** | **986.6** |

---

## 五、实时预测系统

### 5.1 系统架构

```
Open-Meteo API ──→ weather_validator ──→ feature_generator(38维)
      ↓                                       ↓
历史负荷(MySQL) ─→ HistoricalLoadProvider ─→ normalization_adapter
                                               ↓
                                        build_sequence(168,38)
                                               ↓
                              4 模型集成推理 → inverse_transform → MW
                                               ↓
                      光伏ML预测/物理回退 + 风电估算 + 净负荷
                                               ↓
                                    响应 + 入库 load_predictions
```

### 5.2 API 端点

| 端点 | 说明 | 认证 |
|------|------|------|
| `POST /api/prediction/load` | 24 小时负荷预测 | 需 JWT |
| `POST /api/prediction/batch` | 批量预测 | 需 JWT |
| `GET /api/prediction/history` | 历史预测查询 | 需 JWT |
| `GET /api/weather/current` | 当前气象 | 公开 |
| `GET /api/solar-generation` | 光伏 ML 预测 | 需 JWT |
| `GET /api/wind-generation` | 风电估算 | 需 JWT |
| `GET /api/analytics/*` | 准确性/漂移/趋势分析 | 需 JWT |
| `GET /api/system/status` | 系统状态 | 公开 |
| `GET /api/system/metrics` | 监控指标 | 需 JWT |
| `POST /api/auth/*` | 注册/登录/刷新 | 公开（登录） |
| `GET /api/health` | 健康检查 | 公开 |

> **数据真实性说明**：`load_predictions.actual_load_mw` 仅由真实数据源写入。
> 项目已移除所有"预测值+噪声伪造实际值"的逻辑；在接入真实实际负荷数据前，
> 准确性统计端点返回空数据而非伪造值。

### 5.3 认证

- JWT（access 30min / refresh 7天），密钥由环境变量 `AUTH_JWT_SECRET_KEY` 提供
- 中间件白名单：文档、健康检查、登录注册、天气当前值、系统状态公开，其余需认证
- RBAC：系统管理员/普通用户角色，路由级权限校验

---

## 六、使用与部署

### 6.1 一键启动（Windows）

```powershell
.\start.ps1
```

### 6.2 手动启动

```bash
# 后端（backend 目录）
cd backend
pip install -r requirements.txt
python -m uvicorn realtime_api.app:app --host 0.0.0.0 --port 8000 --reload

# 前端（frontend 目录）
cd frontend
npm install
npm run dev   # http://localhost:3000
```

### 6.3 环境变量（`.env`，参见 `.env.example`）

| 变量 | 说明 |
|------|------|
| `MYSQL_HOST/PORT/DATABASE/USER/PASSWORD` | MySQL 连接 |
| `AUTH_JWT_SECRET_KEY` | JWT 密钥（生产必须强随机） |
| `SYSTEM_ENVIRONMENT` | development / production |

### 6.4 测试

```bash
cd backend
pip install pytest pytest-cov pytest-asyncio pytest-mock
python -m pytest tests/
```

### 6.5 Docker 全栈

```bash
docker-compose up -d
# API: http://localhost:8000  Grafana: http://localhost:3000  Prometheus: http://localhost:9090
```

---

## 七、训练输出

- **模型权重**：`backend/models/models/{enhancedlstm,bigru,deeptcn,spatialtransformer}_best_model.pth`
- **真实指标**：`backend/models/models/final_results.json`（反归一化 MW 口径）
- **重算命令**：`cd backend && python scripts/recompute_final_metrics.py`
- **重训命令**：`cd backend && python train_four_models.py`

---

## 八、已知限制

- 预测准确性统计依赖真实 `actual_load_mw` 数据接入（当前空缺）
- 登录页 HUD 为纯装饰演示动画（已标注 DEMO）
- 本机 Windows 下 coverage 统计不可用（coverage 库环境问题），CI（Ubuntu）正常
