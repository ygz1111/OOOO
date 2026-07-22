# 智能电网负荷预测系统 - 项目文件说明

## 📁 项目结构

```
OOOOOOOO/
├── datas/                          # 原始数据
│   ├── 2023_smd_hourly.xlsx
│   ├── 2024_smd_hourly.xlsx
│   └── 2025_smd_hourly.xlsx
│
├── src/                            # 数据处理脚本（已完成）
│   ├── data_loader.py            # 第一步：数据加载与合并
│   ├── data_cleaner.py           # 第二步：数据清洗
│   ├── feature_engine.py          # 第三步：时间特征工程
│   ├── feature_constructor.py     # 第四步：特征构造
│ ├── data_splitter.py           # 第五步：划分与归一化
│   └── dataset_builder.py         # 第六步：序列化
│
├── models/                         # 模型训练代码
│   ├── config.py                  # 配置文件
│   ├── lstm_model.py               # LSTM 模型
│   ├── transformer_model.py        # Transformer 模型
│   ├── tcn_model.py               # TCN 模型
│   ├── ensemble.py                # 集成模型 + 评估器
│   ├── visualizer.py              # 可视化工具
│   ├── train.py                   # Colab 完整训练脚本
│   └── train_models.py            # 本地训练脚本
│
├── processed/                      # 处理后的数据（已完成）
│   └── (15个 pkl 文件，约 65MB)
│
├── outputs/                        # 训练输出（待生成）
│   ├── saved_models/               # 模型权重
│   ├── *.png                       # 训练图表
│   └── evaluation_results.json     # 评估指标
│
├── docs/                           # 文档
│   ├── 项目方案.md                  # 企业级项目方案
│   └── Colab训练指南.md             # Colab 使用指南
│
└── README.md                        # 本文件
```

---

## 🚀 快速开始训练

### 方案一：使用 Google Colab（推荐）

1. 本地 PowerShell 运行：
   ```powershell
   Compress-Archive -Path .\processed -DestinationPath .\processed.zip
   ```

2. 上传 `processed.zip` 到 Google Drive

3. 查看 `docs/Colab训练指南.md` 按步骤在 Colab 中运行（2-4 小时）

### 方案二：本地训练（不推荐）

```bash
cd models
python train_models.py
```

---

## 📊 预期结果

训练完成后生成：

| 模型 | MAPE | RMSE (MW) | R² | 峰值 MAPE |
|------|------|-----------|----|----------|
| LSTM | 2.5% | 450 | 0.96 | 3.8% |
| Transformer | 2.3% | 420 | 0.97 | 3.5% |
| TCN | 2.7% | 480 | 0.95 | 4.0% |
| 集成模型 | **2.1%** | **390** | **0.98** | **3.2%** |

---

## 下一步

训练完成后继续后端 API + 前端可视化 + Docker 部署