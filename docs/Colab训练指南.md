# Google Colab 训练完整指南

## 一、准备工作（本地操作）

### 1.1 压缩处理后的数据

在本地 PowerShell 运行：

```powershell
cd D:\GitHub\OOOOOO
Compress-Archive -Path .\processed -DestinationPath .\processed.zip
```

这将创建 `processed.zip`，包含所有数据处理后的文件。

### 1.2 压缩模型代码文件

```powershell
cd D:\GitHub\OOOOOO
Compress-Archive -Path .\models -DestinationPath .\models.zip
```

---

## 二、上传到 Google Drive

### 2.1 将两个文件上传到 Google Drive

1. 打开 [Google Drive](https://drive.google.com/)
2. 点击左上角 "新建" → "上传文件"
3. 上传 `processed.zip` 和 `models.zip`

### 2.2 获取 processed.zip 的 File ID

1. 在 Google Drive 中右键 `processed.zip` → "获取共享链接"
2. 点击 "限制为知道链接的人"
3. 复制链接中的 File ID（链接中 `d/` 和 `/edit` 之间的部分）

示例：
- 链接: `https://drive.google.com/file/d/1ABCdefGHIJ.../edit?usp=sharing`
- File ID: `1ABCdefGHIJ...`

---

## 三、在 Google Colab 中运行

### 3.1 打开 Colab

访问 [Google Colab](https://colab.research.google.com/)

### 3.2 创建新 Notebook

点击 "文件" → "新建笔记本"

### 3.3 启用 GPU

点击 "代码执行程序" → "更改运行时类型" → "T4 GPU"

### 3.4 依次运行以下代码单元格

#### 单元格 1: 挂载 Google Drive

```python
from google.colab import drive
drive.mount('/content/drive')
```

运行后点击授权链接，复制授权码，粘贴回输入框。

#### 单元格 2: 解压数据

```python
import zipfile
import os

# 解压数据
zip_path = '/content/drive/MyDrive/processed.zip'  # 修改为你实际的文件名
extract_dir = '/content'

with zipfile.ZipFile(zip_path, 'r') as zip_ref:
    zip_ref.extractall(extract_dir)

print(f"数据已解压到: {extract_dir}")
!ls /content/processed/
```

#### 单元格 3: 解压模型代码

```python
zip_path = '/content/drive/MyDrive/models.zip'

with zipfile.ZipFile(zip_path, 'r') as zip_ref:
    zip_ref.extractall('/content')
print(f"模型代码已解压")
!ls /content/models/
```

#### 单元格 4: 安装依赖

```python
!pip install -q tensorflow numpy pandas scikit-learn matplotlib seaborn pyyaml
```

#### 单元格 5: 修改配置并训练

打开 `/content/models/config.py`，修改：

```python
DATA_SOURCE = "gdrive"  # 保持不变
GDRIVE_FILE_ID = "你的FileID"  # 填入步骤 2.2 复制的 File ID

# 如果只想测试，可以设置：
TRAIN_SINGLE_MODEL = True  # False 训练全部，True 只训练 LSTM
```

然后运行训练：

```python
import sys
sys.path.append('/content/models')

# 修改配置（动态修改，无需编辑文件）
import config
config.DATA_SOURCE = "gdrive"
config.GDRIVE_FILE_ID = "你的FileID"  # 替换为实际 FileID

# 运行训练
exec(open('/content/train.py').read())
```

---

## 四、下载训练结果

训练完成后（预计 2-4 小时）：

### 4.1 下载图表和报告

在 Colab 中运行：

```python
from google.colab import files
import shutil

# 压缩输出文件夹
shutil.make_archive('outputs.zip', '/content/outputs')
files.download('outputs.zip')
```

### 4.2 下载模型权重

```python
shutil.make_archive('saved_models.zip', '/content/outputs/saved_models')
files.download('saved_models.zip')
```

---

## 五、本地使用训练结果

### 5.1 解压到本地

将下载的文件解压到项目目录。

### 5.2 文件说明

```
outputs/
├── LSTM_training_history.png        # LSTM 训练曲线
├── LSTM_prediction_24h.png            # 24小时预测对比
├── LSTM_prediction_7d.png             # 7天连续预测
├── LSTM_error_distribution.png        # 误差分布
├── LSTM_scatter.png                   # 散点图
├── LSTM_hourly_error.png              # 每小时误差
├── Transformer_*.png                   # Transformer 对应图表
├── TCN_*.png                           # TCN 对应图表
├── Ensemble_*.png                      # 集成模型对应图表
├── model_comparison_MAPE.png           # 模型 MAPE 对比
├── model_comparison_RMSE.png           # 模型 RMSE 对比
├── model_comparison_R2.png              # 模型 R² 对比
└── evaluation_results.json             # 评估指标数据

saved_models/
├── lstm_model.h5                       # LSTM 权重
├── transformer_model.h5                 # Transformer 权重
├── tcn_model.h5                         # TCN 权重
└── (checkpoints)                        # 最佳检查点（自动保存的）
```

### 5.3 论文使用建议

**论文中的图表使用：**

1. **对比图**: `model_comparison_MAPE.png`, `model_comparison_RMSE.png`, `model_comparison_R2.png`
2. **最佳模型曲线图**: `Ensemble_training_history.png`
3. **预测效果**: `Ensemble_prediction_24h.png`, `Ensemble_prediction_7d.png`
4. **误差分析**: `Ensemble_error_distribution.png`, `Ensemble_scatter.png`, `Ensemble_hourly_error.png`

**论文数据参考**: 查看 `evaluation_results.json` 获取所有指标数据

---

## 六、常见问题

### Q1: 训练速度慢？
**A**: 确保 GPU 已启用（代码执行程序 → 更改运行时类型 → T4 GPU）

### Q2: 内存不足？
**A**: 减小 batch_size（在 `train.py` 中修改为 32 或 16）

### Q3: File ID 填什么？
**A**: 从 Google Drive 右键 processed.zip → 获取共享链接 → 复制链接中 `d/` 和 `/edit` 之间的部分

### Q4: 想用本地数据？
**A**: 
1. 跳过 Google Drive 步骤
2. 修改 `train.py` 中的配置：
   ```python
   DATA_SOURCE = "local"
   LOCAL_DATA_DIR = "../processed"  # 相对路径
   ```
3. 将 models 文件夹也放在与 processed 同级目录

### Q5: 想缩短训练时间？
**A**: 
1. 使用 `TRAIN_SINGLE_MODEL = True` 只训练一个模型
2. 或减少 `EPOCHS`（不推荐低于 50）

---

## 七、完整执行流程（从零开始）

```
本地：
1. python 数据处理（已完成）→ 生成 processed/ 目录
2. 压缩 processed/ 和 models/
3. 上传两个 zip 文件到 Google Drive

Google Colab：
4. 新建 Notebook，启用 T4 GPU
5. 运行单元格 1（挂载 Drive）
6. 运行单元格 2（解压数据）
7. 运行单元格 3（解压代码）
8. 运行单元格 4（安装依赖）
9. 修改 train.py 中的 File ID
10. 运行单元格 5（开始训练）
11. 等待 2-4 小时...
12. 下载 outputs.zip

本地：
13. 解压 outputs.zip
14. 查看图表和评估结果
15. 写论文 + 做答辩
```

---

## 八、训练时监控

在 Colab 中可以查看训练日志：

- Loss 下降情况
- 每个 Epoch 的 MAE/RMSE
- 早停触发时间

最佳模型的参数会自动保存在 `saved_models/` 目录。

---

准备好后就可以开始训练了！有任何问题随时问我。