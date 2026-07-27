# -*- coding: utf-8 -*-
"""
PV 光伏预测模型 — 训练配置
自动检测 GPU/CPU, 支持 GPU 加速训练
"""

import os

# ============================================================================
# 路径配置
# ============================================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "new_england_pv_dataset.csv")
TRAINING_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_DIR = os.path.join(TRAINING_DIR, "processed")
MODEL_DIR = os.path.join(TRAINING_DIR, "saved_models")
OUTPUT_DIR = os.path.join(TRAINING_DIR, "outputs")
LOG_DIR = os.path.join(TRAINING_DIR, "logs")

for d in [PROCESSED_DIR, MODEL_DIR, OUTPUT_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)

# ============================================================================
# 设备配置 (自动检测 GPU)
# ============================================================================
import torch

FORCE_CPU = False  # 设为 True 可强制使用 CPU

if FORCE_CPU:
    DEVICE = torch.device("cpu")
    USE_CUDA = False
    USE_AMP = False  # 自动混合精度 (仅 GPU)
else:
    USE_CUDA = torch.cuda.is_available()
    DEVICE = torch.device("cuda" if USE_CUDA else "cpu")
    USE_AMP = USE_CUDA  # GPU 时启用混合精度加速

# 线程配置
CPU_THREADS = torch.get_num_threads()
TORCH_THREADS = min(CPU_THREADS, 8)  # CPU 最多 8 线程

# GPU 信息
if USE_CUDA:
    GPU_NAME = torch.cuda.get_device_name(0)
    GPU_MEM_GB = torch.cuda.get_device_properties(0).total_mem / (1024**3)
else:
    GPU_NAME = "N/A"
    GPU_MEM_GB = 0

# ============================================================================
# 序列配置
# ============================================================================
LOOKBACK = 24        # 回看窗口: 24 小时 (1天)
HORIZON = 24         # 预测步长: 24 小时
STRIDE = 1           # 滑动步长: 1 小时

# ============================================================================
# 特征配置
# ============================================================================
# 安全特征 (实时预测时可获取)
FEATURE_COLUMNS = [
    # 太阳辐射
    "ghi", "dni", "dhi",
    # 气象
    "temperature", "humidity", "wind_speed", "wind_direction",
    "pressure", "precipitable_water",
    # 云层
    "cloud_type", "cloud_low", "cloud_mid", "cloud_high",
    # 地理
    "latitude", "longitude",
    # 时间编码 (衍生)
    "hour_sin", "hour_cos",
    "month_sin", "month_cos",
    "doy_sin", "doy_cos",
]

# 禁用特征 (数据泄露)
EXCLUDE_COLUMNS = [
    "poa_irradiance",       # PVLib 计算中间量
    "cell_temperature",     # PVLib 计算中间量
    "direct_horizontal",    # DNI 衍生
    "sunshine_duration",    # GHI 衍生
    "pv_power",             # 目标
    "pv_power_kw",          # 目标
]

# 目标列
TARGET_COLUMN = "pv_power_kw"  # kW

# ============================================================================
# 模型配置
# ============================================================================
N_FEATURES = len(FEATURE_COLUMNS)  # 21

# CPU 模型配置 (轻量级, 适合 CPU 训练)
MODEL_CONFIGS_CPU = {
    "LSTM": {
        "input_size": N_FEATURES,
        "hidden_size": 64,
        "num_layers": 2,
        "output_size": HORIZON,
        "dropout": 0.2,
        "bidirectional": True,
    },
    "BiGRU": {
        "input_size": N_FEATURES,
        "hidden_size": 64,
        "num_layers": 2,
        "output_size": HORIZON,
        "dropout": 0.2,
        "bidirectional": True,
    },
    "TCN": {
        "input_size": N_FEATURES,
        "num_channels": [32, 64, 32],
        "kernel_size": 3,
        "dilations": [1, 2, 4, 8],
        "output_size": HORIZON,
        "dropout": 0.2,
    },
    "Transformer": {
        "input_size": N_FEATURES,
        "d_model": 64,
        "nhead": 4,
        "num_layers": 2,
        "d_ff": 128,
        "output_size": HORIZON,
        "dropout": 0.2,
    },
}

# GPU 模型配置 (更大模型, 充分利用 GPU 算力)
MODEL_CONFIGS_GPU = {
    "LSTM": {
        "input_size": N_FEATURES,
        "hidden_size": 128,       # 64 → 128
        "num_layers": 3,          # 2 → 3
        "output_size": HORIZON,
        "dropout": 0.3,           # 0.2 → 0.3 (更大模型需要更多正则化)
        "bidirectional": True,
    },
    "BiGRU": {
        "input_size": N_FEATURES,
        "hidden_size": 128,       # 64 → 128
        "num_layers": 3,          # 2 → 3
        "output_size": HORIZON,
        "dropout": 0.3,
        "bidirectional": True,
    },
    "TCN": {
        "input_size": N_FEATURES,
        "num_channels": [64, 128, 256, 128],  # 更深的通道
        "kernel_size": 5,                     # 更大的卷积核
        "dilations": [1, 2, 4, 8],
        "output_size": HORIZON,
        "dropout": 0.3,
    },
    "Transformer": {
        "input_size": N_FEATURES,
        "d_model": 128,           # 64 → 128
        "nhead": 8,               # 4 → 8
        "num_layers": 4,          # 2 → 4
        "d_ff": 512,              # 128 → 512
        "output_size": HORIZON,
        "dropout": 0.3,
    },
}

# 根据设备自动选择模型配置
MODEL_CONFIGS = MODEL_CONFIGS_GPU if USE_CUDA else MODEL_CONFIGS_CPU

# ============================================================================
# 训练配置
# ============================================================================

# CPU 训练配置
TRAINING_CONFIG_CPU = {
    "epochs": 80,
    "batch_size": 256,           # CPU 大 batch 更高效
    "learning_rate": 1e-3,
    "weight_decay": 1e-4,
    "early_stopping_patience": 12,
    "early_stopping_min_delta": 1e-5,
    "lr_scheduler": "cosine",
    "lr_min": 1e-6,
    "lr_warmup_epochs": 5,
    "loss": "huber",
    "num_workers": 4,            # DataLoader 进程数
    "random_seed": 42,
    "use_amp": False,            # CPU 不用混合精度
    "pin_memory": False,         # CPU 不需要 pin_memory
}

# GPU 训练配置
TRAINING_CONFIG_GPU = {
    "epochs": 150,               # GPU 快, 可以训练更多轮
    "batch_size": 512,           # GPU 大 batch
    "learning_rate": 2e-3,       # 大 batch 需要更大学习率
    "weight_decay": 1e-4,
    "early_stopping_patience": 20,
    "early_stopping_min_delta": 1e-6,
    "lr_scheduler": "cosine",
    "lr_min": 1e-6,
    "lr_warmup_epochs": 5,
    "loss": "huber",
    "num_workers": 8,            # GPU 更多的数据加载进程
    "random_seed": 42,
    "use_amp": True,             # 启用自动混合精度 (FP16)
    "pin_memory": True,          # 加速 CPU→GPU 数据传输
}

# 根据设备自动选择训练配置
TRAINING_CONFIG = TRAINING_CONFIG_GPU if USE_CUDA else TRAINING_CONFIG_CPU

# ============================================================================
# 数据划分 (时间序列)
# ============================================================================
# 训练: 2019-01 ~ 2023-06
# 验证: 2023-07 ~ 2023-12
# 测试: 2024-01 ~ 2024-12
SPLIT_DATES = {
    "train_end": "2023-06-30",
    "val_end": "2023-12-31",
}

# ============================================================================
# 评估指标
# ============================================================================
METRICS = ["MAPE", "RMSE", "MAE", "R2", "MaxAE"]

# ============================================================================
# 设备信息打印
# ============================================================================
def print_device_info():
    """打印设备信息"""
    print(f"  设备: {DEVICE}")
    if USE_CUDA:
        print(f"  GPU: {GPU_NAME} ({GPU_MEM_GB:.1f} GB)")
        print(f"  CUDA: {torch.version.cuda}")
        print(f"  cuDNN: {torch.backends.cudnn.version()}")
        print(f"  混合精度: {'启用 (AMP)' if USE_AMP else '禁用'}")
    else:
        print(f"  CPU 线程: {TORCH_THREADS}")
    print(f"  模型配置: {'GPU (大模型)' if USE_CUDA else 'CPU (轻量模型)'}")
    print(f"  Batch Size: {TRAINING_CONFIG['batch_size']}")
    print(f"  Epochs: {TRAINING_CONFIG['epochs']}")
