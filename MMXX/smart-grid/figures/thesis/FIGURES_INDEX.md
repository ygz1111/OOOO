# 毕业论文图表索引（FIGURES INDEX）

> 项目: ISO-NE 智能电网负荷+电价预测（TensorFlow, 24h ahead）
> 全部 PNG 位于本项目 `figures/thesis/`（WSL 与 C:\MMXX\smart-grid\figures\thesis\ 双备份）
> 图注同时给出中文建议（论文可用）与英文原名。dpi=150。

## 一、数据与探索性分析（fig01–fig16，适合"数据/特征分析"章）

| 文件 | 中文图题建议 | 内容 |
|---|---|---|
| fig01_rt_overview.png | 控制区实时负荷逐时序列（2024-01–2026-07） | 全时段负荷+日均线 |
| fig02_rt_by_month_box.png | 负荷月度分布箱线图 | 季节与极端值形态 |
| fig03_daily_profile_daytype.png | 工作日/周末/节假日平均日负荷曲线 | 日/周季节规律 |
| fig04_load_vs_temperature.png | 负荷-温度散点及其二次拟合 | 温度驱动的 U 形关系 |
| fig05_heatmap_hour_dow.png | 负荷的小时×星期热力图 | 双周期结构 |
| fig06_price_overview.png | 日前/实时电价逐时序列 | 价格波动与尖峰事件 |
| fig07_price_profile.png | 工作日/周末电价日曲线 | 电价日内形态 |
| fig08_price_hist.png | 日前/实时电价分布直方图 | 右偏分布与尖峰阈值 |
| fig09_da_rt_demand.png | 日前出清与实时负荷对比及偏差 | DA 基线与 RT 差异 |
| fig10_zone_profiles.png | 八个分区负荷日曲线 | 分区负荷特性 |
| fig11_zone_levels.png | 各分区平均负荷水平 | 分区规模差异 |
| fig12_station_weather.png | 八站点月均气温热力图 | 气象多站口径 |
| fig13_acf_load.png | 负荷自相关函数 | 日/周周期性证据 |
| fig14_holiday_effect.png | 主要节假日 vs 工作日负荷曲线 | 节假日效应 |
| fig15_split_timeline.png | 训练/验证/测试集划分时间轴 | 数据划分(无泄漏) |
| fig16_seasonal_profiles.png | 四季平均日负荷曲线 | 季节演变 |

## 二、模型训练与结果（fig17–fig29，适合"实验/结果分析"章）

| 文件 | 中文图题建议 | 内容 |
|---|---|---|
| fig17_loss_curves.png | 训练/验证损失随轮次变化 | 收敛过程（早停） |
| fig18_test_overlay_step1.png | 测试期 24h 提前第1步预测对照 | 整体贴合度 |
| fig19_day_spike_20260702.png | 尖峰日（07-02）负荷预测对照 | 极端日表现 |
| fig20_day_weekday_20260709.png | 工作日负荷预测对照 | 常规日表现 |
| fig21_day_weekend_20260712.png | 周末负荷预测对照 | 周末表现 |
| fig22_scatter_pred_actual.png | 预测-实际散点（R²） | 全步精度 |
| fig23_error_by_horizon.png | 误差随预测步长变化 | 24h 前瞻误差结构 |
| fig24_error_by_clock_hour.png | 各钟点预测误差 | 峰荷时段误差 |
| fig25_residual_hist.png | 负荷预测残差分布 | 残差正态性检验 |
| fig26_price_fan_spike.png | 尖峰日电价概率预测（p10/p50/p90） | 电价分位数 |
| fig27_price_fan_normal.png | 常规日电价概率预测带 | 电价分位数 |
| fig28_price_calibration.png | 电价分位数校准（名义 vs 实测覆盖） | 概率校准检验 |
| fig29_model_vs_baseline.png | 模型 vs DA 基线 MAE 对比 | 方法有效性 |

## 三、核心指标速查（runs/tf_v1/metrics.json，测试集=2026-07）

| 指标 | 数值 |
|---|---|
| 负荷 MAE / RMSE / MAPE | 402.0 MW / 559.4 MW / 2.62% |
| 负荷 R² | 0.9687 |
| 峰荷(17-20h) MAE | 399.3 MW |
| 电价 p50 MAE / RMSE | 14.72 / 26.55 $/MWh |
| 电价 p10–p90 覆盖率 | 0.822（名义 0.8）|
| 对照：DA 基线(测试) MAE | 762.7 MW（本模型低 47%）|
| 实际训练轮数 | 28 epochs（上限 80，验证早停）|
