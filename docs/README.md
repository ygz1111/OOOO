# 智能电网负荷预测系统

> **给 AI 助手的说明**：本文档是项目的完整索引。每个文件的作用、数据处理流程、模型架构、运行方式都在下面有详细说明。请先通读本文档，再开始工作。

---

## 一、项目概述

- **目标**：基于 ISO New England 电网数据（2023-2025），使用深度学习预测未来 24 小时系统负荷
- **数据**：3 年小时级数据，26,304 行，38 个特征
- **模型**：LSTM + Transformer + TCN 三模型集成
- **环境**：Python 3.10+, TensorFlow 2.x, scikit-learn, pandas, matplotlib
- **训练硬件**：需要 GPU（推荐 NVIDIA GPU，显存 4GB+）

---

## 二、项目结构总览

```
OOOOOO/
├── .gitignore                      # Git 忽略规则
├── README.md                       # 本文件
├── train.py                        # Colab 训练入口脚本
├── prepare_colab_data.ps1          # 一键打包数据的 PowerShell 脚本
│
├── datas/                          # 原始 Excel 数据（只读，不要修改）
│   ├── 2023_smd_hourly.xlsx        # 2023 年数据
│   ├── 2024_smd_hourly.xlsx        # 2024 年数据
│   └── 2025_smd_hourly.xlsx        # 2025 年数据
│
├── src/                            # 数据处理管道（6 步，全部完成）
│   ├── data_loader.py              # Step 1: 加载 3 年 Excel 并合并
│   ├── data_cleaner.py             # Step 2: 类型统一 + 夏令时处理 + 异常检测
│   ├── feature_engine.py           # Step 3: 时间特征 + 正余弦编码
│   ├── feature_constructor.py      # Step 4: 滞后/滚动/气象衍生特征
│   ├── data_splitter.py            # Step 5: 时间序列划分 + MinMaxScaler
│   ├── dataset_builder.py          # Step 6: 滑动窗口序列化 + tf.data
│   ├── evaluation.py               # [旧版] 评估可视化（已被 models/ 下替代）
│   └── model_definitions.py        # [旧版] 模型定义（已被 models/ 下替代）
│
├── models/                         # 模型训练代码（核心）
│   ├── config.py                  # 全局配置（超参数、路径、训练参数）
│   ├── lstm_model.py              # LSTM 模型定义 + 训练封装
│   ├── transformer_model.py       # Transformer 模型定义 + 训练封装
│   ├── tcn_model.py               # TCN 模型定义 + 训练封装
│   ├── ensemble.py                # 集成模型 + 评估器 + 训练工厂
│   ├── visualizer.py              # 可视化工具（7 类图表）
│   └── train_models.py            # 本地训练入口脚本
│
├── processed/                      # 数据处理产物（已完成，直接用于训练）
│   ├── step1_system_data.pkl       # 合并后系统数据 (26,304 行)
│   ├── step1_region_data.pkl       # 8 个区域数据
│   ├── step2_cleaned_data.pkl      # 清洗后数据（连续时间序列）
│   ├── step2_anomaly_report.pkl    # 异常检测报告
│   ├── step2_cleaning_report.txt    # 清洗日志
│   ├── step3_time_features.pkl     # 时间特征数据 (42 列)
│   ├── step3_feature_info.pkl      # 特征配置信息
│   ├── step4_engineered_data.pkl   # 完整特征数据 (39 列)
│   ├── step4_feature_config.pkl    # 特征工程配置
│   ├── step4_model_data.pkl        # 最终建模数据 (38 特征 + 1 目标)
│   ├── step5_normalized_data.pkl   # 归一化后的训练/验证/测试集
│   ├── step5_scalers.pkl           # MinMaxScaler（特征 + 目标）
│   ├── step5_split_info.pkl        # 数据划分信息（时间点）
│   ├── step6_sequences.pkl         # 滑动窗口序列 (X, y)
│   └── step6_pipeline_config.pkl   # 数据管道配置
│
├── outputs/                        # 训练输出（.gitignore 忽略，训练后生成）
│   ├── saved_models/               # 模型权重文件
│   ├── *.png                       # 训练曲线、预测对比、误差分布等
│   └── evaluation_results.json     # 评估指标
│
├── docs/                           # 文档
│   ├── README.md                  # 本文件
│   ├── 项目方案.md                  # 企业级项目方案（API + 前端 + 部署）
│   └── Colab训练指南.md             # Google Colab 训练详细步骤
│
├── notebooks/                      # Jupyter Notebook（空，备用）
└── env_report.txt                  # [临时] 环境检查报告（可删除）
```

---

## 三、数据处理流程（已完成，不需重跑）

### 流程图

```
3 个 Excel 文件 (2023/2024/2025)
    │  src/data_loader.py (Step 1)
    ▼
合并系统数据 (26,304 行)
    │  src/data_cleaner.py (Step 2)
    ▼
清洗 + 夏令时处理 + 异常检测
    │  src/feature_engine.py (Step 3)
    ▼
时间特征 + 正余弦编码 (42 列)
    │  src/feature_constructor.py (Step 4)
    ▼
滞后/滚动/气象特征 (38 特征 + 1 目标)
    │  src/data_splitter.py (Step 5)
    ▼
时序划分 + MinMaxScaler 归一化
    │  src/dataset_builder.py (Step 6)
    ▼
滑动窗口序列 (lookback=168, horizon=24)
    │
    ▼
processed/step6_sequences.pkl ← 训练用这个文件
```

### 关键数据处理决策

| 问题 | 解决方案 | 所在文件 |
|------|---------|---------|
| `Hr_End` 类型不一致（int vs str） | 全部转 str 清洗后再转 int | `data_cleaner.py` |
| 夏令时 `02X` 标记 | 重复时间戳取平均值合并 | `data_cleaner.py` |
| 春季前调缺失小时 | `asfreq('h').interpolate()` 线性插值 | `data_cleaner.py` |
| 负电价异常值 | 确认为正常市场波动，保留 | `data_cleaner.py` |
| 时间周期性 | 正弦/余弦编码（hour, day, month） | `feature_engine.py` |
| 数据泄露 | 排除电价/调频/需求类特征 | `feature_constructor.py` |
| Scaler 泄露 | 仅在训练集 fit，验证/测试只 transform | `data_splitter.py` |

### 数据划分

| 集合 | 行数 | 占比 | 时间范围 |
|------|------|------|---------|
| 训练集 | 17,376 | 66.5% | 2023-01-01 ~ 2024-10-31 |
| 验证集 | 6,552 | 25.1% | 2024-11-01 ~ 2025-06-30 |
| 测试集 | 2,208 | 8.4% | 2025-07-01 ~ 2025-09-30 |

---

## 四、模型架构

### 4.1 LSTM 模型 (`models/lstm_model.py`)

```
Input (168, 38)
  → Bidirectional LSTM(128, return_sequences=True)
  → Dropout(0.2)
  → Bidirectional LSTM(64, return_sequences=False)
  → Dropout(0.2)
  → Dense(128, relu)
  → Dropout(0.2)
  → Dense(24)  # 输出 24 小时预测
```

- **特点**：双向 LSTM，捕捉前后文信息
- **损失函数**：Huber Loss（对异常值鲁棒）
- **优化器**：Adam (lr=1e-3)

### 4.2 Transformer 模型 (`models/transformer_model.py`)

```
Input (168, 38)
  → Dense(128)  # 投影到 d_model
  → 可学习位置编码
  → TransformerEncoder × 2 (4 heads, d_ff=256)
  → GlobalAveragePooling1D
  → Dense(128, relu) → Dropout
  → Dense(24)
```

- **特点**：多头注意力捕捉全局依赖，可学习位置编码
- **损失函数**：Huber Loss
- **优化器**：Adam (lr=1e-3)

### 4.3 TCN 模型 (`models/tcn_model.py`)

```
Input (168, 38)
  → Dense(64)  # 投影
  → TemporalBlock(filters=64, dilation=1)  # 因果膨胀卷积
  → TemporalBlock(filters=128, dilation=2)
  → TemporalBlock(filters=64, dilation=4)
  → GlobalAveragePooling1D
  → Dense(128, relu) → Dropout
  → Dense(24)
```

- **特点**：膨胀因果卷积，感受野指数增长，残差连接
- **损失函数**：Huber Loss
- **优化器**：Adam (lr=1e-3)

### 4.4 集成模型 (`models/ensemble.py`)

- **策略**：加权平均，权重按各模型验证集 Loss 的负指数分配
- **公式**：$w_i = \frac{e^{-L_i}}{\sum_j e^{-L_j}}$
- **训练工厂**：`EnsembleModelFactory.train_all_ensemble()` 一键训练三个模型 + 集成

---

## 五、训练配置

### 5.1 全局配置 (`models/config.py`)

| 参数 | 值 | 说明 |
|------|------|------|
| LOOKBACK | 168 (小时) | 回看窗口 = 7 天 |
| HORIZON | 24 (小时) | 预测步长 = 1 天 |
| N_FEATURES | 38 | 输入特征数 |
| EPOCHS | 100 | 最大训练轮数 |
| BATCH_SIZE | 64 | 批大小（本地可降到 32） |
| LEARNING_RATE | 1e-3 | 初始学习率 |
| PATIENCE | 10 | 早停耐心值 |

### 5.2 回调函数

所有模型共享：
- **EarlyStopping**：验证损失 10 epoch 不下降则停止，恢复最佳权重
- **ReduceLROnPlateau**：验证损失 5 epoch 不下降则 lr × 0.5（最低 1e-6）
- **ModelCheckpoint**：保存验证集最优权重

---

## 六、如何训练

### 方案 A：本地 GPU 训练（推荐）

```bash
# 1. 确认 GPU 可用
python -c "import tensorflow as tf; print(tf.config.list_physical_devices('GPU'))"

# 2. 运行训练
cd models
python train_models.py
```

训练完成后，结果保存在 `outputs/` 目录。

### 方案 B：Google Colab 训练

1. 本地运行 `prepare_colab_data.ps1` 打包数据
2. 上传到 Google Drive
3. 按 `docs/Colab训练指南.md` 操作

---

## 七、训练输出说明

训练完成后 `outputs/` 目录包含：

### 7.1 模型权重 (`outputs/saved_models/`)

| 文件 | 说明 |
|------|------|
| `lstm_model.h5` | LSTM 模型权重 |
| `transformer_model.h5` | Transformer 模型权重 |
| `tcn_model.h5` | TCN 模型权重 |
| `*_best.h5` | 各模型最佳 checkpoint |

### 7.2 可视化图表

每个模型（LSTM / Transformer / TCN / Ensemble）生成：

| 图表文件 | 内容 | 论文用途 |
|---------|------|---------|
| `*_training_history.png` | Loss + MAE 训练曲线 | 训练过程展示 |
| `*_prediction_24h.png` | 24 小时预测 vs 实际对比 | 核心结果图 |
| `*_prediction_7d.png` | 7 天连续预测对比 | 效果展示 |
| `*_error_distribution.png` | 误差直方图 | 误差分析 |
| `*_scatter.png` | 预测散点图 (含 R²) | 拟合度展示 |
| `*_hourly_error.png` | 每小时误差柱状图 | 误差分解 |
| `model_comparison_MAPE.png` | 四模型 MAPE 对比 | 对比分析 |
| `model_comparison_RMSE.png` | 四模型 RMSE 对比 | 对比分析 |
| `model_comparison_R2.png` | 四模型 R² 对比 | 对比分析 |

### 7.3 评估数据

`evaluation_results.json` 包含所有模型的 MAPE / RMSE / MAE / R² / MaxAE / 峰值 MAPE。

---

## 八、Git 协作说明

### 8.1 忽略规则 (`.gitignore`)

以下文件不纳入 Git：
- `outputs/` — 训练输出（每次不同）
- `*.h5` / `*.weights.h5` — 模型权重（文件大）
- `__pycache__/` — Python 缓存
- `env_report.txt` — 临时文件
- `*.zip` — 打包文件

**会纳入 Git 的文件**：
- 所有 `.py` 源代码
- `processed/*.pkl` — 数据处理产物（约 65MB，两台电脑共享）
- `docs/*.md` — 文档
- `.gitignore`

### 8.2 两台电脑协作流程

```bash
# 电脑 A（开发代码）：
git add .
git commit -m "修改了 LSTM 超参数"
git push origin main

# 电脑 B（训练）：
git pull origin main
cd models
python train_models.py
# 训练完成后将 outputs/ 手动拷回电脑 A（或用网盘）
```

---

## 九、旧版文件说明

`src/` 目录中有两个旧文件：
- `src/evaluation.py` — 早期版本的评估可视化，已被 `models/ensemble.py` + `models/visualizer.py` 替代
- `src/model_definitions.py` — 早期版本的模型定义，已被 `models/lstm_model.py` 等替代

这两个文件保留仅供参考，**训练时不使用**。

---

## 十、依赖环境

```
Python >= 3.10
tensorflow >= 2.12
numpy
pandas
scikit-learn
matplotlib
```

安装命令：
```bash
pip install tensorflow numpy pandas scikit-learn matplotlib
```

GPU 版本（NVIDIA）：
```bash
pip install tensorflow[and-cuda]  # TensorFlow 2.14+
```

---

## 十一、当前状态与下一步

| 模块 | 状态 | 说明 |
|------|------|------|
| 数据处理 | ✅ 完成 | 6 步全部跑通，产物在 `processed/` |
| 模型代码 | ✅ 完成 | 3 模型 + 集成 + 可视化 |
| 训练脚本 | ✅ 完成 | 本地 + Colab 两种方式 |
| 文档 | ✅ 完成 | README + 项目方案 + Colab 指南 |
| 模型训练 | ⏳ 待执行 | 需要在 GPU 电脑上运行 |
| 后端 API | 🔲 未开始 | 训练完成后进行 |
| 前端可视化 | 🔲 未开始 | 后端完成后进行 |
| Docker 部署 | 🔲 未开始 | 最终阶段 |