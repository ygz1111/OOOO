# 光伏预测论文图表索引（PV FIGURES）

数据: ISO-NE BTM PV(2014-2026-04) + Open-Meteo ERA5 辐照/云量 + SMD 气象 | 81,768 行
切分: 训练 2017→2025-10(77,424) | 验证 2025-11~12(1,464) | 测试 2026-01~04(2,880)
模型: GRU-128(96h→24h), 100 epochs, 目标=归一化 PV(p.u.)

## EDA (pv01-pv10)

- pv01_overview.png - 归一化光伏出力序列(2017-2026)与日均线
- pv02_monthly_box.png - 按月光伏出力分布箱线
- pv03_seasonal_curve.png - 四季平均日光伏曲线
- pv04_pv_vs_radiation.png - 光伏出力 vs 太阳辐照(GHI)散点
- pv05_pv_vs_cloud.png - 光伏出力 vs 云量散点
- pv06_coszen_response.png - 晴空响应：出力 vs 太阳高度
- pv07_zone_summer.png - 夏季八分区日光伏曲线
- pv08_capacity_growth.png - MW 装机增长 vs 归一化出力稳定
- pv09_heatmap_month_hour.png - 月×时 出力热力图
- pv10_solstice_days.png - 二分二至日曲线对比

## 模型结果 (pv11-pv17, 测试集 2026-01..04)

- pv11_loss_curves.png - 训练/验证损失随轮次
- pv12_test_overlay.png - 测试期第1步预测对照
- pv13_sunny_day.png / pv13_cloudy_day.png - 晴/阴天 24h 预测对照
- pv14_scatter.png - 预测-实际散点(白天)
- pv15_error_by_step.png - 各步长白天 MAE
- pv16_error_by_hour.png - 各钟点白天 MAE
- pv17_model_vs_naive.png - 模型 vs naive-24 白天 MAE

## 指标速查 (runs/pv_v1/metrics.json)

- 测试全时段 MAE 0.01821 / RMSE 0.03957
- 测试白天 MAE 0.03902 (nMAE 0.17913)
- naive-24 白天 MAE(测试) 0.10909
- 验证白天 MAE 0.03764 | 训练轮数 100