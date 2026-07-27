# 新英格兰地区光伏发电预测系统

> 基于 PVLib 工业级物理仿真 + 深度学习模型的光伏功率预测

## 项目概览

本项目使用 NREL PVLib PVWatts 物理模型对新英格兰地区 6 个城市的气象数据进行光伏发电功率仿真，生成高质量训练数据集，并使用 4 种深度学习模型 (LSTM, BiGRU, TCN, Transformer) 进行光伏功率预测。

### 技术栈

| 组件 | 技术 |
|------|------|
| 气象数据 | Open-Meteo ERA5 再分析数据 (2019-2024) |
| PV 仿真 | NREL PVLib Python (PVWatts v5 模型) |
| 深度学习 | PyTorch (LSTM, BiGRU, TCN, Transformer) |
| 系统容量 | 500 kWp 固定支架光伏电站 |

### 覆盖城市

| 城市 | 州 | 纬度 | 经度 | 倾角 |
|------|----|------|------|------|
| Boston | MA | 42.36 | -71.06 | 37° |
| Hartford | CT | 41.77 | -72.67 | 37° |
| Providence | RI | 41.82 | -71.41 | 37° |
| Portland | ME | 43.66 | -70.26 | 39° |
| Manchester | NH | 43.00 | -71.45 | 38° |
| Burlington | VT | 44.48 | -73.21 | 39° |

---

## 目录结构

```
solar_data/
├── README.md                          # 本文件
├── requirements.txt                   # Python 依赖
│
├── download_nsrdb.py                  # 气象数据下载 (Open-Meteo API)
├── process_data.py                    # 数据清洗、去重、异常值检测
├── analyze_data.py                    # 统计分析、相关性、特征重要性
├── generate_pv_power.py               # PVLib PVWatts 光伏功率仿真
│
├── raw/                               # 原始气象数据 (6城市 × 6年 = 36 CSV)
│   ├── Boston_2019.csv
│   ├── Boston_2020.csv
│   └── ...
│
├── new_england_solar_dataset.csv      # 清洗后的气象数据集 (37 MB)
├── new_england_pv_dataset.csv         # PVLib 仿真后的完整数据集 (51 MB)
│
├── figures/                           # 可视化图表
│   ├── correlation_heatmap.png
│   ├── feature_importance.png
│   ├── weather_distributions.png
│   ├── radiation_distributions.png
│   ├── ghi_diurnal_by_month.png
│   ├── ghi_diurnal_by_city.png
│   ├── ghi_typical_day.png
│   ├── annual_ghi_trend.png
│   ├── annual_ghi_total.png
│   ├── city_yearly_ghi.png
│   ├── monthly_irradiance_components.png
│   └── seasonal_ghi_heatmap.png
│
├── reports/                           # 分析报告
│   ├── statistical_report.txt
│   ├── correlation_matrix.csv
│   ├── feature_importance.csv
│   ├── data_processing_report.json
│   └── pvlib_simulation_report.json
│
└── pv_training/                       # 模型训练代码
    ├── config.py                      # 训练配置 (自动检测 GPU/CPU)
    ├── models.py                      # 模型定义 (LSTM, BiGRU, TCN, Transformer)
    ├── data_preparation.py            # 特征工程、序列构建、归一化
    ├── train.py                       # 训练主脚本 (支持 GPU 混合精度)
    ├── TRAINING_PLAN.md               # 企业级训练方案文档
    ├── processed/                     # 预处理后的数据 (自动生成, .gitignore)
    ├── saved_models/                  # 训练好的模型 (自动生成, .gitignore)
    ├── outputs/                       # 评估报告和图表 (自动生成, .gitignore)
    └── logs/                          # 训练日志 (自动生成, .gitignore)
```

---

## 快速开始

### 1. 环境安装

```bash
# 克隆仓库
git clone https://github.com/ygz1111/OOOO.git
cd OOOO/solar_data

# 安装依赖
pip install -r requirements.txt

# 安装 PyTorch (选择其一)
# CPU 版本:
pip install torch --index-url https://download.pytorch.org/whl/cpu

# GPU 版本 (CUDA 12.1):
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

### 2. 数据准备 (可选 — 已包含数据集)

如果需要重新下载和处理数据:

```bash
# 步骤 1: 下载气象数据 (6城市 × 2019-2024)
python download_nsrdb.py

# 步骤 2: 数据清洗和处理
python process_data.py

# 步骤 3: 数据分析
python analyze_data.py

# 步骤 4: PVLib 光伏功率仿真
python generate_pv_power.py
```

> **注意**: 仓库已包含处理好的数据集 (`new_england_pv_dataset.csv`)，可直接进入训练步骤。

### 3. 模型训练

```bash
cd pv_training

# 运行训练 (自动检测 GPU/CPU)
python train.py
```

训练脚本会自动:
- 检测是否有 GPU (CUDA)
- GPU: 使用大模型 + 混合精度 + 大 batch (512)
- CPU: 使用轻量模型 + 大 batch (256)
- 训练 4 个模型 (LSTM, BiGRU, TCN, Transformer)
- 加权集成
- 评估并保存结果

### 4. 训练结果

训练完成后，结果保存在:
- `pv_training/saved_models/` — 模型权重 (.pth)
- `pv_training/outputs/` — 评估报告 (evaluation_report.json)
- `pv_training/outputs/` — 训练历史 (training_history.json)
- `pv_training/logs/` — 训练日志

---

## GPU vs CPU 训练对比

| 指标 | CPU | GPU |
|------|-----|-----|
| 模型大小 | hidden=64, layers=2 | hidden=128, layers=3-4 |
| Batch Size | 256 | 512 |
| Epochs | 80 | 150 |
| 混合精度 | 否 | 是 (FP16 AMP) |
| 预计单模型耗时 | ~70 分钟 | ~10-15 分钟 |
| 4 模型总耗时 | ~5 小时 | ~40-60 分钟 |

### 强制使用 CPU

如需在 GPU 机器上强制使用 CPU 训练 (用于对比):

```python
# 编辑 pv_training/config.py
FORCE_CPU = True  # 设为 True
```

---

## 数据集说明

### `new_england_pv_dataset.csv` (训练用主数据集)

| 列名 | 单位 | 说明 |
|------|------|------|
| timestamp | - | 时间戳 (America/New_York) |
| city | - | 城市名 |
| state | - | 州缩写 |
| latitude | ° | 纬度 |
| longitude | ° | 经度 |
| ghi | W/m² | 全球水平辐照度 |
| dni | W/m² | 直射法向辐照度 |
| dhi | W/m² | 散射水平辐照度 |
| temperature | °C | 2m 气温 |
| humidity | % | 相对湿度 |
| wind_speed | m/s | 10m 风速 |
| wind_direction | ° | 风向 |
| pressure | hPa | 地面气压 |
| cloud_type | % | 云量 |
| cloud_low/mid/high | % | 低/中/高云量 |
| precipitable_water | mm | 降水量 |
| pv_power | W | **PVLib 仿真的 AC 功率 (目标)** |
| pv_power_kw | kW | **PVLib 仿真的 AC 功率 (目标, kW)** |
| poa_irradiance | W/m² | 倾斜面辐照度 (PVLib 中间量, 训练时排除) |
| cell_temperature | °C | 组件温度 (PVLib 中间量, 训练时排除) |
| year/month/day/hour | - | 时间分量 |

### 训练特征 (21个)

模型使用以下特征进行预测 (排除了 PVLib 中间计算量以防止数据泄露):

- **太阳辐射**: ghi, dni, dhi
- **气象**: temperature, humidity, wind_speed, wind_direction, pressure, precipitable_water
- **云层**: cloud_type, cloud_low, cloud_mid, cloud_high
- **地理**: latitude, longitude
- **时间编码**: hour_sin/cos, month_sin/cos, doy_sin/cos

### 数据划分

| 集合 | 时间范围 | 用途 |
|------|----------|------|
| 训练集 | 2019-01 ~ 2023-06 | 模型训练 |
| 验证集 | 2023-07 ~ 2023-12 | 早停和超参数 |
| 测试集 | 2024-01 ~ 2024-12 | 最终评估 |

---

## PVLib 仿真参数

| 参数 | 值 | 来源 |
|------|----|------|
| 系统容量 | 500 kWp (DC) | - |
| 组件类型 | 多晶硅 | gamma_pdc = -0.004/°C |
| 逆变器效率 | 96% (CEC) | PVWatts 默认 |
| 系统损耗 | ~14% | PVWatts v5 默认 |
| 倾角 | 37-39° (≈纬度-5°) | NREL 推荐 |
| 方位角 | 180° (正南) | - |
| 温度模型 | SAPM | a=-3.56, b=-0.075, ΔT=3 |
| 天空散射 | Perez | 各向异性模型 |
| 入射角损失 | Physical | 物理模型 |

参考: [NREL PVWatts Calculator](https://pvwatts.nrel.gov/)

---

## 模型架构

### 1. BiLSTM + Attention
- 双向 LSTM + 注意力机制 + LayerNorm
- 适合捕捉长期时序依赖

### 2. BiGRU
- 双向 GRU + LayerNorm
- 轻量级, 训练速度快

### 3. TCN (Temporal Convolutional Network)
- 因果膨胀卷积 + 残差连接
- 并行计算效率高

### 4. Transformer
- 自注意力机制 + 可学习位置编码
- 适合长序列建模

### 集成策略
- 基于验证集损失的 softmax 加权平均
- 权重: `w_i = exp(-loss_i * 10) / Σ exp(-loss_j * 10)`

---

## 许可证

数据来源: Open-Meteo (ERA5), NREL PVLib (开源)
