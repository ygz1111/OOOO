# Colab T4 训练入口

本实验不依赖现有前端、FastAPI、数据库或 ISO-NE 权重。当前所有模型 smoke 仅验证数学接口，不能作为 CAISO 正式训练结果。

## 前置条件

1. 官方 Solar Actual 样本和定义已经用户确认，数据集目录包含根代理记录的 `data_approval.json`。脚本不会自行产生 approved 记录。
2. 使用完整的独立 `experiments/caiso_pv/` 目录。数据位于 `data/processed/<dataset_id>/`，包括 `dataset.npz`、三个 scaler JSON、`feature_config.json`、`split_info.json`。
3. 未来天气仅接受 `forecast_single_run` 或 `forecast_fixed_lead_day2`，每个窗口记录的可用时间上界必须不晚于 origin。固定提前量历史预报的发布延迟可能采用已记录的保守假设，不能把检查通过称为首次发布时间已实证。未说明的事后实际天气不能冒充未来天气预报。
4. Colab 运行时选择 T4 GPU。正式入口会检查设备；不会修改本地 TensorFlow 环境。

## 依赖与版本兼容

独立训练/重载环境约束见 `../requirements-training.txt`：TensorFlow 2.20、Keras≥3.10。它是兼容范围，不是实测 Colab 版本锁。实际 job 保存 `logs/dependencies.json` 和 `logs/requirements-lock.txt`；正式训练与加载应优先复用其中的 TensorFlow/Keras 版本。

T4 TensorFlow 2.20 保存的数学 `.keras` 在旧 TensorFlow 2.16.1 中直接加载曾因 `Orthogonal` 初始化器的 `shared_object_id` 配置失败。不能将跨版本加载写成 PASS，也不修改原生 `.keras` 权重/配置来掩盖兼容问题。不升级生产环境；本地正式重载应使用独立的 TensorFlow 2.20 环境。当前未进行额外的降版本兼容导出。

## 自动正式 job 包装

`colab_formal_job.py --config <job_config.json>` 接收下面 JSON。ZIP 采用独立实验根的相对布局：`scripts/*` 与 `data/processed/<dataset_id>/*`，不包含生产 assets 或 `experiments/caiso_pv` 前缀。根执行器负责打包、上传、启动和下载。

```json
{
  "archive_path": "/content/<唯一bundle>.zip",
  "workspace": "/content/caiso_pv_formal_<唯一run_id>",
  "dataset_relative": "data/processed/<dataset_id>",
  "run_id": "<唯一run_id>",
  "training": {"batch_size": 64, "epochs": 100, "patience": 12, "seed": 42, "learning_rate": 0.001, "dropout": 0.15, "loss": "huber"},
  "snapshot_interval_seconds": 300
}
```

workspace 必须全新；已有 workspace、run 和结果包拒绝覆盖。训练命令不缓冲 stdout，每轮同时输出 train/val loss、学习率、epoch 秒数与累计耗时，并保存 `logs/train_stdout.txt`。包装保存真实 NPZ 压缩大小及数组解压大小用于估算内存。周期日志包可以提前下载，避免读取正在写的模型 checkpoint；结束时成功与失败都打包结果和错误日志。结果为 `/content/caiso_pv_formal_<run_id>_results.zip`，含独立脚本、运行目录和实际依赖；不重复打包巨大输入 dataset，不停止 Colab session。

## 数学 smoke（不需要官方训练数据）

```python
import subprocess, sys
subprocess.run([
    sys.executable, "experiments/caiso_pv/scripts/smoke.py",
    "--output-dir", "experiments/caiso_pv/results/smoke/<唯一的新目录名>",
], check=True)
```

三种模型分别检查 96×Fp 与 24×Ff 输入、24×1 输出、有限梯度、一小步数学优化和新 Python 进程重载。随机张量及 identity scaler 明确标为 SMOKE_ONLY，不用于 baseline、正式模型选择或精度报告。

## 已确认数据后的正式训练

```python
import subprocess, sys
subprocess.run([
    sys.executable, "experiments/caiso_pv/scripts/colab_run.py",
    "--dataset-dir", "experiments/caiso_pv/data/processed/<已确认dataset_id>",
    "--run-dir", "experiments/caiso_pv/results/runs/<唯一的新run_id>",
    "--epochs", "100", "--patience", "12", "--batch-size", "64",
], check=True)
```

所有参数、scaler、划分和输入顺序一致。三个模型均依 Validation loss 选最佳 epoch；模型间依 Validation MAE 选 Final。随后 Test 对 baseline 和三种模型统一只评价一次。该协议避免根据 Test 反复调参；若用户选择其他最终协议，应先记录明确决定再正式训练。

显存不足时自动将所有候选模型统一改用较小 batch 并重新开始比较，保留失败 attempt，不覆盖已有目录。OOM 最低 batch 为 8；若仍失败会保存异常并退出，不能将失败视为成功。长时间任务应使用稳定存储；Colab 断连不能保证运行会持续。

## 正式输出

run 内保存：

- `models/{gru,tcn_gru,tcn_gru_attention}/best.keras`
- `models/caISO_pv_final.keras` 和同权重兼容副本 `models/final.keras`
- `scalers/{past,future,target}_scaler.json`
- `feature_config.json`、`model_config.json`、`split_info.json`、`data_approval.json`
- `training_plan.json`（fit 前保存）、`training_history.json`、`validation_metrics.json`、`metrics.json`
- `results/test_predictions.csv`（有 origin、带 UTC 偏移的 Pacific timestamp 和 horizon）及三模型明细
- loss curve、首个 Test origin 的真实/预测 24h 曲线、24h horizon error curve
- `reload_check.json`、`TRAINING_REPORT.md`

本实验目标规范名为 **CAISO OASIS Solar Actual Generation**，使用已确认的官方 OASIS Actual Solar 字段及 source，不将其解释成全 California 或所有屋顶光伏。signed 原始数值和线性输出均保留，不以零截断、夜间强制置零或删除负值改善指标。Persistence 为 24 个物理小时 lag，DST 当日可能不是相同当地墙钟小时；全部模型复用相同 Test origin/horizon 索引。

正式新进程重载使用首两个 Test 样本的原始特征，重新执行保存的 Train scaler、模型推理和 MW 逆变换，与训练结束时的标准化输出及 signed MW 同时比较。旧随机数学 smoke 仅验证其明确标注的标准化张量，不冒充正式原始特征验证。

重载相对容差为 `rtol=1e-4`。标准化绝对容差 `atol_scaled=1e-5` 换算为 `atol_mw=atol_scaled×target_scaler.scale[0]`；输出记录两种单位的容差，兼容字段 `atol` 保留标准化含义，不采用随意放大的 MW 阈值。

96 小时历史的数学时间索引不越界，不代表 Solar ACTUAL 在 origin 已发布。OASIS 旧规范可能次日发布，当前源无逐条 first-publication 时间；离线研究训练允许明确记录此限制，在线可得性不得由此推定。报告把研究资产 PASS 和实时接入条件分开，后者仍待同口径及时 Solar 或发布延迟策略核验。

## 独立离线推理

`infer.py` 接收保存顺序的原始 past/future feature arrays，先用 Train scaler transform，再一次输出 24 点 signed MW。NPZ 必须同时提供 `past_feature_names`、`future_feature_names`、`origin_ts`、`past_ts`、`target_ts`、`future_available_upper_bound_ts`：特征名称顺序与已保存配置完全一致，过去与未来分别覆盖96/24连续UTC小时，未来预报已可得时间不晚于origin。这些时间校验不能证明未提供发布时间的历史Solar实际值已在线可得。

未来 Solar 标签不得作为输入；任意新天气字段或顺序变化会被 shape/config 检查拒绝。这个脚本不接入现有 API。`.keras` 使用Keras原生内置层保存，没有Lambda或需要生产项目才能导入的自定义层；格式说明见[TensorFlow官方保存与加载文档](https://www.tensorflow.org/guide/keras/serialization_and_saving)。
