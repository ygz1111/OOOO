# 毕业论文项目事实基线

> 核对日期：2026-09-12（Asia/Shanghai）  
> 项目目录：`D:\GitHub\OOOOOO`  
> Git 分支与当前 HEAD：`main` / `56b239bec09511a539d402b4a7c853f12950aabb`  
> 注意：当前工作区存在大量尚未提交的新增、修改和删除文件，因此该 HEAD 不能单独还原当前可运行状态。本文件记录的是核对时工作区事实，不是已发布版本说明。

## 1. 论文题目与项目定位

- 开题报告中的题目：**基于 TensorFlow 的智能电网负荷预测系统设计与实现**。
- 项目实际定位：面向美国 New England / ISO New England（ISO-NE）的智能电网短期预测系统，使用三个独立 TensorFlow/Keras 模型完成未来 24 小时负荷、电价分位和区域 BTM 光伏出力预测，并提供历史回测、误差分析、气象监测、数据库记录和前端可视化。
- 研究对象：ISO-NE 控制区与 8 个负荷分区（ME、NH、VT、CT、RI、SEMA、WCMA、NEMA）。
- 时区：业务时间统一按 `America/New_York`。负荷/电价训练表使用 hour-ending 标签；光伏训练表使用 hour-start 标签。在线管线将光伏时间加 1 小时后与负荷/电价 hour-ending 时间严格对齐。
- 当前生产推理只使用 TensorFlow。旧 PyTorch 和风电预测已退出生产调用链；仓库中保留的旧 TensorFlow 联合模型和 PV v1 仅属于历史实验资产。

### 待确认

- TODO：最终论文题目是否必须与开题报告逐字一致。若允许调整，可在副标题或摘要中明确包含电价与光伏预测。
- TODO：学院名称、专业、姓名、学号、指导教师等封面信息尚未填写。

## 2. 技术栈

| 层次 | 当前真实实现 |
|---|---|
| 前端 | React 18.2、TypeScript 5.2、Vite 4.5、React Router 6.14、Axios 1.6、Recharts 2.8、Tailwind CSS 3.3、Lucide React |
| 后端 | Python、FastAPI、Uvicorn、Pydantic 2、Requests、pandas、NumPy |
| 模型 | TensorFlow 2.16.1、Keras 3.3.3、scikit-learn StandardScaler、HDF5 `weights.h5` |
| 数据库 | MySQL 8、SQLAlchemy、aiomysql/PyMySQL；Redis 用于缓存配置；Prometheus/Grafana 用于监控配置 |
| 测试 | pytest、pytest-asyncio、pytest-cov、Vitest、TypeScript 类型检查、ESLint |
| 部署与运行 | Windows PowerShell 一键启动/停止；Docker Compose 配置同时包含 API、MySQL、Redis、Prometheus、Grafana |

主要依赖来源：`backend/requirements.txt`、`frontend/package.json`、`docker-compose.yml`。

## 3. 项目重要目录

| 路径 | 作用 |
|---|---|
| `backend/realtime_api/` | FastAPI 入口、路由、在线特征、数据库、监控和预测服务 |
| `backend/models/tensorflow_load/` | 当前 TensorFlow 模型结构定义及历史模型定义 |
| `backend/models/tf_assets/` | 当前生产权重、Scaler、元数据和冻结数据资产 |
| `backend/tests/` | 后端单元、接口、在线特征、历史回测和生产模型测试 |
| `frontend/src/` | React 页面、组件、上下文、API 客户端和类型定义 |
| `MMXX/datas/` | 2017—2026 年 ISO-NE SMD Excel、BTM PV 和 ERA5 辐照数据备份 |
| `MMXX/smart-grid/data/raw/` | 当前训练流水线使用的原始 ISO-NE、BTM PV 与天气缓存 |
| `MMXX/smart-grid/data/processed/` | 规范化小时表、特征表和数据审计结果 |
| `MMXX/smart-grid/scripts/` | 数据构建、训练、评估和图表生成脚本 |
| `MMXX/smart-grid/runs/` | 各次训练日志、指标和模型元数据 |
| `MMXX/smart-grid/figures/` | 已生成的论文候选图片 |
| `docker/` | 数据库初始化、监控和容器部署配置 |
| `Word/` | 开题报告模板和已完成开题报告 |

## 4. 数据事实

### 4.1 ISO-NE 负荷与电价小时数据

- 原始工作簿：`2017_smd_hourly.xlsx` 至 `2026_smd_hourly.xlsx`，共 10 个年度文件。
- 控制区规范表：83,975 行，范围为 `2017-01-01 01:00:00` 至 `2026-08-01 00:00:00`；审计文件按日显示到 `2026-07-31`。
- 8 个分区长表：671,800 行，即每个分区 83,975 行。
- 年度控制区行数：2017 8760、2018 8760、2019 8760、2020 8784、2021 8760、2022 8760、2023 8760、2024 8784、2025 8760、2026 5087。
- 规范特征表：`ca_features.parquet`，83,975 行、64 列。
- 主要原始字段：`RT_Demand`、`DA_Demand`、`RT_LMP`、`DA_LMP`、`Dry_Bulb`、`Dew_Point`、`System_Load`，以及 ISO-NE 分区数据。
- 夏令时处理：保留 `02X` 重复小时并通过 `seq` 表示物理小时顺序；审计中记录了春季 23 小时日和秋季 25 小时日。
- 特征表头部的 NaN 来自 1/24/168/336 小时滞后及滚动窗口预热，审计确认缺失量均不超过设计的前 336 行。

证据：`MMXX/smart-grid/data/processed/audit_stage1.json`、`audit_stage2.json`、`splits.json`、`stage1_build_canonical.py`、`stage2_build_features.py`。

### 4.2 当前负荷与电价模型使用的数据切分

最终独立模型没有直接使用 `splits.json` 中较早的 2025-11/2026-01 切分，而是在 `train_tf_split_models.py` 中重新按目标时间定义：

| 分区 | 时间范围 | 24h 窗口数 |
|---|---|---:|
| 训练集 | 2017-01-01 至 2026-04-30 23:00 | 81,407 |
| 验证集 | 2026-05-01 00:00 至 2026-06-30 23:00 | 1,441 |
| 测试集 | 2026-07-01 00:00 至 2026-08-01 00:00 | 722 |

- 每个样本包含过去 168 小时和未来 24 小时目标。
- 窗口归属由全部 24 个目标时间决定，不采用随机时间切分。
- StandardScaler 只在训练行上拟合。
- 训练时 `shuffle=True` 只打乱已经构造好的训练窗口，不会把验证或测试时间混入训练集。

### 4.3 当前 PV v2 数据

- 文件：`MMXX/smart-grid/data/processed/pv_v2_features.parquet`。
- 范围：`2025-02-01 00:00:00` 至 `2026-09-10 23:00:00`。
- 总行数：14,088 个小时。
- 训练行：12,360；验证行：1,104；测试行：624。
- 目标：ISO-NE 8 个负荷区的 estimated BTM PV 小时汇总，单位 MW。
- 目标最大值：7,059.833 MW；平均值：1,207.094 MW；大于 1 MW 的小时数：7,857。
- 训练集：2025-02-01 至 2026-06-30。
- 验证集：2026-07-01 至 2026-08-15。
- 测试集：2026-08-16 至 2026-09-10。
- 时区：`America/New_York` 本地墙钟时间，标签为小时开始时间。

### 4.4 PV v2 数据生成方式

1. 调用 ISO-NE 官方接口 `GET /api/v1.1/fiveminuteestimatedzonalload/day/{YYYYMMDD}`。
2. 读取字段 `interval_begin_date`、`load_zone_id`、`estimated_btm_pv_mw`。
3. 仅使用 4001—4008 八个负荷区。
4. 每个区每小时至少具有 10 个五分钟点时才视为完整；先按区和小时求均值，再汇总八区 MW。
5. 天气使用 Open-Meteo Previous Runs API 的 day-1 预报：短波辐照、云量、2 米温度、2 米露点。
6. 生成太阳天顶角余弦、日照标记、小时/星期/年周期编码和趋势天数。

证据：`MMXX/smart-grid/scripts/build_pv_v2_dataset.py`、`pv_v2_dataset_audit.json`。

## 5. 当前生产模型

### 5.1 独立负荷模型 `tf_load_split_v1`

| 项目 | 已核对事实 |
|---|---|
| 框架 | TensorFlow/Keras |
| 结构 | LayerNorm → BiGRU(112) → GRU(144) → RepeatVector；未来特征经 Dense(72) 投影；拼接后 GRU(144) → Dense(96) → TimeDistributed Dense(1) |
| 参数量 | 422,333 |
| 历史输入 | `(batch, 168, 21)` |
| 未来已知输入 | `(batch, 24, 17)` |
| 输出 | `(batch, 24, 1)`，未来 24 小时 RT_Demand，单位 MW |
| 损失 | Huber，`delta=0.75`（在标准化目标上） |
| 优化器 | AdamW，学习率 `8e-4`，weight decay `1e-4` |
| 训练设置 | batch 256，最大 120 epochs，EarlyStopping patience 16，实际 40 epochs，随机种子 42 |
| Scaler | 历史、未来、目标分别使用 StandardScaler，只在训练集拟合 |

历史 21 个特征：`RT_Demand`、`DA_Demand`、`RT_LMP`、`DA_LMP`、`Dry_Bulb`、`Dew_Point`、`hdd65`、`cdd65`、`temp_mem`、小时/星期/月周期编码、节假日、夏令时、24/168 小时负荷滞后、过去 24/168 小时均值。

未来 17 个特征：日前需求、日前电价、气温、露点、采暖/制冷指标、温度记忆、小时/星期/月周期编码、节假日及邻近标记、夏令时、昨日同小时实际负荷。

### 5.2 独立电价分位模型 `tf_price_split_v1`

| 项目 | 已核对事实 |
|---|---|
| 框架 | TensorFlow/Keras |
| 结构 | 与独立负荷模型相同的 BiGRU-GRU 编码解码骨干，输出头为 3 个有序分位 |
| 参数量 | 425,897 |
| 历史输入 | `(batch, 168, 26)` |
| 未来已知输入 | `(batch, 24, 17)` |
| 输出 | `(batch, 24, 3)`，依次为 P10、P50、P90，单位 USD/MWh |
| 目标变换 | `asinh(RT_LMP / 50)` 后再进行 StandardScaler；反变换为 `sinh(x) × 50` |
| 损失 | P10/P50/P90 Pinball Loss |
| 分位顺序 | 通过 `OrderedQuantiles` 层保证 P10 ≤ P50 ≤ P90 |
| 优化器 | AdamW，学习率 `8e-4`，weight decay `1e-4` |
| 训练设置 | batch 256，最大 120 epochs，EarlyStopping patience 16，实际 21 epochs，随机种子 42 |

电价历史特征在负荷 21 个历史特征基础上增加：RT-LMP 的 1/24/168 小时滞后、过去 24 小时均值和日前 LMP 的 24 小时滞后。

### 5.3 光伏模型 `pv_v2`

| 项目 | 已核对事实 |
|---|---|
| 框架 | TensorFlow/Keras |
| 结构 | 3 个因果残差 TCN 块（64 filters，膨胀率 1/2/4）→ GRU(96) 编码 → 4 头交叉注意力 → GRU(96) 解码 → Dense(64) → Softplus 输出 |
| 参数量 | 246,017 |
| 历史输入 | `(batch, 96, 28)` |
| 未来输入 | `(batch, 24, 27)` |
| 输出 | `(batch, 24, 1)`，未来 24 小时 ISO-NE estimated BTM PV MW |
| 历史特征 | 8 区 GHI、8 区云量、平均温度、平均露点、太阳几何、时间周期、趋势、历史 PV MW |
| 未来特征 | 与上面相同，但不含未来真实 PV |
| 目标缩放 | 训练集 `pv_mw_ISONE` 的 0.999 分位数，值为 6,774.643 MW |
| 损失 | 日照加权 Huber + 0.12×日能量误差 + 0.08×峰值误差 |
| 优化器 | AdamW，学习率 `4e-4`，weight decay `2e-5`，clipnorm 1.0 |
| 训练设置 | batch 256，最大 120 epochs，种子 7/42/20260912；按验证损失选择种子 42，实际训练 38 epochs |
| 后处理 | 仅当 `sun_up == 0` 时将输出设为 0；没有平滑、插值或装机容量乘数 |

### 5.4 生产资产指纹

| 资产 | SHA-256 |
|---|---|
| `load_best.weights.h5` | `D508237CB0285160D15170B2A78A5528D883E2860C947D3A542AF46F5424EBD9` |
| `load_scalers.json` | `430054BD6404EBD3A0376AC617DB292C7C25853205251E47CEB42FA8A6B6AA26` |
| `price_best.weights.h5` | `4472D2FE07B308F7F9483D782EB1E0D21EC1E70996EDC3FA5A0841C0F9A8FE77` |
| `price_scalers.json` | `E305DD904FA11CBE6E759CABD4138905B46541F13A67EACFB0E5A19E2F04BB47` |
| `pv_v2_best.weights.h5` | `84D9E4049B03ECCF5059AC409F0B070F62D17003DA8A33A4CA1C1C6620313F80` |
| `pv_v2/metadata.json` | `7C72BF05B56417D7CD1A79040D618EFE48660CF25D79C0E68711F6B70F6ADFCB` |

## 6. 生产调用链

### 6.1 统一预测

`React 页面 / ApiContext`  
→ `POST /api/prediction/load` 或 `GET /api/prediction/overview`  
→ `routers/prediction.py`  
→ `services/prediction_pipeline.py`  
→ `TFRealtimeFeatureProvider`  
→ ISO-NE + Open-Meteo  
→ 168h 负荷/电价特征与 96h 光伏特征  
→ `TFSplitService` + `TFPVV2Service`  
→ 24h 负荷、P10/P50/P90 电价、24h 光伏  
→ 时间对齐与净负荷 `load - pv`  
→ FastAPI JSON  
→ React 曲线、指标卡和详细数据表。

### 6.2 独立页面接口

| 页面/功能 | API | 当前模型或服务 |
|---|---|---|
| 负荷预测 | `POST /api/prediction/load`、`GET /api/prediction/overview` | `tf_load_split_v1` |
| 电价预测 | `GET /api/price/forecast` | `tf_price_split_v1` |
| 电价历史回测 | `GET /api/price/backtest?date=YYYY-MM-DD` | `tf_price_split_v1` 与 ISO-NE RT-LMP |
| 光伏预测与最近24h回测 | `GET /api/solar-generation` | `pv_v2` 与 ISO-NE estimated BTM PV |
| 任意日期负荷回测 | `GET /api/analytics/backtest/date?date=YYYY-MM-DD` | `tf_load_split_v1` 与 ISO-NE 实际负荷 |
| 当前气象 | `GET /api/weather/current` | Open-Meteo |
| 历史分析 | `/api/analytics/*` | 数据库记录与实时重算结果 |
| 系统状态 | `GET /api/system/status`、`GET /api/health*` | 服务、模型、数据库和资源状态 |

### 6.3 在线数据接口

- ISO-NE `hourlysysload/day/{date}`：小时系统负荷接口代码仍存在，但当前训练口径的 RT_Demand 在线值实际优先采用五分钟分区 estimated load 的八区小时汇总。
- ISO-NE `dayaheadhourlydemand/day/{date}/location/{id}`：日前需求。
- ISO-NE `hourlylmp/da/final/day/{date}/location/{id}`：日前 LMP。
- ISO-NE `hourlylmp/rt/prelim`，失败时回退 `rt/final`：实时 LMP。
- ISO-NE `fiveminuteestimatedzonalload/day/{date}`：八区实际估计负荷和 estimated BTM PV。
- Open-Meteo：六城市在线天气；PV v2 离线训练使用八区 Previous Runs day-1 预报。

## 7. 前端与系统功能

当前受保护页面：

- 总览仪表板 `/`
- 负荷预测 `/load-forecast`
- 电价预测 `/price-forecast`
- 光伏预测 `/solar-generation`
- 气象监测 `/weather-monitor`
- 运行态势 `/operation-situation`
- 历史分析 `/historical-analysis`
- 系统状态 `/system-status`

历史分析包含概览、历史记录、模型对比、趋势分析、误差分布、模型漂移、日期回测。负荷、电价和光伏预测页面已分开，各自展示对应曲线和详细数据。

## 8. 数据库事实

核心表：

- `weather_data`：气象数据，唯一键为 `(location, timestamp)`。
- `load_predictions`：24h 预测记录、光伏估计、净负荷、模型和推理信息，唯一键为 `(prediction_id, target_timestamp)`。
- `actual_load_data`：ISO-NE 实际负荷，唯一键为 `(timestamp, region)`。
- `model_performance`：模型调用与误差指标。
- `api_request_logs`、`api_access_logs`：请求和访问日志。
- `system_metrics`、`cache_performance`、`performance_alerts`：运行监控。
- 认证扩展表：`users`、`roles`、`permissions`、`user_roles`、`role_permissions`、`login_histories`、`user_sessions`、`operation_logs`。

核对时数据库中的实际负荷范围为 2026-07-25 00:00 至 2026-09-12 06:00，共 1,183 条，按小时连续。`load_predictions` 有 36,474 行、10,738 个不同目标时刻；频繁刷新会生成不同 `prediction_id` 的完整快照。

## 9. 运行与验证事实

- `start.ps1`：查找 Conda 环境 `smartgrid-tf`，验证 TensorFlow 资产，启动 FastAPI 8000 和 Vite 3000，并检查前后端代理。
- `stop.ps1`：依据进程记录和端口识别关闭本项目服务。
- 后端本次验收：205/205 项 pytest 通过。
- 前端本次验收：15/15 项 Vitest 通过；TypeScript 类型检查通过；生产构建通过。
- TensorFlow 运行资产验证通过，三个模型输出形状分别为 `(1,24,1)`、`(1,24,3)`、`(1,24,1)`。
- ESLint 当前为 0 个 error 和 28 个 warning；warning 主要为 `no-explicit-any` 类型约束提示，不影响当前构建通过，但仍属于后续代码质量改进项。
- `docker/init-db.sql` 当前定义 17 张表和 6 个视图。

## 10. 论文中必须保持的口径

1. 离线测试集指标、页面最近 24 小时历史回测指标、数据库累计在线指标是三种不同结果，不能混写。
2. 负荷/电价模型的最终测试区间为 2026-07-01 至 2026-08-01；PV v2 测试区间为 2026-08-16 至 2026-09-10。
3. 负荷和电价虽然结构相似，但权重、Scaler、历史特征数、目标和损失函数均独立。
4. 电价 MAPE 仅对 `|actual| >= 1 USD/MWh` 的点计算。
5. PV 的 MAPE 仅对真实值大于 500 MW 的稳定出力点计算；全时段和白天应主要报告 MAE、RMSE、WAPE。
6. PV v2 是数据驱动模型，不是物理装机容量估算模型；生产后处理只做夜间物理归零。
7. 当前历史回测使用事后可获得的回顾性气象观测，属于 retrospective backtest，不等于严格的“按当时发布天气预报”重演。

## 11. 已发现但尚未处理的事实冲突

- `backend/realtime_api/app.py` 的 FastAPI 描述仍写着“4个模型加权集成”和“辐射物理估算”，与当前三个独立 TensorFlow 模型不一致。
- `MMXX/smart-grid/figures/thesis/FIGURES_INDEX.md` 的模型结果仍对应旧联合模型。
- `MMXX/smart-grid/figures/pv/FIGURES_INDEX.md` 及 `pv11`—`pv17` 对应旧 PV v1，而不是当前 PV v2。
- 已完成开题报告中把光伏结构简写为 GRU，并引用了旧 PV v1 的 nMAE；正式论文必须改为当前 TCN-GRU-Attention 和 PV v2 指标。
- `backend/config/app_config.yaml` 中 `solar.installed_capacity_mw: 500` 属于旧配置遗留，当前 PV v2 推理不使用该数值。
- `backend/pyproject.toml` 未同步列出全部当前 TensorFlow 生产依赖，正式环境以 `backend/requirements.txt` 为准。

## 12. 仍需补齐的 TODO

- TODO：将当前大量未提交文件冻结为可复现 Git 版本，并记录最终 commit/tag。
- TODO：从当前独立负荷、电价模型重新生成训练曲线、测试对照、分步误差、残差和电价校准图。
- TODO：从 PV v2 重新生成损失、测试对照、晴/阴天、散点、分步误差和模型基线对比图。
- TODO：保存三个模型训练时的精确 Colab GPU 型号、CUDA/cuDNN 版本；现有指标文件只证明 TensorFlow 识别到 `/physical_device:GPU:0`。
- TODO：给出当前独立电价模型的可靠外部基线或同测试集传统方法对照。
- TODO：补充真正的浏览器端端到端测试或至少保存答辩演示验收记录。
- TODO：最终论文引用前逐条在线核对参考文献 DOI、卷期页码及学校参考文献格式。
