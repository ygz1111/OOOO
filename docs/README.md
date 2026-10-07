# 智能电网负荷预测系统

面向 ISO New England 的 TensorFlow 智慧能源预测平台，提供未来 24 小时负荷、电价与光伏发电预测，以及历史回测、误差分析、气象监测和可视化大屏。

当前交付方式为本地运行。最近启动优化见 [启动与首次加载验收](启动与首次加载验收-2026-10-01.md)，时间口径及已有修复见 [本地运行数据对齐验收](本地运行数据对齐验收-2026-09-23.md)。

模型开发和正式训练遵循 [模型训练与验证环境约定](模型训练与验证环境约定.md)：本地完成开发及小规模验证，正式训练优先使用 Google Colab T4，现有模型和训练数据保留。提前量误差统计、输入留档及离线诊断见 [预测评估与输入留档验收](预测评估与输入留档验收-2026-10-03.md)。

电价标签、回测日期竞争及电价/光伏页面恢复的本轮验证见 [电价标签与页面恢复验收](电价标签与页面恢复验收-2026-10-01.md)。

前端正式工作台与深色监控两种外观的实现与验证见 [前端双模式视觉验收](前端双模式视觉验收-2026-10-03.md)。

CAISO 太阳能页面及其后端接口已于 2026-10-06 移除，见 [功能移除记录](maintenance/CAISO功能移除-2026-10-06.md)。独立训练模型和数据保留，研究记录见 [CAISO 独立实验说明](../experiments/caiso_pv/README.md)；此前 [页面接入与验收](CAISO太阳能页面接入与验收-2026-10-05.md) 仅作为历史记录，不代表当前功能。

论文正文和配套事实、图表、实验记录集中在 `Word/`，可从 [论文项目事实](../Word/materials/THESIS_PROJECT_FACTS.md) 和 [论文提纲](../Word/materials/THESIS_OUTLINE.md) 查阅。历史项目审计见 [项目审计与上下文](audits/PROJECT_AUDIT.md)。

当前目录位置、已删除项、验证结果及恢复备份见 [项目清理与目录整理记录](maintenance/项目清理与目录整理-2026-10-06.md)。

## 当前生产模型

ISO-NE 在线预测链接入以下 3 个 TensorFlow 模型，模型加载失败时直接报告错误，不回退到其他框架或物理估算：

| 模型标识 | 任务 | 架构 | 输入 | 输出 |
|---|---|---|---|---|
| `tf_load_split_v1` | 负荷预测 | BiGRU + GRU 编解码器 | 过去 168h + 未来 24h 已知特征 | 未来 24h 负荷（MW） |
| `tf_price_split_v1` | 电价预测 | BiGRU + GRU 分位数模型 | 过去 168h + 未来 24h 已知特征 | 未来 24h P10/P50/P90（USD/MWh） |
| `pv_v2` | 光伏预测 | TCN + GRU + 交叉注意力 | 过去 96h + 未来 24h 气象/太阳特征 | 未来 24h 分布式光伏估算参考出力 |

生产权重与 scaler 位于 `backend/models/tf_assets/`，模型定义位于 `backend/models/tensorflow_load/`，加载入口位于 `backend/realtime_api/services/container.py`。

## 技术栈

- 前端：React、TypeScript、Vite、Tailwind CSS、Recharts
- 后端：FastAPI、Pydantic、SQLAlchemy Async
- AI：TensorFlow/Keras、NumPy、Pandas、scikit-learn
- 数据库：MySQL；Redis 用于缓存；Prometheus/Grafana 用于监控
- 外部数据：ISO-NE、Open-Meteo

## 主要目录

```text
backend/
  realtime_api/                 FastAPI、路由、实时特征与模型服务
  models/tensorflow_load/       TensorFlow 模型定义
  models/tf_assets/             生产权重、scaler、冻结验收数据
  scripts/                      数据准备、校验与运行检查
  tests/                        后端测试
frontend/                       React 可视化前端
MMXX/                           TensorFlow 训练工程和训练结果
solar_data/                     光伏数据准备，不参与线上模型加载
experiments/caiso_pv/            保留的 CAISO 独立研究模型和数据
Word/                           毕业论文正文、配套材料与验收图表
  materials/                    论文事实、提纲、实验记录和图表依据
docs/                           项目文档
  audits/                       历史项目审计
  evidence/                     验收截图、检查记录和测量日志
docker-compose.yml              MySQL/Redis/监控等服务编排
start.ps1                       Windows 启动入口
```

## 在线预测链

```text
React 前端
  -> FastAPI /api/prediction/load
  -> Open-Meteo 气象 + ISO-NE 历史负荷/电价
  -> TensorFlow 实时特征适配器
  -> 独立负荷模型 + 独立电价模型 + 光伏模型
  -> 反归一化、净负荷计算
  -> API 返回并按业务逻辑入库
```

生产模式要求三个模型均成功加载，且实时特征字段、顺序、窗口长度与训练契约完全一致。

## 启动与验证

```powershell
.\start.ps1
python backend/scripts/check_runtime.py
python -m pytest backend/tests
cd frontend
npm run build
```

前端默认 `http://localhost:3000`，后端默认 `http://localhost:8000`。数据库、JWT 等敏感配置通过 `.env` 提供。

禁止用文件是否存在代替模型验收；至少要同时验证权重可加载、输入/输出 Shape 正确、在线特征可生成、预测接口可返回 24 个点。
