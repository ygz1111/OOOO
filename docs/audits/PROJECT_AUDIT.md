# 智能电网预测系统项目审计与上下文

> 资料迁移说明（2026-10-06）：本报告由根目录迁至 `docs/audits/PROJECT_AUDIT.md`；论文配套 `THESIS_*.md` 已归入 `Word/materials/`，保留的临时验收证据已归入 `docs/evidence/`。下文路径和目录树记录审计当时的结构，保留其历史表述；当前目录入口见 [项目文档索引](../README.md)。

> 审计日期：2026-09-19  
> 审计方式：对当前工作区进行递归静态检查，并交叉阅读前端路由、页面、API 封装、后端路由、服务、数据库脚本、模型资产、配置、测试、日志、启动脚本、Docker 与 Git 状态。  
> 约束：本次未修改源代码、未安装或升级依赖、未启动服务、未执行数据库迁移、未调用会写库的 HTTP 接口、未训练模型、未运行完整测试、未进行任何 Git 写操作。现有 `GET` 请求也可能记录访问日志或持久化气象/系统指标，因此没有通过在线调用验证接口。除本文件外，没有创建或修改项目文件。

## 1. 项目概述

这是一个面向 ISO New England（ISO-NE，新英格兰独立系统运营商）区域的智能电网预测与运行态势展示系统。它不是单纯的数据可视化页面，也不是只包含训练脚本的算法项目，而是由以下部分构成的全栈毕业设计：

- React 单页应用：登录、仪表盘、负荷预测、电价预测、光伏预测、气象监控、历史分析、运行态势和系统状态。
- FastAPI 服务：认证、实时数据接入、模型推理、历史回测、指标分析、监控和数据库读写。
- TensorFlow 模型：24 小时负荷点预测、24 小时电价 P10/P50/P90 分位数预测、24 小时光伏预测。
- MySQL：用户、权限、会话、气象、预测、实际负荷、监控、日志等持久化数据。
- ISO-NE 与 Open-Meteo：生产模式下的真实电力市场和气象数据来源。
- 训练与论文资产：`MMXX/`、`THESIS_*.md`、图表、实验指标和原始 Excel 数据。

当前项目更准确的定位是“可在已配置开发机上运行的研究/演示型预测平台”。它已经具有较完整的前后端、数据库和模型闭环，但还不是可从干净仓库稳定复现、可直接生产部署的成熟系统。

## 2. 项目实际用途

### 2.1 解决的问题

系统把区域历史负荷、电价、表后光伏和气象数据整理成模型输入，生成未来 24 小时预测，并提供历史真实值对比、误差诊断、漂移检查和运行风险提示，帮助用户观察电力系统供需变化。

### 2.2 目标用户

- 电网调度或运行分析人员：查看负荷、光伏、净负荷、爬坡和规则型风险提示。
- 电力市场/数据分析人员：查看电价分位数预测、历史误差和趋势。
- 毕业设计答辩与科研演示用户：展示数据采集、深度学习推理、前后端交互和实验结果。

代码目前并未达到真实调度控制系统的安全性、可用性和审计要求，不能把它表述为能够直接下发调度指令的生产系统。

### 2.3 主要业务流程

用户注册/登录 → JWT 鉴权 → 进入仪表盘 → 后端从 ISO-NE 与 Open-Meteo 获取并整理特征 → TensorFlow 模型推理 → 组合负荷、光伏与净负荷 → 返回图表/指标 → MySQL 保存预测、实际值、指标与访问日志 → 历史分析页面进行回测和诊断。

### 2.4 完成度判断

按“本科毕业设计可演示系统”口径，完成度约为 **80%**：核心页面、三类预测、数据库、登录、真实外部数据、历史回测、实验指标和监控均已存在；主要缺口集中在干净环境可复现、认证闭环、权限执行、测试证据、部署一致性和文档冻结，而不是缺少主业务页面。

## 3. 技术栈

### 3.1 前端

| 类别 | 实际技术 | 证据 |
|---|---|---|
| UI 框架 | React 18.2 | `frontend/package.json` |
| 语言 | TypeScript 5.2，严格模式 | `frontend/tsconfig.json` |
| 构建工具 | Vite 4.5 | `frontend/vite.config.ts` |
| 路由 | React Router 6.14 | `frontend/src/App.tsx` |
| 请求 | Axios 1.6，自定义刷新令牌与 GET 去重 | `frontend/src/services/api.ts` |
| 图表 | Recharts 2.8 | 页面与图表组件 |
| 样式 | Tailwind CSS 3.3 + 自定义 CSS | `tailwind.config.js`、`src/index.css` |
| 图标 | lucide-react | `package.json` |
| 状态 | React Context（`AuthContext`、`ApiContext`） | `frontend/src/contexts/` |
| 单元测试 | Vitest + jsdom | `package.json`、`src/__tests__/shared.test.ts` |
| 浏览器测试依赖 | Playwright 已安装，但没有正式 `test:e2e` 脚本 | `package.json` |

没有 Redux、Pinia、Vue、Next.js、WebSocket、SSE 或文件上传前端流程。

### 3.2 后端

| 类别 | 实际技术 | 证据 |
|---|---|---|
| 语言/版本 | Python 3.10–3.12 | `backend/pyproject.toml` |
| Web 框架 | FastAPI + Uvicorn | `backend/realtime_api/app.py` |
| 数据校验 | Pydantic 2 | `backend/realtime_api/schemas/` |
| 数据处理 | pandas、NumPy、PyArrow、scikit-learn | `backend/requirements.txt` |
| 深度学习 | TensorFlow 2.16.1、Keras 3.3.3 | 配置和模型服务 |
| 同步数据库 | mysql-connector-python 连接池 | `backend/realtime_api/database.py`、`crud/core.py` |
| 异步数据库/认证 | SQLAlchemy 2 + aiomysql | `database.py`、`crud/auth_crud.py` |
| 鉴权 | HS256 JWT、bcrypt | `auth/middleware.py`、`crud/auth_crud.py` |
| 监控 | psutil、Prometheus client、Grafana 配置 | `monitoring_service.py`、`docker/` |
| 缓存/健康检查 | Redis 客户端 | `health_check.py`、`docker-compose.yml` |

后端入口是 `backend/realtime_api/app.py`。应用生命周期依次初始化数据库、服务容器、TensorFlow 模型和后台任务；路由集中在 `backend/realtime_api/routers/`；业务编排集中在 `services/`；持久化在 `crud/` 和 `database.py`；请求鉴权和访问日志在 `auth/middleware.py`。

### 3.3 数据库与文件存储

- 主数据库：MySQL 8；本机 `.env` 当前包含所需 MySQL 配置（报告不打印值）。
- Redis：Docker 和健康检查已配置；主预测请求的短期缓存主要仍是进程内缓存，未发现完整的 Redis 业务缓存读写闭环。
- 本地文件：Parquet、JSON、CSV、Excel、H5 权重和图片。模型推理依赖 `backend/models/tf_assets/` 下的本地冻结资产。
- 没有 MongoDB、Elasticsearch、SQLite 或用户文件上传存储。

### 3.4 AI / 算法

项目明确存在真实的深度学习模块，而不是把普通规则包装成 AI：

- `tf_load_split_v1`：BiGRU-GRU，168 小时历史窗口预测未来 24 小时负荷。
- `tf_price_split_v1`：BiGRU-GRU Quantile，168 小时历史窗口预测未来 24 小时 P10/P50/P90 电价。
- `pv_v2`：因果 TCN + GRU 编码器 + cross-attention + GRU 解码器，96 小时窗口预测未来 24 小时表后光伏。
- 运行态势的“风险”是规则推导结果，不是独立 AI 风险模型。
- 漂移检查是历史 MAPE 分段比较，不是 PSI 模型；配置中的 PSI 阈值没有成为当前该接口的实现。

## 4. 项目目录结构

```text
OOOOOO/
├─ frontend/                    React + TypeScript + Vite 前端
│  ├─ src/pages/                正式页面及历史分析子页
│  ├─ src/components/           布局、图表、登录视觉与通用组件
│  ├─ src/contexts/             认证和共享 API 状态
│  ├─ src/services/api.ts       HTTP、令牌刷新、请求去重
│  ├─ src/types/                API 与页面类型
│  └─ src/__tests__/            少量共享工具单元测试
├─ backend/
│  ├─ realtime_api/app.py       FastAPI 入口和生命周期
│  ├─ realtime_api/routers/     auth/prediction/weather/system/generation/price/analytics
│  ├─ realtime_api/services/    预测编排、概览、运行态势
│  ├─ realtime_api/crud/        MySQL CRUD 和认证 CRUD
│  ├─ realtime_api/auth/        JWT 中间件、依赖和 RBAC 辅助
│  ├─ realtime_api/tasks/       周期性指标、预警和实际负荷同步
│  ├─ models/tf_assets/         当前推理所需权重、scaler、尾部特征
│  ├─ scripts/                  迁移、数据拉取、资产准备与诊断脚本
│  ├─ tests/                    后端单元/集成/模型/API 测试
│  ├─ config/app_config.yaml    应用与模型配置
│  └─ pyproject.toml            Python 包、工具与测试配置
├─ docker/                      MySQL 初始化、Prometheus、Grafana、Dockerfile
├─ docker-compose.yml           API、MySQL、Redis、监控栈（不含前端）
├─ MMXX/                        正式模型训练工程、原始数据、运行结果和图表
├─ solar_data/                  较早的光伏采集/实验数据，不是在线主链
├─ processed/                   大型处理后数据，未纳入 Git
├─ docs/                        部署、训练和问题记录
├─ Word/                        论文文档资产
├─ THESIS_*.md                  论文事实、提纲、图表和实验记录
├─ logs/                        本机运行日志
├─ start.ps1 / stop.ps1         Windows 本地启停脚本
├─ .env / .env.example          本机秘密配置与示例
└─ backups/ 等                  备份、临时或工具性内容，不在正式调用链
```

体积较大的目录包括 `processed/`、`solar_data/`、`frontend/node_modules/`、`MMXX/`、临时缓存等；它们不能等同于需要全部提交的运行源码。

## 5. 前端架构

### 5.1 入口、路由和布局

- 入口：`frontend/src/main.tsx`，挂载 `BrowserRouter`。
- 根组件：`frontend/src/App.tsx`，先挂载 `AuthProvider`。
- 公开路由：`/login`，已登录用户会被送回 `/`。
- 受保护路由：其余页面经过 `ProtectedRoute`，再挂载 `ApiProvider`、`Header`、`Sidebar` 和错误边界。
- 页面采用懒加载；未知路径显示 404。
- `AuthContext` 在 localStorage 或 sessionStorage 中保存访问/刷新令牌和用户信息；`api.ts` 在 401 时尝试单次刷新并重放请求。
- `ApiContext` 首次并行加载预测和系统状态，再加载气象；初始失败时约 35 秒重试，正常后约 5 分钟轮询。

### 5.2 正式页面

| 页面 | 文件 / 路由 | 主要用途与 API | 可用性判断 |
|---|---|---|---|
| 登录/注册 | `pages/Login.tsx` `/login` | `/api/auth/login`、`/register`，并显示公开气象/状态 | 账号密码流程真实；预览 HUD、生物识别为明确 Demo |
| 综合仪表盘 | `pages/Dashboard.tsx` `/` | 预测、当前气象、系统状态、`/prediction/overview` | 正式功能，依赖外部数据和模型就绪 |
| 负荷预测 | `pages/LoadForecast.tsx` `/load-forecast` | `/prediction/load`、`/prediction/overview`，24h 图表/表格/CSV | 正式功能 |
| 电价预测 | `pages/PriceForecast.tsx` `/price-forecast` | `/price/forecast`、`/price/backtest` | 正式功能 |
| 气象监控 | `pages/WeatherMonitor.tsx` `/weather-monitor` | `/weather/current`，六城市卡片和地图 | 正式功能 |
| 光伏预测 | `pages/SolarGeneration.tsx` `/solar-generation` | `/solar-generation`、`/model-info`、历史回测 | 正式功能；首次回测可能较慢 |
| 系统状态 | `pages/SystemStatus.tsx` `/system-status` | `/system/status`，模型与推理统计 | 正式功能 |
| 历史分析 | `pages/HistoricalAnalysis.tsx` `/historical-analysis` | 历史、准确率、模型对比、趋势、误差、漂移、日期回测 | 正式功能，但依赖数据库积累的预测/实际值 |
| 运行态势 | `pages/OperationSituation.tsx` `/operation-situation` | `/analytics/operations/situation`、小时误差、特征敏感度 | 正式页面；风险是规则结果，敏感度不是实时样本解释 |

没有已路由的文件上传页、WebSocket 页或 SSE 页。Git 状态中的 `WindGeneration.tsx` 已删除且路由中不存在，风电不是当前正式功能。

### 5.3 Demo、Mock 与视觉数据

- `components/cyber/GridForecastPreviewHUD.tsx` 使用 `Math.random()` 生成登录页曲线，且页面已标明“模拟/演示”；其中 `2.4ms / batch` 是硬编码视觉文案。
- `components/cyber/BiometricScannerModal.tsx` 通过定时器改变进度，没有摄像头、WebAuthn 或后端生物识别；文件内明确提示使用账号密码登录。
- `components/cyber/CyberLoginForm.tsx` 的验证码由前端生成、前端显示并只在前端比较，不能作为服务器安全控制。
- 背景粒子和拓扑随机值属于装饰动画，不是业务数据。

## 6. 后端架构

### 6.1 启动和生命周期

`backend/realtime_api/app.py` 创建 FastAPI 应用。生命周期大致为：

1. 初始化 MySQL 数据库层。
2. `services/container.py:init_services()` 加载 Open-Meteo、辅助特征对象和当前 TensorFlow 模型。
3. 在 `strict_startup: true` 下，选中模型资产缺失会阻止启动。
4. 启动后台任务：5 分钟系统指标、5 分钟性能预警、60 分钟 ISO-NE 最近 14 天实际负荷同步。
5. 挂载认证/访问日志中间件、超时处理、CORS、Prometheus 和各路由。

### 6.2 主要模块

- `routers/`：HTTP 参数、响应和异常映射。
- `services/prediction_pipeline.py`：统一负荷/电价/PV 推理与净负荷组装。
- `tf_realtime_feature_provider.py`：拉取 ISO-NE/Open-Meteo，并构造模型严格要求的实时窗口。
- `tf_split_service.py`：当前独立负荷/电价模型加载和推理。
- `tf_pv_v2_service.py`：当前 PV v2 加载和推理。
- `services/prediction_insight.py`：仪表盘历史+未来概览。
- `services/operation_situation.py`：净负荷、爬坡、规则风险和特征组敏感度。
- `openmeteo_client.py`：六站点气象、限速与进程内缓存。
- `crud/core.py`：气象、预测、性能、日志、实际负荷等同步 CRUD。
- `crud/auth_crud.py`：用户、密码、JWT 和会话的异步 SQLAlchemy CRUD。
- `auth/middleware.py`：Bearer JWT 校验和 API 访问日志。
- `tasks/background.py`：系统指标、告警和实际负荷同步。
- `monitoring_service.py`：内存监控对象；存在“WebSocket”注释和订阅者结构，但没有实际 WebSocket 路由或广播实现。

### 6.3 主要 API

| 分组 | HTTP 与路径 | 数据/服务 | 前端使用 |
|---|---|---|---|
| 认证 | `POST /api/auth/register`、`login`、`refresh`、`logout`、`logout-all`、`change-password` | SQLAlchemy、bcrypt、JWT、MySQL | 登录/注册/自动刷新/退出；其余部分未提供完整 UI |
| 认证查询 | `GET /api/auth/me`、`sessions`、`login-history`、`health`；`DELETE /session/{id}` | 用户、会话和登录历史 | 当前页面基本未使用会话管理 UI |
| 负荷 | `POST /api/prediction/load`、`batch` | 实时特征 + TensorFlow | 负荷页/仪表盘；batch 未见正式页面调用 |
| 负荷历史 | `GET /api/prediction/history`、`overview` | MySQL、ISO-NE 实际值、预测服务 | 历史分析、仪表盘、负荷页 |
| 气象 | `GET /api/weather/current`、`history` | Open-Meteo、MySQL | 气象页使用 current；history 无主要页面调用 |
| 光伏 | `GET /api/solar-generation`、`model-info` | PV v2、实时/归档气象、ISO-NE PV | 光伏页 |
| 电价 | `GET /api/price/forecast`、`backtest`、`model-info` | split price 模型、ISO-NE LMP | 电价页 |
| 系统 | `GET /api/system/status`、`metrics` | 健康检查、模型运行统计、MySQL/Redis | 状态页和登录页 |
| 健康 | `GET /api/health`、`liveness`、`readiness` | 应用与依赖状态 | 部署/诊断 |
| 运行分析 | `GET /api/analytics/operations/situation`、`feature-sensitivity`、`diagnostics/hourly-errors` | 当前预测、历史误差、模型遮蔽计算 | 运行态势页 |
| 历史分析 | `GET /api/analytics/backtest/date`、`accuracy/stats`、`accuracy/recent`、`drift/check`、`comparison/models`、`temporal/trends`、`error/distribution` | MySQL、ISO-NE、Open-Meteo archive、模型 | 历史分析各标签页 |
| 辅助分析 | `GET /api/analytics/quality/stats`、`patterns/load`、`report/comprehensive`、`dashboard/metrics`、`prediction-vs-actual`；`POST quality/validate` | 监控/CRUD/聚合 | 多数未见当前正式页面调用 |
| 监控 | `GET /metrics`、`GET /` | Prometheus/应用说明 | 运维使用 |

除公开路径外，业务 API 由 JWT 中间件保护。当前主要是“已登录/未登录”二元控制，RBAC 表和辅助函数存在，但大多数业务路由没有按角色/权限执行授权依赖。

## 7. 数据库架构

`docker/init-db.sql` 是当前 MySQL 初始化脚本，共定义 **17 张表、6 个视图**。

### 7.1 业务与监控表

- 数据：`weather_data`、`load_predictions`、`actual_load_data`、`model_performance`。
- API/操作审计：`api_request_logs`、`api_access_logs`、`operation_logs`。
- 认证/RBAC：`users`、`roles`、`permissions`、`user_roles`、`role_permissions`、`login_histories`、`user_sessions`。
- 监控：`system_metrics`、`cache_performance`、`performance_alerts`。

### 7.2 视图

`latest_weather_data`、`today_predictions`、`system_health`、`user_permissions_view`、`active_sessions_view`、`login_stats_view`。

### 7.3 初始化和访问方式

- Docker 首次启动通过 `/docker-entrypoint-initdb.d/init.sql` 初始化。
- 本机 `start.ps1` 每次启动前执行 `backend/scripts/migrate.py`；该脚本会建表/视图、初始化 RBAC，并移除旧的风电列，因此启动脚本不是纯只读检查。
- 领域数据使用 mysql-connector 连接池，阻塞调用被放入线程执行。
- 认证使用 SQLAlchemy 异步会话和 aiomysql。
- 初始化 SQL 含少量示例气象记录，它们是种子/Demo 数据，不应当作在线观测值。

## 8. AI / 算法模块

### 8.1 当前生产模型

由 `backend/config/app_config.yaml` 确认：`load_backend=tf_split_v1`、`pv_backend=tf_pv`、`inference_mode=live`、`strict_startup=true`。

| 模型 | 输入/输出 | 特征与规模 | 冻结测试结果 |
|---|---|---|---|
| 负荷 `tf_load_split_v1` | 168h → 24h 点预测 | 21 个历史特征、17 个未来特征；约 422,333 参数 | MAE 305.40 MW、RMSE 476.14 MW、MAPE 1.922%、R² 0.97739 |
| 电价 `tf_price_split_v1` | 168h → 24h P10/P50/P90 | 26 个历史特征、17 个未来特征；约 425,897 参数 | P50 MAE 13.266 USD/MWh、RMSE 26.494；区间覆盖率 66.93% |
| 光伏 `pv_v2` | 96h → 24h 点预测 | 28 个历史特征、27 个未来特征；246,017 参数 | 全时段 MAE 236.1834 MW、RMSE 474.25 MW；日照 WAPE 17.0532% |

负荷/电价指标来自 `MMXX/smart-grid/runs/tf_split_v1/metrics.json`，光伏指标来自 `backend/models/tf_assets/pv_v2/metadata.json`。这些是冻结测试集结果，不等同于当前在线每小时表现。电价 66.93% 覆盖率低于名义 80%，说明区间仍需校准。

### 8.2 推理链

生产模式由 `TFRealtimeFeatureProvider` 获取 ISO-NE 系统负荷、日前需求、日前/实时 LMP、估算表后光伏以及 Open-Meteo 气象，构造严格列顺序的历史和未来窗口。`prediction_pipeline.py` 分别调用负荷/电价与 PV 服务，按时间对齐后计算 `net_load = load - pv`。

### 8.3 历史回测的解释边界

日期回测会用 Open-Meteo Archive 的历史观测气象重建过去输入，再与 ISO-NE 实际值对比。这属于“回顾性验证”，不是严格模拟当日当时能够获得的历史天气预报，论文中必须注明，否则会高估真实滚动预测条件下的可用性。

## 9. 核心功能

1. 未来 24 小时区域电力负荷预测，并显示历史实际值与历史预测误差。
2. 未来 24 小时电价 P10/P50/P90 概率预测及指定日期历史回测。
3. 未来 24 小时表后光伏发电预测、模型信息和历史回测。
4. 负荷、光伏与净负荷综合运行态势，以及峰谷、爬坡和规则型风险提示。
5. 历史预测准确率、误差分布、趋势、模型对比和漂移检查。

辅助功能包括登录/注册、气象监控、系统健康、Prometheus/Grafana 配置、CSV 导出、API/登录日志和后台数据同步。

## 10. 核心业务流程

### 10.1 用户认证

注册/登录表单 → `AuthContext` → `apiService.login/register` → `/api/auth/*` → `AuthCRUD` → MySQL 用户/登录历史/会话 → JWT 返回前端 → 前端存储令牌 → 受保护页面。

### 10.2 实时综合预测

用户进入仪表盘/负荷页 → `ApiContext` 或页面服务方法 → `POST /api/prediction/load` 或 `GET /api/prediction/overview` → prediction router → `dispatch_prediction`/prediction insight → `TFRealtimeFeatureProvider` → ISO-NE + Open-Meteo → `TFSplitService` + `TFPVV2Service` → 负荷/PV/净负荷响应 → Recharts/指标卡展示。

### 10.3 电价预测

电价页 → `getPriceForecast()` → `GET /api/price/forecast` → price router → split price service → P10/P50/P90 → 区间图表和表格。

### 10.4 历史验证

用户选择日期 → backtest API → ISO-NE 历史实际值 + Open-Meteo Archive → 用当前冻结模型重新推理 → 计算 MAE/RMSE/MAPE 等 → 页面图表/指标。此流程不重训模型。

### 10.5 后台闭环

应用启动 → 每 60 分钟同步 ISO-NE 最近 14 天实际负荷 → 回填 `actual_load_data`/预测实际值 → 历史分析读取数据库 → 形成在线误差和漂移判断。另有每 5 分钟的系统指标和阈值预警写库。

## 11. 前后端调用链

| 前端入口 | 前端方法 | HTTP | 后端入口 | 服务/数据 | 页面输出 |
|---|---|---|---|---|---|
| `Dashboard.tsx` | `predictLoad`、`getLoadOverview` | `POST /prediction/load`、`GET /prediction/overview` | `routers/prediction.py` | pipeline、ISO-NE、Open-Meteo、TF 模型、MySQL | 当前/未来负荷、PV、净负荷、历史对比 |
| `LoadForecast.tsx` | 同上 | 同上 | prediction router | insight/pipeline | 24h 曲线、表格、CSV |
| `PriceForecast.tsx` | `getPriceForecast`、`getPriceBacktest` | `/price/forecast`、`/price/backtest` | `routers/price.py` | split price 模型、ISO-NE LMP | 分位数区间、回测误差 |
| `SolarGeneration.tsx` | `getSolarGeneration` | `/solar-generation` | `routers/generation.py` | PV v2、气象、ISO-NE PV | 未来 PV、历史回测、模型信息 |
| `WeatherMonitor.tsx` | `getCurrentWeather` | `/weather/current` | `routers/weather.py` | Open-Meteo + WeatherCRUD | 六站点气象 |
| `HistoricalAnalysis.tsx` | history/accuracy/drift/backtest 等 | `/prediction/history`、`/analytics/*` | analytics/prediction routers | MySQL、archive API、统计函数 | 历史、误差、趋势、漂移 |
| `OperationSituation.tsx` | situation/diagnostics/sensitivity | `/analytics/operations/*` | analytics router | prediction pipeline、DB、遮蔽敏感度 | 运行态势、规则风险、诊断 |
| `SystemStatus.tsx` | `getSystemStatus` | `/system/status` | `routers/system.py` | health check、runtime stats | 依赖和模型状态 |

## 12. 数据来源

| 数据类型 | 来源 | 对应代码/资产 | 使用位置 | 真实性 |
|---|---|---|---|---|
| 系统负荷、日前需求 | ISO-NE Web Services | `tf_realtime_feature_provider.py`、`utils/iso_ne.py` | 负荷特征、实际值、回测 | 官方真实数据，需账号 |
| 日前/实时 LMP | ISO-NE | 同上 | 电价特征、标签和回测 | 官方真实数据 |
| 表后光伏估算 | ISO-NE | 同上 | PV 历史输入/真实对比 | 官方估算数据，不是逐电站实测 |
| 当前/预报气象 | Open-Meteo Forecast API | `openmeteo_client.py` | 实时预测、气象页 | 第三方真实预报 |
| 历史气象 | Open-Meteo Archive API | 历史回测服务 | 日期回测 | 回顾性历史观测/再分析性质数据 |
| 在线历史 | MySQL | `crud/`、`docker/init-db.sql` | 历史分析、日志、用户 | 运行中真实积累；含初始化示例行 |
| 模型输入资产 | Parquet/JSON/H5 | `backend/models/tf_assets/` | 模型加载、scaler、验收 | 真实冻结训练产物，但当前未跟踪 |
| 训练原始数据/结果 | Excel/CSV/JSON/H5 | `MMXX/`、`solar_data/` | 离线训练和论文 | 混合研究资产；不是在线 API |
| 登录页预览曲线 | `Math.random()` | `GridForecastPreviewHUD.tsx` | 登录页 | 明确 Demo/模拟 |
| 生物识别 | 定时器状态 | `BiometricScannerModal.tsx` | 登录页弹窗 | Demo，不是真实认证 |
| 验证码 | 前端随机数 | `CyberLoginForm.tsx` | 登录表单 | 仅前端交互，不是安全验证码 |
| 运行风险 | 规则计算 | `services/operation_situation.py` | 运行态势 | 派生规则结果，不是外部真实事件 |

当前没有用户上传数据、爬虫主链或 LLM/NLP 数据源。EIA 只在可选脚本/示例配置中出现，不是当前 live 推理的必需数据源。

## 13. 第三方服务

- ISO-NE Web Services：需要 `ISO_NE_USERNAME`、`ISO_NE_PASSWORD`；当前 `.env` 已配置，但本报告不暴露值。
- Open-Meteo Forecast/Archive：无需 API Key；当前六个代表城市为 Boston、Manchester、Hartford、Portland、Providence、Burlington。
- MySQL 8：主持久化依赖。
- Redis：Docker/健康检查依赖；当前没有证据表明所有配置中的缓存策略已落为 Redis 业务缓存。
- Prometheus、Grafana、node-exporter、cAdvisor：Docker 监控栈。

## 14. 项目启动方式

### 14.1 启动前准备

- Windows PowerShell、Conda、npm。
- Python 3.10–3.12；项目固定 TensorFlow 2.16.1/Keras 3.3.3。
- 当前脚本要求名为 `smartgrid-tf` 的 Conda 环境。
- Node 文档只写了较低要求，但当前锁文件中的部分开发依赖要求 Node 22.13+/24；本机检测到 Node 24.19.0、npm 11.17.0。
- MySQL 必须可连接且 `.env` 中 `MYSQL_*` 配置有效。
- live 模式需要 ISO-NE 凭据和外网访问 Open-Meteo/ISO-NE。
- 必须存在 split load/price 与 pv_v2 的权重、scaler/metadata 和特征尾部资产。

### 14.2 推荐的当前本机入口

在项目根目录执行 `./start.ps1`。脚本会：验证模型资产 → 执行幂等数据库迁移 → 只清理属于本项目的 8000/3000 端口进程 → 启动 Uvicorn → 启动 Vite → 检查前后端。

浏览器地址：`http://localhost:3000`；后端：`http://localhost:8000`；OpenAPI：`http://localhost:8000/docs`。

注意：启动脚本会修改数据库并启停进程，本次审计没有执行。审计时 3000、8000、3306、6379 均未发现监听进程。

### 14.3 Docker 现状

根 `docker-compose.yml` 可编排 API、MySQL、Redis、Prometheus、Grafana 等，但**没有前端服务**。Grafana占用宿主机 3000 端口，和本机 Vite 默认端口冲突，因此不能直接把“完整 Compose + 本机前端”当成无冲突的一键全栈方案。

## 15. 当前正式功能

- JWT 账号注册、登录、刷新和受保护路由。
- live 模式的 24h 负荷、电价和 PV 预测。
- 负荷/PV/净负荷综合展示。
- ISO-NE 实际负荷自动同步与预测对比。
- 指定日期的负荷、电价、PV 历史回测。
- 历史准确率、小时误差、趋势、分布和漂移检查。
- 六站点气象监控。
- 系统/模型状态、Prometheus 指标和后台性能预警。
- CSV 导出、错误边界、加载状态、响应式菜单。

## 16. 未完成功能

- RBAC 数据结构和辅助函数存在，但业务 API 基本没有按角色/权限强制授权。
- WebSocket 在监控服务中只有注释/占位，没有真实路由和前端订阅。
- Docker 没有前端镜像/服务，不能完整一键部署 UI。
- 前端没有会话管理、改密、登录历史等完整账户管理界面。
- 配置宣称的 Redis 缓存策略、备份计划和限流没有形成已验证的完整实现。
- Playwright 依赖存在，但缺少正式 E2E 脚本和受版本控制的浏览器测试套件。
- 论文实验清单仍记录待办：负荷/电价基线固化、预测明细与图、训练环境、典型日案例、动态回测模型哈希与 JSON 证据。

## 17. Mock / Demo / 测试功能

- 登录页预测 HUD、拓扑和部分延迟数值：模拟展示。
- 生物识别弹窗：纯视觉 Demo。
- 前端验证码：仅客户端交互，不是安全控制。
- `inference_mode=demo` 分支：冻结样本验收模式；当前正式配置为 `live`。
- 初始化 SQL 的样例气象：种子数据。
- `calculate_demo_feature_sensitivity()`：对冻结验收窗口做真实模型遮蔽计算，但输入不是用户当前实时预测样本；当前 UI 标签容易让人误认为实时解释。
- `frontend/capture_loaded.js` 和页面 PNG：临时截图/验收资产，不是正式功能。

## 18. 历史遗留代码

- `tf_v2`：旧的负荷+电价联合模型仍可由配置选择，但当前生产选择是 `tf_split_v1`。
- `tf_pv_service.py`/PV v1：旧光伏服务；当前容器加载 `tf_pv_v2_service.py`。
- 风电页面、估算器、数据库列和相关模型文件处于删除状态，当前路由/迁移均表明风电已退出正式功能。
- `solar_data/`：较早光伏数据收集与实验目录；README 仍称 PV v1 为当前版本，与实际配置不一致。
- `docker/config/init-db.sql` 和旧 `docker/docker-compose.yml` 体现 PostgreSQL/TimescaleDB 或拆分微服务方案；当前根 Compose 使用 MySQL。
- 旧高可用 Compose 仍引用已删除的 `docker/services/model-inference/Dockerfile`，且环境变量名与当前后端不一致，不能视为有效部署方案。
- `HistoricalLoadProvider`、`FeatureGenerator`、`NormalizationAdapter`、`WeatherDataValidator` 中部分逻辑服务于旧管线或辅助/冷启动，不是当前实时 TensorFlow 特征主链。
- `backups/`、临时诊断脚本和缓存目录不在正式运行调用链，不能据其文件存在声称功能已上线。

## 19. 当前发现的 Bug

### 优先级结论

本次静态审计**没有发现可证实的 P0**。发现 3 组 P1，以及若干 P2/P3。

### P1-1：注销与会话撤销链路失效

- 登录时 `routers/auth.py` 生成 UUID `session_id`，并和 token 一起写入 `user_sessions`。
- `/logout` 却把 `Authorization` 中的完整 access token 当作 `session_id` 传给 `AuthCRUD.revoke_session()`；数据库按 UUID 字段匹配，通常撤销不到记录。
- `/logout-all` 同样把 access token 当作 `except_session_id`，导致“保留当前会话”的语义错误。
- 更严重的是 `auth/middleware.py:_authenticate_request()` 只校验 JWT 签名、类型和过期时间，没有查询会话是否撤销、用户是否仍激活；即使数据库会话成功撤销，原 access token 仍可继续使用到过期。
- 影响：退出登录/注销会话不形成服务器端安全闭环，丢失令牌无法立即失效。

### P1-2：干净克隆无法复现当前严格启动

- `backend/config/app_config.yaml` 开启 `strict_startup: true`，启动必须加载 split 与 pv_v2 资产。
- 当前 `backend/models/tf_assets/` 和 `backend/models/tensorflow_load/` 在 Git 中属于未跟踪内容；`MMXX/` 训练工程和当前多个新服务/路由也未跟踪。
- 影响：当前机器有资产并有近期成功日志，不代表答辩机或新克隆能启动。若按当前提交状态交付，会缺少核心代码/模型资产。

### P1-3：Docker 全栈部署路径不完整且端口冲突

- 根 Compose 没有前端服务。
- Grafana 映射宿主机 `3000:3000`，而 Vite 本地前端默认也是 3000。
- Dockerfile/Compose 依赖本地模型和数据目录；干净仓库缺资产时 strict startup 会失败。
- 影响：按“Docker 一键部署整套系统”演示时会直接遇到 UI 缺失或端口冲突。

### P2 问题

1. **JWT 过期配置漂移**：`app_config.yaml` 写 30 分钟，`crud/auth_crud.py` 实际常量为 720 分钟，接口返回 43200 秒；配置项未生效。
2. **RBAC 未落地到业务路由**：角色/权限表和依赖函数存在，但普通已登录用户原则上可访问全部受保护预测/分析接口。
3. **会话 token 明文存库**：`user_sessions.jwt_token` 和 `refresh_token` 保存完整 bearer token；数据库泄露会直接暴露有效凭据。
4. **无有效登录限流**：配置有 `rate_limit_per_minute`，未发现中间件实施。连续 5 次失败会锁定已知账号，但没有明确自动解锁/管理 UI，可能被用于账号拒绝服务。
5. **验证码不是服务端验证码**：攻击者可绕过前端直接调用登录接口。
6. **特征敏感度标签不准确**：`operation_situation.py` 调用 `calculate_demo_feature_sensitivity`，使用冻结窗口而非当前 live 输入，但页面称“当前负荷预测”的敏感度。
7. **前后端超时不一致**：后端把光伏/电价回测等归入最长 120 秒请求，前端光伏和电价预测主要使用 60 秒超时；冷缓存/外部 API 较慢时客户端可能先失败。
8. **GET 有写副作用**：访问中间件会记录请求；气象 current 和系统 status 也可异步写库。接口语义和测试隔离需明确。
9. **文档版本漂移**：部分 `docs/README.md`、部署文档和 `solar_data/README.md` 仍描述 PV v1、WebSocket 或不存在的 `test:e2e`。
10. **默认部署凭据不安全**：Compose 为 MySQL/Grafana 提供 `changeme`/固定管理员密码兜底；旧 Compose 还有更多硬编码口令。
11. **数据库 URL 对特殊字符脆弱**：SQLAlchemy URL 由字符串拼接用户名/密码，未显式 URL 编码，复杂密码可能导致连接解析失败。

### P3 问题

- `tasks/background.py:start_background_tasks()` 重复打印同一条启动日志。
- 部分已初始化服务在当前正式推理主链中不使用，增加理解和维护成本。
- 多个大页面/服务承担数据获取、变换、展示或兼容逻辑，后续修改容易扩大回归面。
- `.env.example` 没有覆盖代码支持的所有关键开关，如 CORS、TF 禁用、SSL 等，部署人员容易误配。
- Python 依赖在 `pyproject.toml` 与 `requirements.txt` 中存在版本下界差异，Node 运行范围也没有通过 `engines` 固化。

## 20. 技术债

- **仓库边界不清**：大量当前功能是未跟踪文件，历史删除也未形成提交；无法由 Git 明确回答“正式版本是什么”。
- **配置有多套事实源**：YAML、环境变量、代码常量、Compose 默认值和文档之间存在漂移。
- **新旧管线并存**：tf_v2/split、PV v1/v2、旧微服务/当前单体、旧风电残留共同增加判断成本。
- **测试证据不完整**：代码中约有 205 个后端测试函数，但本次没有执行；现有 `e2e_out.txt` 只证明两个选定测试通过且带 SQLAlchemy 清理警告。现有 `coverage.xml` 约为 9.59% 行覆盖，更像局部运行产物，不能作为全套覆盖率证明。
- **前端测试很薄**：仅约 15 个共享工具单元测试，页面、认证刷新、图表状态和关键用户流程缺少可靠测试。
- **缓存实现与配置不一致**：Open-Meteo、overview、situation 等主要使用进程内缓存；Redis 配置和监控存在，但业务缓存闭环不足。
- **可观测性有占位**：监控服务有 WebSocket 广播描述但无实际通道；配置中的部分指标/备份计划没有运行证据。
- **大型本地资产管理缺策略**：`processed/`、`MMXX/`、模型 H5、论文图片等应明确区分“源码必需、运行必需、训练可重建、论文归档”。

## 21. 安全问题

### 21.1 已确认风险

- P1 会话撤销失效，详见 19 节。
- P2 业务接口缺少角色级授权。
- P2 完整 access/refresh token 明文存库。
- P2 无服务端登录限流；账号锁定机制可能被滥用。
- P2 前端验证码不构成安全控制。
- P2 JWT 默认配置与实际有效期不一致，实际 access token 长达 12 小时。
- P2 Compose 有弱默认密码；生产部署若未覆盖会直接暴露风险。
- 浏览器令牌保存在 local/session storage；若未来出现 XSS，令牌容易被读取。当前 React 默认转义且未发现 `dangerouslySetInnerHTML`，但也未见 CSP 配置。

### 21.2 未发现的高风险点

- 没有文件上传，因此当前没有上传型路径穿越面。
- 核心 SQL 查询普遍使用参数绑定，静态检查未发现明确 SQL 注入点。
- 未发现把 `.env` 秘密值直接提交到本报告；`.env` 本身被 `.gitignore` 忽略。
- CORS 实际在 `app.py` 中默认限制本机前端来源；YAML 的 `cors_origins: ["*"]` 并不是当前实际中间件取值，但这种双配置本身容易误导。
- 未实现 Cookie 会话，当前 CSRF 不是主风险；Bearer token 泄露和 XSS 更值得关注。

## 22. 从本科毕业设计角度的完成度分析

### 22.1 已达到的工作量和亮点

- 有明确业务主题、8 个受保护页面和完整用户路径，不像简单课程 CRUD 作业。
- 有真实前后端交互、MySQL 数据库、JWT、外部 API 和后台任务。
- 有三个独立 TensorFlow 预测任务，包含概率电价预测和注意力 PV 架构。
- 有真实 ISO-NE/Open-Meteo 数据、冻结测试集指标、基线对比和大量训练/论文图表。
- 有历史回测、实际值回填、误差诊断、漂移检查和系统监控，具备系统性。
- 现有页面和 `MMXX` 图表足以支持较丰富的论文截图、系统架构图、功能结构图和业务流程图。
- 17 表/6 视图和 RBAC 关系足以制作 ER 图，但图中应区分“表已存在”和“业务已真正使用”。

### 22.2 答辩前仍缺的证据

- 一份从干净环境可执行的、与当前代码一致的部署说明和模型资产获取/校验方案。
- 把当前所有正式代码、迁移、模型元数据和必要资产纳入明确版本基线。
- 一次可复现的完整后端测试、前端构建/类型检查和关键浏览器流程报告。
- 修正会话撤销和权限执行后，再提供登录/退出/越权测试证据。
- 固化负荷、电价基线和预测明细；解释电价区间覆盖不足和历史气象回测边界。
- 论文中的模型版本、架构图、API、数据库和页面截图必须与当前 split + pv_v2 系统一致。
- 准备外部 API 不可用时的合规演示预案，且必须清楚标注 Demo 数据，不能伪装为实时数据。

### 22.3 总体判断

项目具备本科毕业设计所需的技术深度、功能广度和实验材料，核心问题不是“工作量不足”，而是工程基线和真实性叙述尚未完全收口。如果先解决 P1，并把测试与论文事实冻结，项目可以形成较有说服力的完整答辩作品。

## 23. 推荐的后续优化方向

按风险和答辩收益建议顺序如下；本节只记录方向，本次未执行任何修改。

1. **冻结可复现版本（第一优先）**：确定正式源码/模型/数据边界，处理未跟踪关键文件，给模型资产做清单、校验和和恢复说明；在干净目录验证启动。
2. **修复认证安全闭环**：让 JWT 携带或映射真实 session id；中间件检查用户/会话状态；正确实现 logout/logout-all；统一 token 有效期；补充认证回归测试。
3. **落实最小 RBAC**：至少区分 viewer/analyst/admin 对写操作、账户管理和敏感运维 API 的权限；前端角色选择不能只做装饰。
4. **统一部署入口**：决定“本机脚本”或“完整 Docker”哪个是答辩主路径；若保留 Compose，加入前端并解决 Grafana 端口、资产注入和弱默认密码。
5. **建立可信测试基线**：后端全套测试、前端 type-check/build/unit、关键浏览器路径；保存命令、环境、通过数、失败数和覆盖率，不沿用局部旧产物。
6. **收口页面真实性标签**：把冻结敏感度改名为验收样本敏感度；始终区分实时预测、回顾性回测、规则风险和登录页 Demo。
7. **冻结论文实验**：补齐基线、典型日、预测明细、模型哈希、环境版本和图表来源；专门讨论电价区间校准与 PV 高出力误差。
8. **清理配置和文档漂移**：在确认基线后统一 YAML、`.env.example`、Compose、代码常量和部署手册；明确 PV v2 是当前正式版本。
9. **第二阶段再做代码结构优化**：待功能和测试基线稳定后，才拆分大型页面/服务、隔离 legacy、统一缓存和监控实现，避免在答辩前无测试地大规模重构。

## 附录 A：Git 状态快照

- 当前分支：`main`。
- 相对 `origin/main`：本地领先 15 个提交。
- 工作区存在大量已修改、已删除和未跟踪文件；当前生产路由、模型服务、模型资产、训练工程和论文材料中相当一部分未跟踪。
- 最近提交为 `56b239b`（2026-08-13，24 小时负荷预测重构），此前提交涉及实际值合并、token 刷新、Windows 异步 DB 修复和 ISO-NE 实际负荷同步。
- `.env`、依赖目录、日志、处理后数据、备份和部分大数据已在 `.gitignore` 中排除；但运行必需模型资产没有形成可复现的版本/下载策略。
- 本次未执行 commit、push、pull、reset、checkout、clean 或 rebase。

## 附录 B：验证状态与限制

- 近期现有日志显示后端曾成功加载 TensorFlow 模型，并从 Open-Meteo 六站点取得有效数据；这只能证明当前机器近期运行过，不能替代本次独立启动验证。
- `e2e_out.txt` 显示两个选定 E2E 测试通过，同时出现 SQLAlchemy 连接回收和特征/scaler 警告；不能概括为“205 项全部通过”。
- 本次为遵守只读与不改数据库约束，没有启动应用，因为生命周期会迁移数据库并启动写库后台任务，请求中间件也会记录 API 访问。
- 因此，本文对调用关系、配置、数据来源和静态缺陷具有代码证据；对当前数据库内容、外部 API 可达性、全量测试通过率和真实浏览器交互不作未经运行验证的保证。
