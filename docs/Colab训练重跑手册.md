# TensorFlow 模型重跑手册

## 训练前

1. 核对数据时间范围、时区、缺失值和重复时间戳。
2. 核对 train/validation/test 为连续且互不重叠的时间区间。
3. 核对 scaler 只在训练集拟合。
4. 在 Colab 中确认 TensorFlow GPU 可用。
5. 为本次运行创建独立输出目录，不覆盖生产资产。

## 训练与选择

- 负荷、电价、光伏分别训练，不共享输出头和损失函数。
- 早停和 checkpoint 选择只使用验证集。
- 模型选择同时参考 MAE、RMSE、MAPE、峰值时段误差和分时段稳定性。
- 电价分位数模型额外检查 P10/P90 覆盖率与分位数顺序。
- 光伏模型额外检查白天误差，并确保夜间输出为 0。

## 验收

1. 在从未参与调参的测试集上生成完整指标。
2. 与朴素基线（昨日同小时/周期性基线）比较。
3. 重建模型后加载权重，确认输出 Shape 和数值有限。
4. 使用冻结样本做离线回归测试。
5. 接入实时特征服务后做 24h 在线链路验收。

## 接入位置

- 独立负荷/电价模型：`backend/models/tensorflow_load/tf_split_models.py`
- 光伏模型：`backend/models/tensorflow_load/tf_pv_models.py`
- 生产资产：`backend/models/tf_assets/`
- 服务加载：`backend/realtime_api/services/container.py`
- 资产检查：`backend/scripts/check_runtime.py`

生产资产替换后必须运行后端测试与前端构建；失败时恢复上一版已验收的 TensorFlow 资产。
