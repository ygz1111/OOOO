# 光伏发电功率预测 — 企业级训练方案

> 基于 PVLib 仿真数据集 `new_england_pv_dataset.csv`（315,648 行 × 28 列，6 城市 × 6 年）

---

## 一、数据集概况

| 维度 | 数值 |
|------|------|
| 总行数 | 315,648 行（6 城市 × 6 年 × 8760h） |
| 有发电行 | 150,654 行（白天，pv_power > 0） |
| 无发电行 | 164,994 行（夜间，pv_power = 0） |
| 城市数 | 6（Boston, Hartford, Providence, Portland, Manchester, Burlington） |
| 年份范围 | 2019-2024 |
| 时间分辨率 | 1 小时 |
| 特征列 | 24 列（含气象 + 时间 + POA + 组件温度） |
| 目标列 | `pv_power`（W）或 `pv_power_kw`（kW） |
| 装机容量 | 500 kWp / 城市 |

### 与负荷预测的关键差异

| 对比项 | 负荷预测（现有） | PV 预测（新） |
|--------|-----------------|--------------|
| 数据量 | 26,304 行（3年系统级） | 315,648 行（6城市6年） |
| 特征数 | 38 个（含负荷滞后特征） | ~20 个（纯气象特征） |
| 目标特性 | 24h 连续非零 | 昼夜分明（夜间恒为 0） |
| 周期性 | 日/周强周期 | 日/年强周期（日出日落） |
| 物理约束 | 无明确上限 | 逆变器限制 ≤ 480 kW |
| 数据泄露风险 | 滞后负荷特征安全 | **不可使用 POA/cell_temperature**（PVLib 计算的中间量） |

---

## 二、是否需要 GPU？

### 结论：不需要 GPU，CPU 完全可以胜任

### 理由分析

| 因素 | 分析 |
|------|------|
| **数据规模** | 315K 行 × 20 特征 ≈ 50 MB，内存毫无压力 |
| **序列长度** | PV 预测建议 lookback=24h（1天），远小于负荷预测的 168h |
| **模型参数量** | 单模型 50K-500K 参数，CPU 前向+反向传播 < 1s/batch |
| **训练时间估算** | LSTM 100 epoch ≈ 15-30 min（CPU），Transformer ≈ 20-40 min |
| **总训练时间** | 4 模型 × 30 min = ~2 小时（CPU 即可） |
| **对比 GPU** | GPU 仅快 3-5 倍，但 315K 数据规模下 CPU 并非瓶颈 |

### CPU 训练优化策略

```
1. 使用 PyTorch + torch.set_num_threads(N)  ← 充分利用多核
2. batch_size = 256-512                       ← CPU 大 batch 更高效
3. 使用 torch.utils.data.DataLoader           ← 多进程数据加载
4. 模型规模适中: hidden=64, layers=2          ← 避免过参数化
5. 混合精度训练 (可选): torch.cuda.amp        ← CPU 收益有限, 可选
6. 使用 ONNX Runtime 加速推理                  ← 部署阶段优化
```

---

## 三、特征工程方案

### 3.1 可用特征（安全，无泄露）

| 类别 | 特征 | 说明 |
|------|------|------|
| **太阳辐射** | `ghi`, `dni`, `dhi` | 核心特征，GHI 与 PV 功率相关性 0.941 |
| **气象** | `temperature`, `humidity`, `wind_speed` | 影响组件温度和效率 |
| **云层** | `cloud_type`, `cloud_low`, `cloud_mid`, `cloud_high` | 影响辐照度 |
| **其他气象** | `pressure`, `precipitable_water`, `wind_direction` | 辅助特征 |
| **时间编码** | `hour_sin/cos`, `month_sin/cos`, `day_of_year_sin/cos` | 周期性编码 |
| **地理位置** | `latitude`, `longitude` | 区分城市 |
| **滞后特征** | `ghi_lag_1h`, `ghi_lag_24h`, `pv_power_lag_24h` | 时间依赖 |

### 3.2 禁用特征（数据泄露）

| 特征 | 原因 |
|------|------|
| `poa_irradiance` | PVLib 计算的中间量，实时预测时不可知 |
| `cell_temperature` | PVLib 计算的中间量，实时预测时不可知 |
| `direct_horizontal` | 由 DNI 衍生，冗余 |
| `sunshine_duration` | 由 GHI 衍生，冗余 |

### 3.3 衍生特征

```python
# 时间周期编码（替代原始 hour/month）
df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
df['doy_sin'] = np.sin(2 * np.pi * df['day_of_year'] / 365)
df['doy_cos'] = np.cos(2 * np.pi * df['day_of_year'] / 365)

# 太阳高度角近似（无需天文计算）
df['solar_elevation_approx'] = 90 - abs(df['hour'] - 12) * 7.5  # 粗略估计

# GHI 滞后特征
df['ghi_lag_1h'] = df.groupby('city')['ghi'].shift(1)
df['ghi_lag_24h'] = df.groupby('city')['ghi'].shift(24)

# GHI 变化率
df['ghi_diff_1h'] = df.groupby('city')['ghi'].diff(1)
df['ghi_rolling_mean_3h'] = df.groupby('city')['ghi'].shift(1).rolling(3).mean()

# 温度滞后
df['temp_lag_1h'] = df.groupby('city')['temperature'].shift(1)

# PV 功率滞后（训练时可用，实时预测时用前一日实际发电量）
df['pv_power_lag_24h'] = df.groupby('city')['pv_power'].shift(24)
df['pv_power_lag_168h'] = df.groupby('city')['pv_power'].shift(168)  # 上周同时刻
```

### 3.4 数据清洗

```python
# 1. 仅保留有发电的时段（可选：白天过滤或全量训练）
# 建议: 全量训练，让模型自动学习夜间输出 0

# 2. 异常值处理
# PV 功率应为 [0, 480000] W
df = df[(df['pv_power'] >= 0) & (df['pv_power'] <= 500000)]

# 3. GHI 异常值
df = df[(df['ghi'] >= 0) & (df['ghi'] <= 1200)]

# 4. 按 city 分组处理，确保时间连续性
df = df.sort_values(['city', 'timestamp']).reset_index(drop=True)
```

---

## 四、数据划分策略

### 4.1 时间序列划分（防止数据泄露）

```
┌─────────────────────────────────────────────────────────────────┐
│                    2019  2020  2021  2022  2023  2024          │
├─────────────────────────────────────────────────────────────────┤
│  训练集 (72%)     ████████████████████████████                  │
│  验证集 (14%)                              ████                 │
│  测试集 (14%)                                   ████            │
└─────────────────────────────────────────────────────────────────┘
```

| 集合 | 时间范围 | 行数 | 用途 |
|------|---------|------|------|
| 训练集 | 2019-01 ~ 2023-06 | ~226K | 模型学习 |
| 验证集 | 2023-07 ~ 2023-12 | ~26K | 早停 + 超参调优 |
| 测试集 | 2024-01 ~ 2024-12 | ~52K | 最终评估 |

### 4.2 序列构建

```python
# 滑动窗口构建序列
LOOKBACK = 24   # 回看 24 小时（1天）
HORIZON  = 24   # 预测未来 24 小时
STRIDE   = 1    # 步长 1 小时

# 每个城市独立构建序列
# X: (lookback, n_features)  →  y: (horizon,)
```

### 4.3 归一化策略

```python
# 仅使用训练集统计量进行归一化
from sklearn.preprocessing import MinMaxScaler

# 特征归一化 (0-1 范围)
feature_scaler = MinMaxScaler()
feature_scaler.fit(train_features)  # 仅 fit 训练集

# 目标归一化
target_scaler = MinMaxScaler()
target_scaler.fit(train_target.reshape(-1, 1))

# 保存 scaler 供推理使用
import pickle
with open('pv_scalers.pkl', 'wb') as f:
    pickle.dump({'feature_scaler': feature_scaler, 
                 'target_scaler': target_scaler}, f)
```

---

## 五、模型架构方案

### 5.1 模型选择（4 模型集成）

复用现有项目的 4 模型架构，针对 PV 预测调整参数：

| 模型 | 架构 | 参数量 | CPU训练时间 | 适用场景 |
|------|------|--------|------------|---------|
| **LSTM** | BiLSTM(64) + Attention + Dense | ~100K | ~15 min | 中长期时序依赖 |
| **BiGRU** | BiGRU(64) + Dense | ~80K | ~12 min | 短期快速响应 |
| **TCN** | TCN([32,64,32]) + Dense | ~60K | ~10 min | 局部模式捕捉 |
| **Transformer** | Encoder(2层) + Dense | ~150K | ~25 min | 全局注意力 |

### 5.2 模型参数（CPU 优化版）

```python
PV_MODEL_CONFIGS = {
    # LSTM: 适中规模, BiLSTM + Attention
    "LSTM": {
        "input_size": 20,       # 特征数
        "hidden_size": 64,      # 隐藏单元 (CPU友好)
        "num_layers": 2,        # LSTM层数
        "output_size": 24,      # 预测步长
        "dropout": 0.2,
        "bidirectional": True,
    },
    
    # BiGRU: 轻量级, 训练快
    "BiGRU": {
        "input_size": 20,
        "hidden_size": 64,
        "num_layers": 2,
        "output_size": 24,
        "dropout": 0.2,
        "bidirectional": True,
    },
    
    # TCN: 卷积型, 适合捕捉局部模式
    "TCN": {
        "input_size": 20,
        "num_channels": [32, 64, 32],
        "kernel_size": 3,
        "dilations": [1, 2, 4, 8],
        "output_size": 24,
        "dropout": 0.2,
    },
    
    # Transformer: 全局注意力
    "Transformer": {
        "input_size": 20,
        "d_model": 64,          # CPU友好维度
        "nhead": 4,
        "num_layers": 2,
        "d_ff": 128,
        "output_size": 24,
        "dropout": 0.2,
    },
}
```

### 5.3 集成策略

```python
# 加权平均集成 (基于验证集表现)
# 权重 = softmax(-val_loss / temperature)
weights = np.exp(-val_losses / 0.01)
weights = weights / weights.sum()

# 或使用优化搜索最佳权重 (scipy.optimize)
from scipy.optimize import minimize

def ensemble_loss(w, preds, y_val):
    w = w / w.sum()
    ensemble = sum(p * wi for p, wi in zip(preds, w))
    return np.mean((ensemble - y_val) ** 2)

result = minimize(ensemble_loss, [1,1,1,1], args=(val_preds, y_val))
optimal_weights = result.x / result.x.sum()
```

---

## 六、训练配置

### 6.1 训练超参数

```python
TRAINING_CONFIG = {
    # 基础配置
    "epochs": 80,               # 最大轮数 (CPU建议不超过100)
    "batch_size": 256,          # CPU大batch更高效
    "learning_rate": 1e-3,      # 初始学习率
    "weight_decay": 1e-4,       # L2正则化
    
    # 早停
    "early_stopping_patience": 12,
    "early_stopping_min_delta": 1e-5,
    
    # 学习率调度
    "lr_scheduler": "cosine_annealing",  # 余弦退火
    "lr_min": 1e-6,
    "lr_warmup_epochs": 5,               # 预热
    
    # 损失函数
    "loss": "huber",            # Huber Loss (对异常值鲁棒)
    "delta": 1.0,               # Huber delta
    
    # CPU优化
    "num_workers": 4,           # DataLoader 进程数
    "num_threads": 8,           # PyTorch 线程数
    "pin_memory": False,        # CPU 不需要
    
    # 随机种子
    "random_seed": 42,
}
```

### 6.2 损失函数选择

```python
# Huber Loss: 对异常值鲁棒 (推荐)
criterion = nn.HuberLoss(delta=1.0)

# 或自定义 PV 专用损失: 同时惩罚白天和夜间误差
class PVLoss(nn.Module):
    """PV 预测专用损失: 白天和夜间分别加权"""
    def __init__(self, daytime_weight=1.0, nighttime_weight=0.3):
        super().__init__()
        self.daytime_weight = daytime_weight
        self.nighttime_weight = nighttime_weight
    
    def forward(self, pred, target, ghi):
        # ghi > 0: 白天, ghi = 0: 夜间
        daytime_mask = (ghi > 0).float()
        nighttime_mask = 1 - daytime_mask
        
        daytime_loss = F.huber_loss(pred * daytime_mask, target * daytime_mask)
        nighttime_loss = F.huber_loss(pred * nighttime_mask, target * nighttime_mask)
        
        return (self.daytime_weight * daytime_loss + 
                self.nighttime_weight * nighttime_loss)
```

### 6.3 评估指标

| 指标 | 公式 | 目标值 |
|------|------|--------|
| MAPE | mean(\|y-ŷ\|/y) × 100% | < 15% |
| RMSE | sqrt(mean((y-ŷ)²)) | < 30 kW |
| MAE | mean(\|y-ŷ\|) | < 20 kW |
| R² | 1 - SS_res/SS_tot | > 0.90 |
| nMAE | MAE / Capacity | < 6% |
| 日间MAPE | 仅白天时段的 MAPE | < 12% |
| 峰值MAPE | P95 时段的 MAPE | < 10% |

---

## 七、训练流程

```
┌──────────────────────────────────────────────────────────────┐
│                     训练流程 (7步)                            │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Step 1: 数据预处理                                          │
│  ├── 加载 new_england_pv_dataset.csv                         │
│  ├── 特征工程 (时间编码 + 滞后特征)                           │
│  ├── 数据清洗 (异常值过滤)                                    │
│  └── 保存 pv_processed.pkl                                   │
│                                                              │
│  Step 2: 序列构建与归一化                                     │
│  ├── 按 city 分组构建滑动窗口序列                              │
│  ├── 时间序列划分 (train 72% / val 14% / test 14%)           │
│  ├── MinMaxScaler 归一化 (仅 fit 训练集)                     │
│  └── 保存 pv_sequences.pkl + pv_scalers.pkl                  │
│                                                              │
│  Step 3: 模型构建                                             │
│  ├── LSTM (BiLSTM + Attention)                              │
│  ├── BiGRU (BiGRU + Dense)                                  │
│  ├── TCN (Temporal Convolutional Network)                   │
│  └── Transformer (Encoder + Dense)                          │
│                                                              │
│  Step 4: 逐模型训练                                           │
│  ├── Adam optimizer + Huber Loss                            │
│  ├── Cosine Annealing LR + Warmup                           │
│  ├── Early Stopping (patience=12)                           │
│  ├── 保存每个模型的 best_model.pth                           │
│  └── 记录训练历史 (loss/metrics)                             │
│                                                              │
│  Step 5: 集成与权重优化                                       │
│  ├── 在验证集上搜索最优权重                                   │
│  ├── 加权平均集成                                             │
│  └── 保存 ensemble_weights.pkl                               │
│                                                              │
│  Step 6: 测试集评估                                           │
│  ├── 计算整体指标 (MAPE/RMSE/MAE/R²)                         │
│  ├── 分时段评估 (日间/夜间/峰值)                              │
│  ├── 分城市评估                                              │
│  └── 生成评估报告 JSON                                       │
│                                                              │
│  Step 7: 可视化与导出                                         │
│  ├── 训练曲线 (loss/metrics)                                 │
│  ├── 24h 预测对比图                                          │
│  ├── 散点图 (预测 vs 实际)                                   │
│  ├── 误差分布图                                              │
│  ├── 分城市/季节分析                                         │
│  └── 模型对比柱状图                                           │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 八、文件结构

```
solar_data/
├── new_england_pv_dataset.csv          # 原始数据 (PVLib 仿真输出)
├── pv_training/                        # 训练工作目录
│   ├── config.py                       # 训练配置
│   ├── data_preparation.py             # Step 1-2: 数据预处理
│   ├── models.py                       # Step 3: 模型定义
│   ├── trainer.py                      # Step 4: 训练器
│   ├── ensemble.py                     # Step 5: 集成
│   ├── evaluator.py                    # Step 6: 评估
│   ├── visualizer.py                   # Step 7: 可视化
│   ├── train.py                        # 主入口
│   ├── processed/
│   │   ├── pv_processed.pkl            # 预处理后数据
│   │   ├── pv_sequences.pkl            # 序列数据
│   │   └── pv_scalers.pkl              # 归一化器
│   ├── saved_models/
│   │   ├── lstm_best.pth
│   │   ├── bigru_best.pth
│   │   ├── tcn_best.pth
│   │   ├── transformer_best.pth
│   │   └── ensemble_weights.pkl
│   ├── outputs/
│   │   ├── training_history.json
│   │   ├── evaluation_report.json
│   │   └── figures/
│   │       ├── training_loss.png
│   │       ├── prediction_24h.png
│   │       ├── scatter_plot.png
│   │       └── model_comparison.png
│   └── logs/
│       └── training.log
```

---

## 九、企业级增强功能

### 9.1 实验追踪

```python
# 使用 MLflow 追踪实验 (项目已有 MLflow 配置)
import mlflow

mlflow.set_experiment("pv_power_forecasting")

with mlflow.start_run(run_name="lstm_v1"):
    mlflow.log_params({"model": "LSTM", "hidden": 64, "lr": 1e-3})
    mlflow.log_metric("val_mape", val_mape)
    mlflow.log_metric("val_rmse", val_rmse)
    mlflow.log_artifact("saved_models/lstm_best.pth")
```

### 9.2 超参数搜索

```python
# 使用 Optuna 进行贝叶斯优化
import optuna

def objective(trial):
    hidden = trial.suggest_int("hidden", 32, 128)
    dropout = trial.suggest_float("dropout", 0.1, 0.4)
    lr = trial.suggest_float("lr", 1e-4, 1e-2, log=True)
    
    model = build_lstm(hidden=hidden, dropout=dropout)
    val_loss = train_and_evaluate(model, lr=lr)
    return val_loss

study = optuna.create_study(direction="minimize")
study.optimize(objective, n_trials=20)  # CPU 可跑 20 次
```

### 9.3 模型版本管理

```python
# 保存模型时附带元数据
model_metadata = {
    "model_type": "LSTM",
    "version": "v1.0",
    "training_date": "2024-01-15",
    "data_range": "2019-2023",
    "features": feature_list,
    "lookback": 24,
    "horizon": 24,
    "metrics": {"MAPE": 8.5, "RMSE": 25.3, "R2": 0.95},
    "scaler_path": "pv_scalers.pkl",
}
torch.save({
    "model_state_dict": model.state_dict(),
    "metadata": model_metadata,
}, "lstm_v1.0.pth")
```

### 9.4 推理优化

```python
# 训练完成后导出 ONNX 格式, 加速 CPU 推理
dummy_input = torch.randn(1, 24, 20)
torch.onnx.export(
    model, dummy_input, "lstm_inference.onnx",
    input_names=["input"],
    output_names=["output"],
    dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
)

# 使用 ONNX Runtime 推理 (比 PyTorch 快 2-3 倍)
import onnxruntime as ort
session = ort.InferenceSession("lstm_inference.onnx")
prediction = session.run(None, {"input": input_data})
```

---

## 十、预期训练时间（CPU）

| 模型 | 参数量 | 80 epoch 预估 | 说明 |
|------|--------|--------------|------|
| LSTM | ~100K | 15-25 min | BiLSTM 计算量稍大 |
| BiGRU | ~80K | 10-20 min | GRU 比 LSTM 快 25% |
| TCN | ~60K | 8-15 min | 卷积运算 CPU 友好 |
| Transformer | ~150K | 20-35 min | Attention 计算量大 |
| **总计** | - | **55-95 min** | 4 模型串行训练 |

> 注：以上基于 Intel i7/i9 CPU (8核+)，实际时间取决于 CPU 性能和并行度设置。

---

## 十一、部署集成方案

训练完成后，PV 预测模型与现有系统集成的架构：

```
┌─────────────────────────────────────────────────────────────────┐
│                    实时预测系统架构                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐   │
│  │ Open-Meteo   │────→│ FastAPI      │────→│ 负荷预测模型  │   │
│  │ 天气API      │     │ 后端         │     │ (现有4模型)  │   │
│  └──────────────┘     │              │     └──────────────┘   │
│                       │  气象数据    │                        │
│                       │  ↓           │     ┌──────────────┐   │
│                       │  PV 预测     │────→│ PV 预测模型   │   │
│                       │  模型推理    │     │ (新训练4模型) │   │
│                       │  ↓           │     └──────────────┘   │
│                       │  净负荷计算  │                        │
│                       │  = 负荷 - PV │     ┌──────────────┐   │
│                       │  ↓           │────→│ 前端展示      │   │
│                       │  API 响应    │     │ React + ECharts│   │
│                       └──────────────┘     └──────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 十二、执行清单

- [ ] Step 1: 运行 `data_preparation.py` — 数据预处理 + 特征工程
- [ ] Step 2: 运行 `data_preparation.py` — 序列构建 + 归一化 + 划分
- [ ] Step 3: 运行 `train.py` — 4 模型训练（~1.5 小时 CPU）
- [ ] Step 4: 运行 `ensemble.py` — 集成权重优化
- [ ] Step 5: 运行 `evaluator.py` — 测试集评估
- [ ] Step 6: 运行 `visualizer.py` — 生成可视化图表
- [ ] Step 7: 导出 ONNX 模型 — 部署优化
- [ ] Step 8: 集成到 FastAPI 后端 — 实时预测
