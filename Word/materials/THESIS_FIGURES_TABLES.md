# 毕业论文图片与表格清单

> 分类规则：  
> **A 可直接使用**：内容与当前数据事实一致。  
> **B 可作为历史/对照使用**：必须在图题中注明旧模型或旧数据口径。  
> **C 必须重生成**：当前图片不能代表上线模型。  
> 所有现有 PNG 均为候选素材，正式论文插入前仍需检查中文字体、分辨率、坐标轴、单位和图注。

## 1. 负荷、电价数据探索图

目录：`MMXX/smart-grid/figures/thesis/`

| 文件 | 建议图名 | 章节 | 分类与说明 |
|---|---|---|---|
| `fig01_rt_overview.png` | ISO-NE 控制区实时负荷逐时序列 | 3.1/3.3 | A，数据 EDA |
| `fig02_rt_by_month_box.png` | 实时负荷月度分布箱线图 | 3.3 | A |
| `fig03_daily_profile_daytype.png` | 不同日期类型的平均日负荷曲线 | 3.4 | A |
| `fig04_load_vs_temperature.png` | 负荷与温度关系 | 3.4 | A |
| `fig05_heatmap_hour_dow.png` | 小时与星期负荷热力图 | 3.4 | A |
| `fig06_price_overview.png` | 日前与实时电价逐时序列 | 3.1/3.3 | A |
| `fig07_price_profile.png` | 工作日与周末电价日曲线 | 3.3 | A |
| `fig08_price_hist.png` | 日前与实时电价分布 | 3.3 | A |
| `fig09_da_rt_demand.png` | 日前需求与实时负荷对比 | 3.4/6.3 | A，可解释 DA 基线 |
| `fig10_zone_profiles.png` | 八分区平均日负荷曲线 | 3.1/3.3 | A |
| `fig11_zone_levels.png` | 八分区平均负荷水平 | 3.1 | A |
| `fig12_station_weather.png` | 八站点月均气温热力图 | 3.1/3.4 | A，离线 SMD 站点口径 |
| `fig13_acf_load.png` | 负荷自相关函数 | 3.4 | A，支撑 24h/168h 滞后 |
| `fig14_holiday_effect.png` | 节假日与工作日负荷曲线 | 3.4 | A |
| `fig15_split_timeline.png` | 数据集时间划分示意 | 3.6/6.2 | C；现图基于旧联合模型切分，须按最终独立模型切分重画 |
| `fig16_seasonal_profiles.png` | 四季平均日负荷曲线 | 3.3 | A |

## 2. 现有负荷与电价模型结果图

| 文件 | 内容 | 分类与处理建议 |
|---|---|---|
| `fig17_loss_curves.png` | 旧联合模型训练/验证损失 | C；必须从 `tf_split_v1/load_train_log.csv` 与 `price_train_log.csv` 分别重画 |
| `fig18_test_overlay_step1.png` | 旧联合模型测试期第 1 步对照 | C；改用独立负荷模型输出 |
| `fig19_day_spike_20260702.png` | 旧联合模型尖峰日 | C；以独立负荷模型重算 |
| `fig20_day_weekday_20260709.png` | 旧联合模型工作日 | C；以独立负荷模型重算 |
| `fig21_day_weekend_20260712.png` | 旧联合模型周末 | C；以独立负荷模型重算 |
| `fig22_scatter_pred_actual.png` | 旧联合模型预测—实际散点 | C |
| `fig23_error_by_horizon.png` | 旧联合模型分预测步长误差 | C |
| `fig24_error_by_clock_hour.png` | 旧联合模型分时刻误差 | C |
| `fig25_residual_hist.png` | 旧联合模型残差分布 | C |
| `fig26_price_fan_spike.png` | 旧联合模型尖峰日电价扇形图 | C；改用独立电价模型 |
| `fig27_price_fan_normal.png` | 旧联合模型常规日电价扇形图 | C |
| `fig28_price_calibration.png` | 旧联合模型分位校准 | C；按当前 66.93% 覆盖率重画 |
| `fig29_model_vs_baseline.png` | 旧联合模型与 DA 基线 | C；用当前测试目标索引重算 |

这些图由 `make_train_figures.py` 生成，脚本默认读取旧联合模型运行目录，不能直接证明当前 `tf_load_split_v1` 和 `tf_price_split_v1` 的结果。

## 3. 光伏数据探索图

目录：`MMXX/smart-grid/figures/pv/`

| 文件 | 建议图名 | 章节 | 分类与说明 |
|---|---|---|---|
| `pv01_overview.png` | ISO-NE BTM PV 历史归一化序列 | 3.1/3.3 | B；来自旧 `pv_features.parquet`，可作长期历史 EDA，不能写成 PV v2 训练集 |
| `pv02_monthly_box.png` | 光伏出力月度分布 | 3.3 | B，同上 |
| `pv03_seasonal_curve.png` | 四季平均日光伏曲线 | 3.3 | B |
| `pv04_pv_vs_radiation.png` | 光伏出力与 GHI 关系 | 3.5 | B；使用 ERA5 口径 |
| `pv05_pv_vs_cloud.png` | 光伏出力与云量关系 | 3.5 | B |
| `pv06_coszen_response.png` | 光伏出力与太阳高度关系 | 3.5 | B |
| `pv07_zone_summer.png` | 八分区夏季光伏日曲线 | 3.1/3.5 | B |
| `pv08_capacity_growth.png` | BTM PV MW 增长与归一化出力 | 3.1/6.8 | B，适合解释装机规模变化，但必须注明旧数据构造 |
| `pv09_heatmap_month_hour.png` | 月份—小时光伏热力图 | 3.3 | B |
| `pv10_solstice_days.png` | 节气典型日光伏曲线 | 3.5 | B |

建议：长期 EDA 可以保留这些图，但应在数据章节单独说明其使用 2017—2026-04 历史归一化 PV/ERA5 数据；PV v2 正式训练只使用 2025-02—2026-09 的官方 estimated BTM PV MW 与 day-1 天气预报。

## 4. 现有 PV v1 模型结果图

| 文件 | 内容 | 分类与处理建议 |
|---|---|---|
| `pv11_loss_curves.png` | PV v1 损失 | C；用 PV v2 三个 seed 日志及选中 seed 42 重画 |
| `pv12_test_overlay.png` | PV v1 测试对照 | C；改用 PV v2 测试集 |
| `pv13_sunny_day.png` | PV v1 晴天样例 | C |
| `pv13_cloudy_day.png` | PV v1 阴天样例 | C |
| `pv14_scatter.png` | PV v1 散点 | C |
| `pv15_error_by_step.png` | PV v1 分步误差 | C |
| `pv16_error_by_hour.png` | PV v1 分小时误差 | C |
| `pv17_model_vs_naive.png` | PV v1 与 naive-24 | C；按 PV v2 指标重画，当前 PV v2 白天 WAPE 改善 57.42% |

## 5. 当前项目已有界面图片

| 文件 | 内容 | 建议章节 | 使用建议 |
|---|---|---|---|
| [Word/assets/screenshots/login_page.png](../assets/screenshots/login_page.png) | 登录页 | 5.6 | B；核对是否为最终 UI 后使用 |
| [Word/assets/screenshots/load_forecast_page.png](../assets/screenshots/load_forecast_page.png) | 负荷预测页 | 5.6/6.7 | B；核对模型名、时间和指标是否为最新 |
| [Word/assets/grid-command-logo.png](../assets/grid-command-logo.png) | 系统 Logo | 5.6 或附录 | A，必要时使用 |
| [Word/assets/emblem-original.png](../assets/emblem-original.png) | 视觉素材 | 不建议作为实验图 | 仅可用于系统界面设计说明 |

### 建议补拍的最终系统截图

1. 总览仪表板：三个模型加载状态和综合指标。
2. 负荷预测页：当前实际、历史回测、未来 24h 和详细表格。
3. 电价预测页：P10/P50/P90、历史回测和详细表格。
4. 光伏预测页：未来 24h、ISO-NE BTM 历史回测和详细表格。
5. 气象监测页：六城市数据。
6. 运行态势页：负荷、气象和特征敏感度。
7. 历史分析页：趋势、误差分布、漂移和日期回测。
8. 系统状态页：3/3 TensorFlow 模型加载和数据库/API 状态。

TODO：截图前冻结版本、预热模型并隐藏个人账号、密钥、浏览器开发工具和无关桌面信息。

## 6. 建议制作的新架构与流程图

| 编号建议 | 图名 | 建议章节 | 数据来源 |
|---|---|---|---|
| 图1-1 | 论文研究技术路线 | 1.5 | 本项目完整调用链 |
| 图3-1 | 多源数据时间对齐关系 | 3.2 | hour-start/hour-ending 与 America/New_York |
| 图3-2 | 负荷与电价数据处理流程 | 3.3 | stage1/stage2/train_tf_split_models |
| 图3-3 | PV v2 数据生成流程 | 3.3 | build_pv_v2_dataset |
| 图4-1 | 独立负荷模型结构 | 4.2 | tf_split_models.py |
| 图4-2 | 独立电价分位模型结构 | 4.3 | tf_split_models.py |
| 图4-3 | PV v2 TCN-GRU-Attention 结构 | 4.4 | tf_pv_v2_models.py |
| 图5-1 | 系统总体架构 | 5.2 | React/FastAPI/服务/模型/MySQL/外部 API |
| 图5-2 | 前端到模型的在线预测时序图 | 5.3/5.5 | prediction_pipeline 与 provider |
| 图5-3 | 数据库核心 ER 图 | 5.4 | docker/init-db.sql 与认证表脚本 |
| 图5-4 | 24h 历史回测流程 | 5.3/6.6 | analytics/price/generation 路由 |

## 7. 建议放入正文的表格

| 表号建议 | 表名 | 章节 | 当前数据是否齐全 |
|---|---|---|---|
| 表3-1 | 数据源、字段、时间粒度与时区 | 3.1 | 是 |
| 表3-2 | 2017—2026 年 ISO-NE 年度行数 | 3.3 | 是 |
| 表3-3 | 最终模型训练/验证/测试划分 | 3.6 | 是 |
| 表3-4 | 负荷模型历史与未来特征 | 3.4 | 是 |
| 表3-5 | 电价模型新增历史特征 | 3.4 | 是 |
| 表3-6 | PV v2 历史与未来特征 | 3.5 | 是 |
| 表4-1 | 三个生产模型结构与输入输出 | 4.1 | 是 |
| 表4-2 | 三个模型训练超参数 | 4.5/6.2 | 是；训练硬件型号 TODO |
| 表5-1 | 主要后端 API | 5.5 | 是 |
| 表5-2 | MySQL 核心表及用途 | 5.4 | 是 |
| 表6-1 | 独立负荷模型测试指标 | 6.3 | 是 |
| 表6-2 | 负荷模型与基线对比 | 6.3 | 是；已按相同目标索引重算，建议后续固化脚本和结果文件 |
| 表6-3 | 独立电价模型测试指标 | 6.4 | 是 |
| 表6-4 | PV v2 验证集与测试集指标 | 6.5 | 是 |
| 表6-5 | PV v2 与 naive-24 对比 | 6.5 | 是 |
| 表6-6 | 系统测试结果 | 6.7 | 是；浏览器 E2E TODO |
| 表7-1 | 项目局限与后续改进 | 7.2/7.3 | 是 |

## 8. 正式制图 TODO

- TODO：新增 `make_split_model_figures.py` 或等价脚本，保存独立负荷/电价测试预测数组并重画 fig17—fig29。
- TODO：新增 PV v2 论文图脚本，避免继续调用 `make_pv_figures.py` 的 PV v1 权重和旧特征。
- TODO：所有新图记录生成脚本、数据文件、模型 SHA-256 和生成日期。
- TODO：确认学校要求的图片宽度、DPI、中文字体、图题位置和颜色打印要求。
- TODO：系统截图统一使用最终版本、相同浏览器尺寸和无个人信息画面。
