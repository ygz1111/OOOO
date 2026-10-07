# 光伏数据目录

本目录只保存光伏数据获取、清洗与 PVLib 数据集生成相关内容，不承担线上预测。

当前线上光伏预测统一使用 TensorFlow `pv_v1`（GRU-128）：

- 模型定义：`backend/models/tensorflow_load/tf_pv_models.py`
- 推理服务：`backend/realtime_api/tf_pv_service.py`
- 生产资产：`backend/models/tf_assets/pv_v1/`
- 输入窗口：过去 96 小时；输出：未来 24 小时

`pv_training/processed/` 内的大文件属于历史数据处理中间产物，不会被后端加载为模型。
