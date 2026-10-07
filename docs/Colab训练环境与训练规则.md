# Google Colab TensorFlow 训练规则

## 环境分工

- 本机 Windows/WSL：代码开发、数据准备、测试、资产接入。
- Google Colab GPU：正式 TensorFlow/Keras 模型训练。
- 正式训练前必须使用 `tf.config.list_physical_devices("GPU")` 确认 GPU 可见。

## 当前模型任务

- 负荷：过去 168h + 未来 24h 已知特征 -> 未来 24h MW。
- 电价：过去 168h + 未来 24h 已知特征 -> 未来 24h P10/P50/P90。
- 光伏：过去 96h + 未来 24h 气象/太阳特征 -> 未来 24h 光伏出力。

## 数据规则

1. 严格按时间切分训练、验证、测试集，不得随机切分时间序列。
2. scaler 只允许在训练集上拟合。
3. Lag/Rolling 特征只能使用预测时刻之前可获得的数据。
4. 测试集不得用于调参、早停或选择 checkpoint。
5. 固定随机种子，并保存数据时间范围、特征列顺序、版本和训练指标。

## 产物规则

每个正式模型至少保存权重、scaler、特征列顺序、lookback/horizon、数据时间范围和完整测试指标。

接入生产前，将验收后的资产复制到 `backend/models/tf_assets/`，运行 `backend/scripts/check_runtime.py` 和生产服务测试。未经验证的 checkpoint 不得直接覆盖生产资产。
