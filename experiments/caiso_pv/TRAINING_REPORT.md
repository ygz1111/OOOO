# CAISO 光伏预测模型训练报告

正式运行：`caiso_v1_20261004T150045Z`；完成日期：2026-10-04。本报告依据本次真实数据、训练记录、预测 CSV 和独立验收结果编写；run 内的云端原始报告、模型、配置及指标文件均保留原状。

本轮已完成三种 TensorFlow 模型的正式训练、验证集选型、末次 Test 评价及新进程重载。最终保留 **GRU**，其 Validation MAE 为 **611.22 MW**，低于持久性基线的 **844.12 MW**；但 Test MAE 为 **814.83 MW**，高于基线的 **602.32 MW**，增加 **35.28%**，平均偏差为 **−616.76 MW**。因此，训练与资产验收通过，**超越基线的 Test 效果未达成**，不能将本轮结果表述为预测精度提升。

## 1. 数据来源、标签与实际覆盖

规范目标名为 **CAISO OASIS Solar Actual Generation / CAISO OASIS 区域太阳能实际发电功率**，单位 MW。标签来自 CAISO 官方 OASIS `SLD_REN_FCST` 报告，严格筛选 `MARKET_RUN_ID=ACTUAL`、`RENEWABLE_TYPE=Solar`、`XML_DATA_ITEM=RENEW_FCST_ACT_MW`，仅将同一 UTC 小时完整、唯一的 NP15、SP15、ZP26 三区域记录求和。官方记录已为小时 MW，没有改用五分钟网页曲线、Forecast、Wind、GHI、PVWatts 或第三方模拟值作为标签。

这一定义不等同于全 California 所有光伏或屋顶光伏，也没有将未核验的 Solar 覆盖面写成已确认的纯 PV 口径。官方 signed 数值全部保留；标签和模型输出均不裁零，不强制夜间为零。

| 数据口径 | 实际范围或数量 |
|---|---|
| 官方标签请求范围 | LA 2024-01-01 至 2026-10-03，含首末运行日 |
| UTC 半开请求区间 | `[2024-01-01 08:00Z, 2026-10-04 07:00Z)` |
| 请求物理小时 | 24,167 |
| 完整官方标签小时 | 24,108 |
| 官方缺失或不完整小时 | 59，涉及 44 个日期；58 小时三区域均缺，1 小时缺部分区域 |
| 原始有效负值小时 | 9,432；最小 −352.21109 MW，最大 19,738.45386 MW |
| 标签与全部天气字段共同完整的分区日界 | LA 2024-01-21 00:00 至 2026-09-28 00:00，结束不含 |

2023 年初 OASIS 历史标签当前不可取得，2023 年历史天气预报字段也不足，正式范围按用户确认的真实有效数据交集确定；没有为凑多年数据更换标签定义或补造天气。严格筛选后的标签重复行为0，未混入DAM/HASP/RTPD/RTD预测。59个缺小时仍保留在UTC连续网格内，受影响的窗口明确拒绝；不以插值、部分区域和、固定零值或估计值掩盖缺失。

来源与缺口证据见 [官方标签下载审计](D:/GitHub/OOOOOO/experiments/caiso_pv/logs/source_probe/LABEL_DOWNLOAD_AUDIT_20261004T143346982407Z.md) 和 [来源核验说明](D:/GitHub/OOOOOO/experiments/caiso_pv/logs/source_probe/SOURCE_REVIEW.md)。

## 2. 时间、天气和输入特征

时间轴使用连续 UTC 物理小时，显示及日历划分使用 `America/Los_Angeles`。一个目标区间定义为 `[interval_start, interval_end)`，恰好一个物理小时。origin 是第一个未来区间起点；第 h 个输出对应 `[origin+(h−1)小时, origin+h小时)`。因此报告的 t+1 至 t+24 是目标区间终点的提前量，其区间起点提前量为 0 至 23 小时。

官方标签已实际核验五个 DST 转换日：

| LA 日期 | 物理小时 | 完整标签小时 |
|---|---:|---:|
| 2024-03-10 | 23 | 23 |
| 2024-11-03 | 25 | 25 |
| 2025-03-09 | 23 | 23 |
| 2025-11-02 | 25 | 25 |
| 2026-03-08 | 23 | 23 |

春季没有制造不存在的 02 点；秋季两个 01 点保留各自 UTC 时刻与偏移。跨 DST 的模型窗口仍为连续 24 个物理小时，持久性基线也是 lag24 物理小时，并不强称始终为同一个当地墙钟小时。

天气来源为 Open-Meteo：过去天气采用 **ERA5 事后历史重建**，未来天气采用 **GFS global day2 固定提前 48 小时历史预报**，并记录 **额外 6 小时发布延迟上界假设**。每个窗口都校验记录上界不晚于 origin；该检查不能证明历史首次发布时间已实测，day2 的 24 个未来值也不冒称同一批同时发行的预报。辐射 API 时刻 t 的前一小时均值对应 `[t−1小时,t)`；其他天气变量保留小时末瞬时值的说明。官方定义见 [Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api) 与 [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)。

使用 Kern、Fresno/Kings、Mojave、Riverside、Imperial、San Diego 和 California Valley 七个区域代理站点。区域均值采用等权天气站点，不虚构装机容量权重。

| 特征类别 | 已保存的最终内容 |
|---|---|
| 历史标签 | `solar_actual_mw`，仅出现在过去输入 |
| 九项天气变量 | 温度、相对湿度、云量、短波/直接/散射/法向直接辐射、10m 风速、地面气压 |
| 空间差异 | 全变量区域均值，短波辐射/云量的空间标准差及七站各自辐射/云量 |
| 时间周期 | hour、day_of_year、day_of_week 的 sin/cos |
| 太阳几何 | pvlib NREL SPA，在 UTC 区间中点计算 coszen、solar elevation、sun_up_any、sun_up_fraction |
| 输入 Shape | 过去 `(batch,96,36)`；未来 `(batch,24,35)` |
| 输出 Shape | `(batch,24,1)`，一次输出未来 24 点 signed MW |

未来输入只有天气预报、时间和太阳几何，没有未来实际 Solar。特征顺序、站点坐标、来源、辐射对齐和发布假设完整保存在 [feature_config.json](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/feature_config.json)。太阳几何使用独立实现与昼夜专项检查，没有复制现有 ISO-NE 的太阳公式。

## 3. 数据划分与防泄漏

按真实共同数据日界自动划分：最后 60 个 LA 日作为 Test 候选分区，前 30 日作为 Validation，之前作为 Train。所有样本的完整 24 个目标小时必须处于对应半开区间，禁止随机划分及跨分区目标；缺过去 96 小时、缺未来标签或缺合格预报的窗口不接纳。

| 分区 | LA 开始（含） | LA 结束（不含） | 24h 窗口数 | 重复目标比较点 | 纳入窗口的唯一目标小时 | 缺标签/历史拒绝窗口 |
|---|---|---|---:|---:|---:|---:|
| Train | 2024-01-21 00:00 PST | 2026-06-30 00:00 PDT | 17,101 | 410,424 | 17,906 | 4,259 |
| Validation | 2026-06-30 00:00 PDT | 2026-07-30 00:00 PDT | 697 | 16,728 | 720 | 0 |
| Test | 2026-07-30 00:00 PDT | 2026-09-28 00:00 PDT | 882 | 21,168 | 997 | 535 |

**Test 的 60 日是候选分区，不能称为完整连续 60 天测试数据。**该区间共有 1,440 个物理小时；最终合格窗口覆盖 997 个不同目标小时，535 个受标签或历史缺口影响的候选窗口被拒绝。882 个窗口、21,168 个重复比较点和 997 个唯一小时是三种不同口径。误差按 origin/horizon 预测实例统计，重叠目标小时没有假称独立观测。

三个 scaler 只拟合已接纳的 Train 样本，Validation/Test 仅 transform；重复 Train 窗口的原始值按保存口径参与拟合。Train 首个 origin 前的 96 小时历史预热始于 2024-01-17 08:00 UTC，它是训练样本过去输入，不是跨入 Validation/Test 的未来标签。

冻结 dataset.npz SHA256 为 `7ed08a1a55d79280b406d30eeb90db0aa5647a68a225602fae854c0a18670f4d`。独立 [79 项数据审计](D:/GitHub/OOOOOO/experiments/caiso_pv/logs/dataset_independent_audit_20261004T145916251182Z.md) 全部通过：448,320 个目标比较点与官方 CSV 对照，逆缩放最大差异 0.00075014 MW；lag24 基线差异为 0 MW；分区、Train-only scaler、DST 和未来预报上界均按记录契约核验。

## 4. 正式训练、基线和验证集选型

训练使用独立 Colab **Tesla T4**，Python **3.13.15**、TensorFlow **2.20.0**、Keras **3.13.2**，CUDA/GPU 实际识别通过。当前可访问本地生产环境为 TF2.16.1 CPU；没有将正式训练放在该环境，也没有升级生产依赖。本地额外建立独立 TF2.20 CPU 环境用于正式模型重载。

三候选共用相同数据、scaler、指标及索引；均为新初始化的 TensorFlow/Keras 模型，不使用现有 ISO-NE 权重。配置为 Adam、Huber、seed42、初始学习率 0.001、batch64、最多 100 轮、hidden128、dropout0.15、L2 1e−5、梯度 clipnorm1。TCN 使用 96 filters、kernel3、dilation 1/2/4/8；Attention 为 4 heads。EarlyStopping patience12，ReduceLROnPlateau factor0.5/patience5。没有 OOM 减小 batch，没有 Test 驱动调参或更换最终模型。

fit 前先计算 24 物理小时持久性基线，结果已保存：

| 基线分区 | MAE MW | RMSE MW | R² | Daylight MAPE % |
|---|---:|---:|---:|---:|
| Train | 614.14 | 1,314.47 | 0.956420 | 17.95 |
| Validation | 844.12 | 1,710.52 | 0.952752 | 14.88 |

每候选按 Validation loss 保存最佳 checkpoint；候选之间按已确认的 **Validation MAE** 选 Final。选择结果如下：

| 候选 | 参数量 | 实际训练轮数 | 最佳 epoch | Val MAE MW | Val RMSE MW | Val R² | Val Daylight MAPE % | 模型训练秒数 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GRU（Final） | 198,017 | 33 | 21 | 611.22 | 1,019.95 | 0.983201 | 9.96 | 133.4 |
| TCN-GRU | 448,097 | 33 | 21 | 701.13 | 1,209.19 | 0.976389 | 14.36 | 291.8 |
| TCN-GRU-Attention | 514,401 | 35 | 23 | 926.10 | 1,274.68 | 0.973762 | 16.46 | 342.3 |

GRU 在 Validation 上的 MAE 比基线低 27.59%，因此在读取 Test 之前冻结为 Final。总训练流程耗时 **770.4 秒（约 12.8 分钟）**，含三候选构建、训练及 Validation checkpoint 推理等训练阶段工作；不含数据下载、运行时准备、末次 Test 评价和归档传输。各模型秒数为各自 fit、checkpoint 保存/加载及 Validation 推理阶段，不能把总训练时间当成全任务耗时。

参数与选择依据见 [model_config.json](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/model_config.json)、[training_history.json](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/training_history.json) 和 [训练前计划](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/training_plan.json)。

## 5. 冻结后的 Test 结果

全部候选训练完成并冻结后，以相同 882 个 origin、24 个 horizon 和 21,168 个比较点，对基线及三模型进行一次末次 Test 评价。白天有效阈值仅由 Train 正 Solar 值 P99 的 1% 决定且至少 1 MW，本轮为 **181.29070 MW**；MAPE 只在 Actual 严格大于该阈值时统计，共 11,863 个重复预测比较点。全天指标包含真实 signed 夜间值。

| 模型 | Test MAE MW | Test RMSE MW | Test R² | Test Daylight MAPE % |
|---|---:|---:|---:|---:|
| 持久性基线 | 602.32 | 1,258.65 | 0.974627 | 11.85 |
| GRU（Val 选定 Final） | 814.83 | 1,373.45 | 0.969787 | 13.70 |
| TCN-GRU | 719.87 | 1,184.09 | 0.977544 | 13.87 |
| TCN-GRU-Attention | 937.62 | 1,245.31 | 0.975162 | 21.10 |

Final GRU 的 Test MAE 高于基线 35.28%，bias=预测−实际为 **−616.76 MW**，存在明显低估。TCN-GRU 的 Test RMSE 较低，但三个神经网络的 Test MAE 均未超过基线；不能根据已经看到的 Test 指标把 Final 改为 TCN-GRU，也不能利用这些 Test 误差校正模型后再称独立测试。高全天 R² 受明显日周期影响，不能抵消白天高值段误差与偏差。

原始结果及精确小数见 [metrics.json](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/metrics.json)。[178 项训练资产审计](D:/GitHub/OOOOOO/experiments/caiso_pv/logs/training_assets_independent_audit_20261004T153238845872Z.md) 全部通过：从保存的 Test CSV 独立重算指标、核对 origin/horizon/官方标签、训练记录、候选及 Final SHA。审计没有再次对全 Test 执行模型推理；Validation MAE 的核对依据是保存的指标，未另存 Validation 预测 CSV。独占 Test 标记和日志支持本次流程一次评价，不声称可证明没有任何未记录的外部实验。

## 6. Final 的 24 步与分组误差

每步均为 882 个预测实例。提前量按前述目标区间终点定义，表格与图均使用完整 24 个物理小时。

| 步 h | MAE MW | RMSE MW | R² | Daylight MAPE % |
|---:|---:|---:|---:|---:|
| 1 | 807.91 | 1,274.32 | 0.973996 | 14.41 |
| 2 | 835.35 | 1,338.06 | 0.971417 | 13.87 |
| 3 | 796.49 | 1,331.79 | 0.971702 | 12.93 |
| 4 | 803.80 | 1,348.35 | 0.970972 | 13.16 |
| 5 | 821.94 | 1,375.15 | 0.969749 | 13.65 |
| 6 | 838.55 | 1,399.73 | 0.968608 | 14.03 |
| 7 | 849.23 | 1,414.60 | 0.967884 | 14.16 |
| 8 | 858.88 | 1,427.35 | 0.967304 | 14.26 |
| 9 | 856.43 | 1,431.94 | 0.967140 | 14.13 |
| 10 | 849.06 | 1,427.80 | 0.967366 | 14.03 |
| 11 | 837.36 | 1,417.35 | 0.967875 | 13.99 |
| 12 | 827.81 | 1,404.94 | 0.968457 | 14.00 |
| 13 | 818.84 | 1,394.19 | 0.968938 | 13.58 |
| 14 | 810.85 | 1,386.47 | 0.969254 | 13.34 |
| 15 | 805.90 | 1,383.77 | 0.969312 | 13.21 |
| 16 | 806.55 | 1,388.14 | 0.969042 | 13.29 |
| 17 | 804.83 | 1,388.04 | 0.968977 | 13.58 |
| 18 | 799.90 | 1,379.22 | 0.969353 | 13.59 |
| 19 | 792.23 | 1,360.50 | 0.970224 | 13.63 |
| 20 | 785.75 | 1,345.70 | 0.970932 | 13.50 |
| 21 | 784.54 | 1,336.19 | 0.971366 | 13.59 |
| 22 | 785.82 | 1,330.93 | 0.971632 | 13.67 |
| 23 | 786.67 | 1,329.38 | 0.971760 | 13.57 |
| 24 | 791.19 | 1,335.56 | 0.971560 | 13.64 |

当地时段使用固定 LA 钟点区间，非天文昼夜分类：

| 时段 | 比较点 | MAE MW | RMSE MW | R² | Daylight MAPE % | MAPE 有效比较点 |
|---|---:|---:|---:|---:|---:|---:|
| 早晨 `[06:00,10:00)` | 3,528 | 1,131.04 | 1,663.62 | 0.930436 | 16.62 | 3,451 |
| 中午 `[10:00,16:00)` | 5,292 | 1,808.38 | 2,129.21 | −0.341194 | 10.50 | 5,292 |
| 傍晚 `[16:00,20:00)` | 3,528 | 867.05 | 1,315.08 | 0.953234 | 15.89 | 3,119 |
| 其他钟点 | 8,820 | 71.33 | 91.37 | −12.056713 | 101.08 | 1 |

中午 MAE 为 1,808.38 MW、bias 为 −1,737.53 MW，是主要低估时段。其他钟点的 R² 因实际值方差较小而为负，其 MAPE 仅有 1 个达到阈值的比较点，不能代表夜间总体百分比精度或被解读为有稳定统计意义的白天结论。

天气组按对齐的**未来预报区域平均云量**定义，不是观测天气分类；高波动指该云量每物理小时变化至少 25 个百分点，不等同于实测辐射波动。各组可能重叠，也不覆盖所有时刻。

| 预报云量组 | 比较点 | MAE MW | RMSE MW | R² | Daylight MAPE % | MAPE 有效比较点 |
|---|---:|---:|---:|---:|---:|---:|
| 低云量 ≤20% | 11,688 | 745.18 | 1,247.02 | 0.976910 | 11.09 | 6,703 |
| 高云量 ≥80% | 355 | 997.07 | 1,805.93 | 0.895091 | 35.38 | 143 |
| 云量变化 ≥25 百分点/小时 | 656 | 1,065.00 | 1,693.71 | 0.956770 | 14.70 | 299 |

图形：[训练/验证 loss 曲线](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/figures/loss_curves.png)、[实际与预测曲线](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/figures/actual_vs_predicted.png)、[24 步 MAE 曲线](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/figures/horizon_error.png)。实际与预测图展示首个 Test origin（LA 2026-07-30 00:00）的完整 24h，仅为一个案例，整体结论依据全部合格比较点。

## 7. 早停与过拟合判断

GRU 最佳轮为 epoch21，此时 Train/Val loss 为 0.012082/0.014731；随后 Train loss 持续下降至 0.008806，而 Val loss 在 epoch33 上升到 0.029180，约为最佳 Val loss 的 1.98 倍。曲线与记录说明存在**后期过拟合迹象**，不能仅凭最佳 epoch 的 Val/Train 比值 1.22 就写“无明显过拟合”。EarlyStopping 在 12 轮无改善后停止并恢复最佳 checkpoint，Final 保存的是 epoch21 的模型，不是末轮权重。

TCN-GRU 和 Attention 的训练后段也出现 Train/Val 分离；它们分别保存 epoch21/23，实际训练至 33/35。不同时间分布也可能影响验证差距，因此本报告描述观察到的曲线和验证下降/回升，不把所有分布偏移直接归因于模型过拟合。本轮没有根据已经看到的 Test 结果再调参数、缩放器或偏差。

原 loss 图横轴使用从 **0 开始的数组索引**，训练日志、本报告及最佳 epoch 使用从 **1 开始的轮次**；图上索引 20 对应报告 epoch21，索引 22 对应 epoch23。三图原件保持不改。

## 8. 本地资产和保存加载验收

正式资产统一位于 `D:\GitHub\OOOOOO\experiments\caiso_pv\results\runs\caiso_v1_20261004T150045Z`。

| 交付项 | 本地文件 |
|---|---|
| Final 原生模型 | [models/caISO_pv_final.keras](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/models/caISO_pv_final.keras) |
| 三候选最佳模型 | [GRU](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/models/gru/best.keras)、[TCN-GRU](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/models/tcn_gru/best.keras)、[TCN-GRU-Attention](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/models/tcn_gru_attention/best.keras) |
| Train-only scalers | [past_scaler.json](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/scalers/past_scaler.json)、[future_scaler.json](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/scalers/future_scaler.json)、[target_scaler.json](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/scalers/target_scaler.json) |
| 特征/模型/划分/历史/指标 | [feature_config](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/feature_config.json)、[model_config](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/model_config.json)、[split_info](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/split_info.json)、[training_history](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/training_history.json)、[metrics](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/metrics.json) |
| Final Test 预测 CSV | [results/test_predictions.csv](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/results/test_predictions.csv) |
| T4 新进程重载 | [reload_check.json](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/reload_check.json) |
| Windows 独立 TF2.20 新进程重载 | [reload_check_local_tf220.json](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/reload_check_local_tf220.json) |
| 云端原始报告 | [run/TRAINING_REPORT.md](D:/GitHub/OOOOOO/experiments/caiso_pv/results/runs/caiso_v1_20261004T150045Z/TRAINING_REPORT.md) |

Test CSV 包含 `timestamp`（LA、带 UTC 偏移）、`timestamp_utc`、`forecast_origin_utc`、`actual_mw`、`predicted_mw`、`forecast_horizon`。另保存三候选各自的完整 Test CSV，全部索引与 Final 对齐。Final 模型 SHA256 为 `2b9dc6c475f7b291ebac083b2493f841ea5c18f1ecbbc33c7135714e75dc0857`，与被选中 GRU 最佳 checkpoint 一致。

T4 和 Windows 独立 TF2.20 的新进程均重新读取 `.keras`、三 scaler、Feature Config，将前两个 Test 样本的原始特征重新标准化、推理并逆变换为 signed MW。Shape 为 `(2,24,1)`，无 NaN；最大标准化差异 `4.76837×10⁻⁷`，最大 MW 差异 **0.00300247 MW**，两次均 PASS。`rtol=1e−4`，标准化 `atol=1e−5` 按保存 target scale 换算为 **0.06296642 MW**，没有任意放大单位容差。

原生模型使用 TensorFlow 2.20/Keras 对应环境。此前 TF2.20 数学 smoke 模型在生产旧 TF2.16.1 下直接加载曾发生初始化器配置兼容错误，因此不声称正式模型兼容 TF2.16。生产 TF2.16 环境未升级；未降版本改写正式 `.keras` 权重或配置。

结果 ZIP 已下载并完成 CRC/SHA 核验；正式 T4 session `caiso-pv-formal-20261004-r2` 已释放，CLI stop 返回成功。根执行器对原有15个生产模型/缩放器资产逐项核验，变更列表为空；现有前端、FastAPI、MySQL、ISO-NE模型未接入本实验。完整交付核验见 [delivery_verification.json](D:/GitHub/OOOOOO/experiments/caiso_pv/logs/caiso_v1_20261004T150045Z_delivery_verification.json)。

## 9. 最终结论与实时接入条件

**【CAISO PV Final Model：PASS（正式离线训练、资产完整性与新进程重载）】**

**超基线效果：未达成。**按预先确认的 Validation 规则冻结 GRU；Test MAE 及 Daylight MAPE 均劣于持久性基线，存在白天高出力时段低估，不能将资产 PASS 解读为已经优于基线或可直接投入运行。

**目前尚未具备已经验证的实时接入条件。**数学时间无越界与完整窗口分区已通过，但 OASIS Actual 的历史首次发布时间没有验证，紧贴 origin 的过去 96h Solar 不能直接认定当时已发布；ERA5 为事后重建，可能在 origin 后修订；GFS day2 的额外 6h 发布上界也是明示假设，且固定提前量序列不同于未来实时单批天气预报契约。后续须核验同口径及时 Solar 或明确发布延迟策略，并验证实时天气/特征契约及独立未来时段效果。本轮只交付独立研究资产，不接入现有 API 或部署。
