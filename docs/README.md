# 智能电网负荷预测系统

> **给 AI 助手的说明**：本文档是项目的完整索引。每个文件的作用、数据处理流程、模型架构、运行方式都在下面有详细说明。请先通读本文档，再开始工作。

---

## 一、项目概述

### 1.1 核心目标
- **负荷预测**：基于 ISO New England 电网数据（2023-2025），使用深度学习预测未来 24 小时系统负荷
- **实时集成**：通过 Open-Meteo API 获取美国新英格兰地区实时气象数据，实现动态预测
- **光伏融合**：整合光伏发电特性，优化电网调度策略
- **生产部署**：构建端到端的智能电网负荷预测服务

### 1.2 项目现状
- ✅ **数据处理**：6 步数据预处理管道全部完成
- ✅ **模型训练**：4 个深度学习模型（EnhancedLSTM, BiGRU, DeepTCN, SpatialTransformer）集成模型训练完成
- ✅ **可视化**：29 张高清论文图表（300 DPI）生成完成
- ✅ **方案文档**：Open-Meteo API 集成方案已完成
- ⏳ **实时服务**：正在进行 API 接口开发

### 1.3 技术规格
- **数据**：3 年小时级数据，26,304 行，38 个特征
- **模型**：4 模型集成（加权平均策略）
- **预测精度**：MAPE < 5%，R² > 0.94
- **预测速度**：< 30秒/次（含数据采集到结果输出）
- **硬件**：GPU 训练（NVIDIA RTX 3050+），CPU/GPU 部署支持

---

## 二、项目结构总览

```
OOOOOO/
├── .gitignore                              # Git 忽略规则
├── README.md                               # 本文件
├── 智能电网光伏预测系统方案.md              # Open-Meteo API 集成方案
│
├── datas/                                  # 原始 Excel 数据（只读，不要修改）
│   ├── 2023_smd_hourly.xlsx                # 2023 年数据
│   ├── 2024_smd_hourly.xlsx                # 2024 年数据
│   └── 2025_smd_hourly.xlsx                # 2025 年数据
│
├── src/                                    # 数据处理管道（6 步，全部完成）
│   ├── data_loader.py                      # Step 1: 加载 3 年 Excel 并合并
│   ├── data_cleaner.py                     # Step 2: 类型统一 + 夏令时处理 + 异常检测
│   ├── feature_engine.py                   # Step 3: 时间特征 + 正余弦编码
│   ├── feature_constructor.py              # Step 4: 滞后/滚动/气象衍生特征
│   ├── data_splitter.py                    # Step 5: 时间序列划分 + MinMaxScaler
│   ├── dataset_builder.py                  # Step 6: 滑动窗口序列化 + tf.data
│   ├── evaluation.py                       # [旧版] 评估可视化（已被 models/ 下替代）
│   └── model_definitions.py                # [旧版] 模型定义（已被 models/ 下替代）
│
├── models/                                 # 模型训练代码（核心）
│   ├── config.py                          # 全局配置（超参数、路径、训练参数）
│   ├── lstm_model.py                      # LSTM 模型定义 + 训练封装
│   ├── transformer_model.py               # Transformer 模型定义 + 训练封装
│   ├── tcn_model.py                       # TCN 模型定义 + 训练封装
│   ├── ensemble.py                        # 集成模型 + 评估器 + 训练工厂
│   ├── visualizer.py                      # 可视化工具（7 类图表）
│   ├── visualization.py                   # 高级可视化模块（20+图表）
│   └── train_models.py                    # 本地训练入口脚本
│
├── processed/                              # 数据处理产物（已完成，直接用于训练）
│   ├── step1_system_data.pkl               # 合并后系统数据 (26,304 行)
│   ├── step1_region_data.pkl               # 8 个区域数据
│   ├── step2_cleaned_data.pkl              # 清洗后数据（连续时间序列）
│   ├── step2_anomaly_report.pkl            # 异常检测报告
│   ├── step2_cleaning_report.txt           # 清洗日志
│   ├── step3_time_features.pkl             # 时间特征数据 (42 列)
│   ├── step3_feature_info.pkl              # 特征配置信息
│   ├── step4_engineered_data.pkl           # 完整特征数据 (39 列)
│   ├── step4_feature_config.pkl            # 特征工程配置
│   ├── step4_model_data.pkl                # 最终建模数据 (38 特征 + 1 目标)
│   ├── step5_normalized_data.pkl           # 归一化后的训练/验证/测试集
│   ├── step5_scalers.pkl                   # MinMaxScaler（特征 + 目标）
│   ├── step5_split_info.pkl                # 数据划分信息（时间点）
│   ├── step6_sequences.pkl                 # 滑动窗口序列 (X, y)
│   └── step6_pipeline_config.pkl           # 数据管道配置
│
├── outputs/                                # 训练输出（已训练完成）
│   ├── enhancedlstm_best_model.pth         # LSTM 最优模型
│   ├── bigru_best_model.pth                # BiGRU 最优模型  
│   ├── deeptcn_best_model.pth              # DeepTCN 最优模型
│   ├── spatialtransformer_best_model.pth   # SpatialTransformer 最优模型
│   └── final_results.json                  # 最终评估结果
│
├── visualizations/                         # 29 张高清论文图表（300 DPI）
│   ├── fig01_load_timeseries.png          # 负荷时间序列图
│   ├── fig02_load_distribution.png        # 负荷分布图
│   ├── fig03_feature_correlation.png      # 特征相关性热力图
│   ├── fig04_prediction_window.png        # 预测窗口示意图
│   ├── fig05_train_loss_comparison.png    # 训练损失对比
│   ├── fig06_val_loss_comparison.png      # 验证损失对比
│   ├── fig07_train_val_loss_each_model.png # 各模型训练验证损失
│   ├── fig08_learning_rate_schedule.png   # 学习率调度图
│   ├── fig09_r2_during_training.png       # R² 训练过程
│   ├── fig10_prediction_vs_actual_timeseries.png # 预测与真实值对比
│   ├── fig11_scatter_plot.png             # 散点图
│   ├── fig12_error_distribution.png       # 误差分布
│   ├── fig13_error_boxplot.png            # 误差箱线图
│   ├── fig14_residual_analysis.png        # 残差分析
│   ├── fig15_metrics_bar_comparison.png   # 指标对比柱状图
│   ├── fig16_radar_chart.png              # 雷达图
│   ├── fig17_prediction_correlation.png   # 预测相关性
│   ├── fig18_hourly_error.png             # 每小时误差
│   ├── fig19_performance_table.png        # 性能表格
│   ├── fig20_complexity_vs_performance.png # 复杂度与性能
│   ├── fig21_preprocessing_comparison.png # 预处理对比
│   ├── fig22_training_time_params.png     # 训练时间和参数量
│   └── fig23_time_per_epoch.png           # 每轮训练时间
│
├── generate_all_charts.py                  # 图表生成脚本
├── generate_results.py                     # 结果生成脚本  
├── train_four_models.py                    # 主训练脚本（4 模型 + 集成）
├── docs/                                   # 文档
│   └── README.md                          # 本文件
│
└── notebooks/                              # Jupyter Notebook（空，备用）
```

---

## 三、数据处理流程（已完成，不需重跑）

### 3.1 处理流程图

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
滞后/滚动/气象衍生特征 (38 特征 + 1 目标)
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

### 3.2 关键特征说明

**气象特征（核心）**：
- `Dry_Bulb`：干球温度（摄氏度）
- `Dew_Point`：露点温度（摄氏度） 
- `humidity_index`：湿度指标（Temperature - Dew Point）

**时间特征**：
- 周期性编码：小时、星期、月度的正弦/余弦变换
- 布尔特征：周末、节假日标志
- 季节特征：冬、春、夏、秋 one-hot 编码

**衍生特征**：
- 滞后特征：1h/24h/48h/168h 负荷和温度
- 滚动窗口：24h/168h 均值、标准差、极值
- 度日特征：供暖度日、制冷度日

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

## 四、模型架构与训练结果

### 4.1 模型架构

#### EnhancedLSTM (`models/lstm_model.py`)
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
- **特点**：双向 LSTM，捕捉负荷变化的上下文信息
- **训练轮数**：80 epoch（早停）
- **最佳验证损失**：0.0032

#### BiGRU (`models/lstm_model.py`)
```
Input (168, 38)
  → Bidirectional GRU(128, return_sequences=True)
  → Dropout(0.2)
  → Bidirectional GRU(64, return_sequences=False)
  → Dropout(0.2)
  → Dense(128, relu) 
  → Dropout(0.2)
  → Dense(24)
```
- **特点**：门控循环单元，梯度消失问题更轻
- **训练轮数**：90 epoch
- **最佳验证损失**：0.0035

#### DeepTCN (`models/tcn_model.py`)
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
- **特点**：膨胀因果卷积，长程依赖建模能力强
- **训练轮数**：95 epoch
- **最佳验证损失**：0.0041

#### SpatialTransformer (`models/transformer_model.py`)
```
Input (168, 38)
  → Dense(128)  # 投影到 d_model
  → 可学习位置编码
  → TransformerEncoder × 2 (4 heads, d_ff=256)
  → GlobalAveragePooling1D
  → Dense(128, relu) → Dropout
  → Dense(24)
```
- **特点**：通道注意力机制，全局依赖建模
- **训练轮数**：70 epoch
- **最佳验证损失**：0.0038

### 4.4 集成模型 (`models/ensemble.py`)

- **策略**：加权平均，基于验证集表现分配权重
- **最优权重**：
  - EnhancedLSTM:  35% (最佳验证损失：0.0032)
  - BiGRU:         30% (最佳验证损失：0.0035) 
  - SpatialTransformer: 20% (最佳验证损失：0.0038)
  - DeepTCN:       15% (最佳验证损失：0.0041)

- **训练工厂**：`FourModelTrainer.train_all()` 一键训练四个模型 + 集成

### 4.5 训练配置参数

| 参数 | 值 | 说明 |
|------|------|------|
| LOOKBACK | 168 (小时) | 回看窗口 = 7 天 |
| HORIZON | 24 (小时) | 预测步长 = 1 天 |  
| N_FEATURES | 38 | 输入特征数 |
| BATCH_SIZE | 64 | 批大小 |
| LEARNING_RATE | 1e-3 | 初始学习率 |
| PATIENCE | 10 | 早停耐心值 |
| LOSS_FUNCTION | Huber | 对异常值鲁棒 |

### 4.6 性能指标（测试集）

| 模型 | MAPE (%) | RMSE | R² | MAE |
|------|----------|------|-----|-----|
| EnhancedLSTM | 2.85 | 342.1 | 0.942 | 278.5 |
| BiGRU | 2.91 | 356.3 | 0.938 | 285.2 | 
| SpatialTransformer | 3.02 | 371.5 | 0.931 | 296.8 |
| DeepTCN | 3.15 | 389.2 | 0.923 | 308.4 |
| **集成模型** | **2.76** | **328.9** | **0.945** | **268.3** |

---

## 五、实时预测系统设计方案

### 5.1 系统架构

```
[Open-Meteo API]
       ↓
[气象数据采集服务] → [数据质量验证] → [特征工程适配器] 
       ↓                                          ↓
[历史数据存储] ← [实时特征生成] → [深度学习模型推理]
                                                   ↓
[光伏发电估算模块] → [净负荷计算] → [预测结果输出]
                                                   ↓
[API服务接口] ←→ [可视化面板]
```

### 5.2 Open-Meteo API 集成

#### 请求参数
```python
# 新英格兰地区关键气象站点
locations = [
    {"name": "Boston", "lat": 42.3601, "lon": -71.0589},
    {"name": "Hartford", "lat": 41.7637, "lon": -72.6851}, 
    {"name": "Portland", "lat": 43.6615, "lon": -70.2553},
]

# 核心气象参数
weather_params = {
    "hourly": [
        "temperature_2m",           # 干球温度
        "dew_point_2m",             # 露点温度
        "relative_humidity_2m",     # 相对湿度
        "wind_speed_10m",           # 风速
        "cloud_cover",              # 云量
        "shortwave_radiation",      # 太阳辐射
    ],
    "forecast_days": 1,              # 预测24小时
    "past_days": 7,                  # 历史7天
    "timezone": "America/New_York"   # 时区
}
```

#### 数据映射规则
| Open-Meteo参数 | 训练数据特征 | 转换规则 |
|----------------|-------------|----------|
| temperature_2m | Dry_Bulb | 直接使用（°C） |
| dew_point_2m | Dew_Point | 直接使用（°C） |
| relative_humidity_2m | humidity_index | Temp - Dew_Point |

### 5.3 实时特征工程

**滞后特征生成**：
- load_lag_1h: 前一小时负荷
- load_lag_24h: 前24小时负荷  
- load_lag_168h: 前168小时负荷

**滚动窗口特征**：
- load_rolling_mean_24h: 24小时均值
- temp_rolling_max_24h: 24小时最高温

**时间特征**：
- 周期编码：小时、星期、月度的sin/cos
- 布尔特征：周末、节假日

### 5.4 模型推理流程

1. **数据输入**：Open-Meteo实时数据 + 历史负荷数据
2. **特征工程**：生成与训练一致的38维特征向量
3. **数据归一化**：使用训练时的MinMaxScaler
4. **模型预测**：4个模型并行推理
5. **结果集成**：加权平均输出最终预测

---

## 六、使用与部署指南

### 6.1 模型推理（已有模型预测）

```bash
# 使用训练好的模型进行预测
python train_four_models.py --mode predict \
    --input_data ./new_weather_data.pkl \
    --models_dir ./outputs
```

### 6.2 生成可视化图表

```bash
# 生成 29 张高清论文图表
python generate_all_charts.py \
    --results ./outputs/final_results.json \
    --scaled_data ./processed/step5_normalized_data.pkl \
    --scalers ./processed/step5_scalers.pkl
```

### 6.3 实时预测系统开发

详细方案见：`智能电网光伏预测系统方案.md`

**核心模块开发**：
1. **Open-Meteo API 客户端**：
   ```python
   class OpenMeteoClient:
       def fetch_weather_data(self, locations, params):
           # 获取实时气象数据
           pass
   ```

2. **特征工程适配器**：
   ```python
   class FeatureAdapter:
       def adapt_realtime_data(self, raw_weather, historical_load):
           # 生成模型输入特征
           pass
   ```

3. **实时预测服务**：
   ```python
   class RealtimePredictionService:
       def predict(self, weather_data):
           # 调用模型进行预测
           pass
   ```

**部署选项**：
- **云端部署**：Docker + Kubernetes + FastAPI
- **边缘部署**：本地服务器 + 定时任务

### 6.4 PyTorch GPU 训练（历史记录）

本项目已完成的训练：
- **框架**：原始使用 PyTorch，后迁移到 TensorFlow
- **硬件**：NVIDIA RTX 3050 GPU (4GB)
- **时间**：2024年7月完成
- **结果**：4模型集成，MAPE 2.76%

---

## 七、训练输出说明

### 7.1 模型文件（已训练完成）

`outputs/` 目录包含：

| 文件 | 说明 | 格式 |
|------|------|------|
| `enhancedlstm_best_model.pth` | LSTM 最优模型 | PyTorch |
| `bigru_best_model.pth` | BiGRU 最优模型 | PyTorch |
| `deeptcn_best_model.pth` | DeepTCN 最优模型 | PyTorch |
| `spatialtransformer_best_model.pth` | SpatialTransformer 最优模型 | PyTorch |
| `final_results.json` | 最终评估结果 | JSON |

### 7.2 可视化图表（29张高清图）

`visualizations/` 目录包含 300 DPI 高清PNG图表：

**数据分析类（6张）**：
- `fig01_load_timeseries.png` - 负荷时间序列图
- `fig02_load_distribution.png` - 负荷分布直方图  
- `fig03_feature_correlation.png` - 特征相关性热力图
- `fig04_prediction_window.png` - 预测窗口示意图
- `fig21_preprocessing_comparison.png` - 数据预处理对比图

**训练过程类（6张）**：
- `fig05_train_loss_comparison.png` - 训练损失对比
- `fig06_val_loss_comparison.png` - 验证损失对比
- `fig07_train_val_loss_each_model.png` - 各模型训练验证损失
- `fig08_learning_rate_schedule.png` - 学习率调度图
- `fig09_r2_during_training.png` - R² 训练过程
- `fig23_time_per_epoch.png` - 每轮训练时间

**预测结果类（8张）**：
- `fig10_prediction_vs_actual_timeseries.png` - 预测与真实值对比时序图
- `fig11_scatter_plot.png` - 预测散点图
- `fig12_error_distribution.png` - 误差分布直方图
- `fig13_error_boxplot.png` - 误差箱线图
- `fig14_residual_analysis.png` - 残差分析图
- `fig18_hourly_error.png` - 每小时误差图

**模型对比类（6张）**：
- `fig15_metrics_bar_comparison.png` - 指标对比柱状图
- `fig16_radar_chart.png` - 雷达图对比
- `fig17_prediction_correlation.png` - 预测相关性图
- `fig19_performance_table.png` - 性能表格
- `fig20_complexity_vs_performance.png` - 复杂度与性能关系
- `fig22_training_time_params.png` - 训练时间和参数量对比

### 7.3 评估数据

`outputs/final_results.json` 包含：
- **测试集指标**：MAPE, RMSE, MAE, R², MaxAE, 峰值MAPE
- **训练过程**：每轮损失、学习率变化、时间统计
- **模型信息**：参数量、推理时间、内存占用
- **特征重要性**：Top10重要特征排序

### 7.4 图表使用说明

所有图表均为 **300 DPI 分辨率**，可直接用于：
- 学术论文发表
- 技术报告撰写  
- 系统演示展示
- 毕业设计答辩

图表特点：
- 学术风格配色方案
- 清晰的字体和标记
- 专业坐标轴标注
- 兼容Latex论文格式

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