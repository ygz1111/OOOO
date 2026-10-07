# CAISO OASIS Solar Actual Generation 未来 24 小时预测实验

本实验的所有代码、数据、缩放器、模型和结果保存在本目录。生产前端、FastAPI、MySQL、ISO-NE 模型和现有训练数据保持原状。

## 当前状态

用户于2026-10-04明确确认官方标签与完整真实数据交集，并授权连续执行下载和训练。**已完成Colab T4三模型正式训练、Validation选型、Test末次评价、保存及云端/Windows新进程重载验证。**79项独立数据验收和178项训练资产验收全部通过，T4运行时已释放。状态记录见 `logs/training_authorization.json` 和 `TASK_STATUS.md`；完整结果见 [训练报告](TRAINING_REPORT.md)。

最终模型为GRU（Validation MAE 611.22 MW，最佳第21轮）。Test MAE 814.83 MW，持久性基线602.32 MW，**本轮未在Test MAE上超过基线**。资产验收PASS不代表预测精度超过基线，也不代表实时接入就绪。

已经验证三个模型在 Windows TensorFlow 2.16.1 CPU 和 Colab TensorFlow 2.20.0 / Tesla T4 上均能完成输出 Shape、有限梯度、`.keras` 保存、新 Python 进程加载与结果一致性检查。这些检查使用明确标注的数学测试张量，不能作为真实 CAISO 训练结果。

## 官方标签与时间

优先数据源是 [CAISO OASIS](https://oasis.caiso.com/) 的 `SLD_REN_FCST` 报告，同时严格过滤：

```text
MARKET_RUN_ID = ACTUAL
RENEWABLE_TYPE = Solar
XML_DATA_ITEM = RENEW_FCST_ACT_MW
```

训练目标统一命名为 **CAISO OASIS Solar Actual Generation / CAISO OASIS 区域太阳能实际发电功率**。只对同一个 UTC 小时、完整且唯一的 NP15/ZP26/SP15 三区域记录求和。字段单位为 MW。使用明确的 `INTERVALSTARTTIME_GMT` 和 `INTERVALENDTIME_GMT`，无需将五分钟图表数据重新聚合。每条记录代表一个物理小时；本地日历使用 `America/Los_Angeles`，春季日保留 23 小时，秋季日保留 25 小时及各自 UTC 偏移。

原始负 Solar 数值保留，不裁剪为零。不能把该报告称为全 California、全屋顶或纯光伏电站发电量。旧官方规范描述 EIR/PIRP 报告范围；当前范围是否扩展尚未核验。详细官方说明、样本和限制见 `logs/source_probe/SOURCE_REVIEW.md`，实际原始样本见 `data/raw/sample/`。

不混用 OASIS 市场报告与 Today's Outlook 的遥测曲线，不使用预测值、模拟发电量或第三方标签补齐缺小时。

## 天气与太阳位置

七个资源区域代理站点覆盖 Kern、Fresno/Kings、Mojave、Riverside、Imperial、San Diego 和 California Valley，依据 CEC 官方分布资料选择；不虚构装机容量权重。

天气变量为温度、相对湿度、云量、短波辐射、直接辐射、散射辐射、法向直接辐射、10m 风速和地面气压。采用均值、辐射/云量空间标准差及各站辐射/云量保留地区差异。

太阳几何使用 pvlib 的 NREL SPA，在 UTC 小时中点计算；本地小时、年内日和星期的周期编码明确使用 Los Angeles 时区。

未来天气必须单独选择真实历史预报口径。可行的第一版使用 GFS `previous_day2` 固定提前 48 小时预报，保存原来源、下载时间、缺值与可用性假设，不把它称为一份同时发行的 24h 预报批次。+6h 发布上界是保守分析假设，原始发布时刻未提供；每个窗口都检查预报可用上界不晚于预测原点。2023 年样本九个变量中八个缺失；2024-01-01 Kern 样本九个字段全部为空，2024-06-01 样本九个字段全部完整。不能以未来实况替代，也不能宣称 2024 年 1 月已经完整；正式范围以实际完整预报与标签交集为准。

API 辐射时间 t 为前一小时均值，对应标签区间 `[t-1h,t)`；其他天气变量保留小时末瞬时值的说明。历史天气采用明确标记的回顾性重建，不冒充当时的在线输入快照。

## 数据与训练约定

- 过去输入 `(batch,96,past_features)`，未来输入 `(batch,24,future_features)`，输出 `(batch,24,1)`。
- 用 UTC 连续小时构建窗口，不随机划分；24 个标签必须全部位于同一个分区内。
- Test 取最后约 60 个本地日，Validation 取前约 30 日，Train 使用更早的合格数据。
- 三份缩放器只在 Train 窗口拟合；Validation/Test 只 transform。
- 缺标签、缺站点或不合格预报的窗口明确计数并拒绝，不补造零值。
- GRU、TCN-GRU、TCN-GRU-Attention 使用相同分区、缩放器和评价索引。
- 训练前建立 24 物理小时持久性基线；由 Validation 选模型，冻结后一次性评价 Test，保留三个候选。
- 全天报告 MAE/RMSE/R²；白天 MAPE 阈值仅由 Train 确定，另报告每个提前量、早中晚和天气条件误差。
- 初始 batch64、最多100轮、EarlyStopping patience12、ReduceLROnPlateau factor0.5/patience5；显存不足时保留失败记录并统一减小三个模型的 batch。
- 新数据集/运行目录已存在时拒绝覆盖。

## 运行入口

以下入口用于可复现检查，不要求用户手工逐步推进任务。正式数据授权完成后由任务执行器负责下载、构建数据和 Colab T4 训练。

```text
scripts/caiso_data.py       官方标签获取、完整性检查和缓存恢复
scripts/weather_data.py     官方天气样本和来源标准化
scripts/weather_bulk.py     天气批量获取（授权后使用）
scripts/features.py         区域天气、日历与 NREL SPA 特征
scripts/dataset.py          时间划分、合格窗口及 Train-only 缩放器
scripts/models.py           三个独立 TensorFlow/Keras 模型
scripts/train.py            基线、验证集选型、训练与最终测试
scripts/evaluate.py         误差、预测 CSV 与图形
scripts/infer.py            独立模型和缩放器推理
scripts/reload_check.py     新进程保存加载验证
scripts/smoke.py            数学检查，不能当作正式训练
scripts/runtime_probe.py    TensorFlow/GPU 只读检测
```

本地复用现有 TensorFlow Python 执行 smoke；pvlib 0.16.1、pytz 2026.5 只安装在本目录 `.deps`，没有修改生产 Python 环境。需要本地运行特征检查时，将 `.deps` 加入当前进程的 `PYTHONPATH`。Colab 正式训练使用独立工作目录和依赖环境。

## 最终资产与验收

正式运行目录为 `results/runs/caiso_v1_20261004T150045Z/`，已保存 `models/caISO_pv_final.keras`、三个候选模型、三份 scaler JSON、feature/model/split 配置、history、metrics、Test 预测 CSV、三张图形及云端/Windows新进程重载报告。原始云端报告和结果归档另保留用于追溯。

资产验收 PASS 与实时可用性分别报告。OASIS Solar Actual 可能次日发布，目前缺少各历史值的首次发布记录；紧贴预测原点的过去 96h Solar 在线可得性未验证。即使离线训练和重载通过，也需要核验同口径及时 Solar 数据或发布延迟策略后，才能认定实时接入条件具备。

正式模型要求兼容TensorFlow 2.20/Keras 3的环境。Windows隔离环境 `.runtime/tf220_20261004/` 已验证可加载正式模型，原有生产TensorFlow 2.16.1环境未升级，其加载兼容性不能保证。后续正式训练仍优先Colab T4；本地用于预处理、smoke和推理验证。

无需启动或刷新生产项目来使用这些独立训练资产。推理入口为 `scripts/infer.py`，按保存的Feature Config顺序提供96小时历史与24小时未来预报特征；输出24个signed Solar MW值。只加载模型而不加载配套scaler、时区与特征顺序不能复现实验结果。
