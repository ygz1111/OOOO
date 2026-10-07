# CAISO 光伏训练任务状态

本目录是独立的 CAISO Solar Actual 未来 24 小时预测实验。禁止修改生产前端、后端、数据库、ISO-NE 模型、已有数据和缩放器。

## 当前阶段

- 官方 OASIS Solar ACTUAL 样本、字段和 UTC 小时边界已核验，23/25 小时 DST 日已实际验证；来源说明见 `logs/source_probe/SOURCE_REVIEW.md`。
- 用户于2026-10-04明确确认 OASIS Solar ACTUAL 三个Trading Hub汇总标签、完整真实数据交集和Validation选型；**下载、Dataset、Baseline、Colab T4三模型正式训练、Validation选型、Test末次评价、Windows重载和交付验收均已完成。**标签命名为“CAISO OASIS Solar Actual Generation / CAISO OASIS 区域太阳能实际发电功率”。
- 正式训练资产必须写入新的数据集/运行目录，不覆盖已有文件。
- 使用 UTC 连续物理小时建立序列，America/Los_Angeles 用于本地日历、划分和显示，保留 DST 的 23/25 小时日。
- 未来输入使用历史预报，记录初始化及可用性假设，禁止用未来实况冒充预报。
- GRU、TCN-GRU、TCN-GRU-Attention 共用数据划分、缩放器、目标索引和指标。
- 最终模型按 Validation MAE 选择；Test 用于冻结候选后的末次评价，不用于选型或调参。

## 当前可访问的训练环境

2026-10-04 实际检查：

- Windows 可见显示设备为 AMD Radeon (TM) Graphics，未发现 NVIDIA nvidia-smi。
- Windows 已有 Python 3.11.16 / TensorFlow 2.16.1；GPU 列表为空，TensorFlow CUDA build 为 false。该环境仅用于代码和保存加载 smoke test，不修改其依赖。
- 可访问 WSL Ubuntu，但默认 Python 为 3.14.4；没有找到用户先前说明的 Python 3.10 TensorFlow 环境，WSL NVIDIA 库/设备未检出。
- WSL 已有 Google Colab CLI 0.6.0；本轮成功分配独立 Tesla T4，Python 3.13.15 / TensorFlow 2.20.0 CUDA 环境下 GPU 运算及三个模型的数学检查、新进程保存加载均通过。
- T4 测试输出已下载到 `results/smoke_t4/verified_20261004_0938/`，测试会话已释放；后续独立正式训练会话也已在下载验收后释放。

三个候选的早期数学检查输出为 `(2,24,1)`，梯度有限，新进程重载最大差异均为 0；这些早期检查使用测试维度，不能代替正式数据精度评价。正式模型使用past36/future35特征，后续真实Test特征重载检查见下方正式运行结果。现有15个生产资产做SHA256核验，全部保持不变。

本次实际检测结果只描述工具当前能访问的环境，不否定用户其他电脑/环境的配置。

## 验收结论

研究资产与重载 PASS；79项独立数据检查及178项训练资产检查全部通过。最终GRU按Validation MAE 611.22 MW选定；Test MAE 814.83 MW，高于24物理小时持久性基线602.32 MW，不能宣称超过基线。GRU后期存在过拟合迹象，已早停并恢复第21轮最佳验证检查点。

实时接入尚未具备：OASIS Actual逐条首次发布时间、ERA5历史输入在线可得性和GFS历史预报发布上界假设未实证验证；本轮没有接入现有系统。

## 正式运行

- Run：caiso_v1_20261004T150045Z；Colab session：caiso-pv-formal-20261004-r2。
- Dataset：data/processed/caiso_solar_actual_era5_gfs_day2_96x24_20261004_v1；Train/Val/Test=17101/697/882，past36/future35。
- 冻结包SHA256：3dbc5a5cacbce2851f5d653c205647b35c964745f5767274972ad2eb72d65b35。
- 正式结果目录：results/runs/caiso_v1_20261004T150045Z；最终模型：models/caISO_pv_final.keras。
- 最终GRU Test：MAE=814.828251 MW，RMSE=1373.451397 MW，R²=0.969787，白天MAPE=13.702173%。
- 三模型正式训练总计770.43秒；实际Tesla T4 / TensorFlow2.20.0 / batch64，33/33/35轮，没有本地正式训练。
- 云端与Windows隔离TensorFlow2.20新Python进程重载均PASS，最大差0.00300247 MW，输出(2,24,1)。
- 正式归档已下载，ZIP CRC与SHA检查PASS，SHA256=5618bd6d982a61aac7be156adba9b9de711147d34893ba7b4bf7386a2803f255。
- 独立训练会话caiso-pv-formal-20261004-r2已释放。15个现有生产模型/缩放器SHA核验全部未变。
- 最终中文报告见TRAINING_REPORT.md；原始云端报告、冻结配置与模型保留在运行目录。
