# 训练与交付代码核对

本文件是实现审阅记录，**不是正式 CAISO 精度报告或已训练模型验收结果**。正式数据下载、正式训练和 T4 实际依赖锁由根任务执行器完成。

目标规范名：**CAISO OASIS Solar Actual Generation**。保留官方 signed Actual Solar 标签，不对负值裁零或强制夜间为零；不把 OASIS 范围解释成全 California 或所有屋顶光伏。

原始附件的最终 22 项报告与最终模型/实时条件声明逐项核对如下：

| 项 | 交付内容 | 实现与资产依据 |
|---:|---|---|
| 1 | 数据来源 | feature_config 的 solar_label_source_id/input_sources；data_approval；报告来源段 |
| 2 | 数据时间范围 | requested_label_axis/effective_admitted_origins；split_info；报告时间表 |
| 3 | Solar 标签定义 | target_name/approved_label_definition；canonical OASIS Actual 标签 |
| 4 | 天气来源 | future_weather_kind/model/availability_basis、historical_weather_kind/note |
| 5 | 数据量 | 各分区 samples/target_points 与 rejected_windows；不混淆预测实例和唯一目标小时 |
| 6 | Train/Val/Test 时间 | split_info 半开区间及当地日界；24h 标签整窗分区校验 |
| 7 | 输入 Shape | 96×past、24×future；最终 7 站配置为 36/35 维，脚本按已保存配置检查 |
| 8 | 输出 Shape | 每个模型 `[batch,24,1]`；推理/新进程重复检查 |
| 9 | 最终特征 | feature_config 的明确顺序；Train-only scaler 字段顺序校验 |
| 10 | Baseline | fit 前计算 Train/Val；冻结模型后在同 Test index 比较 lag24 物理小时 |
| 11 | 三模型指标 | GRU、TCN-GRU、TCN-GRU-Attention；统一 Test metrics/CSV |
| 12 | 最佳模型 | 用户确认 Validation MAE 选型；绝不按 Test 选型或再次调参 |
| 13 | 最佳 epoch | 同一 val_loss checkpoint、EarlyStopping；history 与模型表 |
| 14 | 参数量 | count_params；强制 10 万–200 万；model_config 候选表 |
| 15 | 训练耗时 | epoch_seconds/elapsed_seconds 实时 JSON 输出；各候选与总耗时 |
| 16 | Test 指标 | signed 全天 MAE/RMSE/R²；Train 正值 P99×1% 且≥1MW 的 daylight MAPE |
| 17 | 24h 误差 | metrics.horizons 1–24 与 horizon_error.png；相同 origin/horizon 索引 |
| 18 | 过拟合分析 | 保存三候选 loss 曲线；最佳 epoch Train/Val gap 与明确局限 |
| 19 | 最终模型路径 | 新 run/models/caISO_pv_final.keras；原生资产不降版本改写 |
| 20 | Scaler 路径 | 新 run/scalers 三文件；只拟合 Train |
| 21 | Test CSV | timestamp/UTC/origin/actual_mw/predicted_mw/horizon，DST 重复小时保留不同偏移 |
| 22 | 重载 PASS | 新 Python 进程 raw Test 特征→保存 scaler→.keras→signed MW，与结束时结果比较 |
| 23 | Final PASS/FAIL、实时条件 | completed/failed 状态与 TRAINING_REPORT；离线资产 PASS 与在线可得性尚未验证分开 |

三候选均只使用独立新模型，不导入 ISO-NE 权重。默认配置没有变动：Adam、Huber、seed42、batch64、max100、patience12、dropout0.15、L2 1e-5、hidden128。OOM 才会统一减少三个模型的 batch，保存失败 attempt 和 OOM 记录；不覆盖已存在的 run。训练计划在 fit 前落盘，最终有效参数另记录。

所有候选完成并冻结后 Test 在该 run 中只评价一次；dataset.npz SHA256 先核对，独占 test_evaluation_started 标记阻止重复评价。Test 没有用于模型选择或超参数调整。

未来天气的记录上界≤origin 是代码检查；固定提前量产品的发布时间保守假设必须保留，不能当作实测首次发布时间。历史 Solar/天气重建的发布可得性尚未验证，因此此流程可以产出明确说明限制的离线研究模型，不能单凭时间无越界或 reload PASS 声称实时接入就绪。

正式 `.keras` 使用 TensorFlow 2.20/Keras 对应环境；旧 TF2.16 对 2.20 的数学 smoke 文件存在已实证反序列化失败。训练环境不升级生产环境；运行时真实版本保存为 dependencies.json/requirements-lock.txt，兼容范围另见 requirements-training.txt。

本轮必要验证：原有评价 7 条、分区/Train-only/批准门禁 8 条通过；新增原始特征重载/推理 3 条与安全 bundle 2 条通过；新增报告 1 条通过。36/35 输入数学模型形状与梯度 3 条此前已通过。它们均使用标注的数学 fixture，不训练真实 CAISO 模型，不生成正式精度结果。

重载容差另有 1 条专项验证通过：标准化 `atol=1e-5` 经 target scale=20 换算为 0.0002 MW；在数学输出 0 MW 时 0.00015 MW 差异接受、0.00030 MW 拒绝，`rtol=1e-4` 不变。重载 JSON 分别记录 atol_scaled/atol_mw，避免单位混用。
