# -*- coding: utf-8 -*-
"""
PV 光伏预测 — 数据预处理模块
Step 1: 特征工程 + 数据清洗
Step 2: 序列构建 + 归一化 + 数据划分
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (
    DATA_FILE, PROCESSED_DIR, FEATURE_COLUMNS, TARGET_COLUMN,
    EXCLUDE_COLUMNS, LOOKBACK, HORIZON, STRIDE, SPLIT_DATES,
    TRAINING_CONFIG, N_FEATURES,
)

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ============================================================================
# Step 1: 特征工程
# ============================================================================

def load_data():
    """加载 PVLib 仿真数据集"""
    logger.info(f"加载数据: {DATA_FILE}")
    df = pd.read_csv(DATA_FILE)
    logger.info(f"  行数: {len(df):,}, 列数: {len(df.columns)}")
    logger.info(f"  城市: {sorted(df['city'].unique())}")
    logger.info(f"  年份: {df['year'].min()}-{df['year'].max()}")
    return df


def add_time_features(df):
    """添加时间周期编码特征"""
    logger.info("添加时间周期编码...")
    
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    
    # day of year
    timestamps = pd.to_datetime(df["timestamp"])
    day_of_year = timestamps.dt.dayofyear
    df["doy_sin"] = np.sin(2 * np.pi * day_of_year / 365)
    df["doy_cos"] = np.cos(2 * np.pi * day_of_year / 365)
    
    return df


def add_lag_features(df):
    """添加滞后特征 (按城市分组)"""
    logger.info("添加滞后特征...")
    
    # GHI 滞后
    df["ghi_lag_1h"] = df.groupby("city")["ghi"].shift(1)
    df["ghi_lag_24h"] = df.groupby("city")["ghi"].shift(24)
    
    # 温度滞后
    df["temp_lag_1h"] = df.groupby("city")["temperature"].shift(1)
    
    # GHI 变化率
    df["ghi_diff_1h"] = df.groupby("city")["ghi"].diff(1)
    
    # GHI 滑动均值
    df["ghi_rolling_mean_3h"] = df.groupby("city")["ghi"].shift(1).rolling(3).mean().reset_index(0, drop=True)
    
    # PV 功率滞后 (训练时可用, 实时推理时用前一日实际发电量)
    df["pv_power_lag_24h"] = df.groupby("city")[TARGET_COLUMN].shift(24)
    
    return df


def clean_data(df):
    """数据清洗: 异常值过滤"""
    logger.info("数据清洗...")
    before = len(df)
    
    # PV 功率范围: [0, 500] kW
    df = df[(df[TARGET_COLUMN] >= 0) & (df[TARGET_COLUMN] <= 500)]
    
    # GHI 范围
    df = df[(df["ghi"] >= 0) & (df["ghi"] <= 1200)]
    
    # DNI 范围
    df = df[(df["dni"] >= 0) & (df["dni"] <= 1100)]
    
    # 温度范围
    df = df[(df["temperature"] >= -40) & (df["temperature"] <= 55)]
    
    # 风速范围
    df = df[(df["wind_speed"] >= 0) & (df["wind_speed"] <= 60)]
    
    after = len(df)
    logger.info(f"  清洗前: {before:,} → 清洗后: {after:,} (删除 {before-after:,})")
    
    return df


def step1_preprocess():
    """Step 1: 完整的数据预处理"""
    print("=" * 70)
    print("Step 1: 数据预处理")
    print("=" * 70)
    
    df = load_data()
    df = add_time_features(df)
    df = add_lag_features(df)
    df = clean_data(df)
    
    # 按城市+时间排序
    df = df.sort_values(["city", "timestamp"]).reset_index(drop=True)
    
    # 保存
    fpath = os.path.join(PROCESSED_DIR, "pv_processed.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(df, f)
    logger.info(f"保存: {fpath} ({len(df):,} 行, {len(df.columns)} 列)")
    
    # 显示特征列表
    available_features = [c for c in FEATURE_COLUMNS if c in df.columns]
    logger.info(f"可用特征 ({len(available_features)}): {available_features}")
    
    return df


# ============================================================================
# Step 2: 序列构建 + 归一化 + 划分
# ============================================================================

def build_sequences(df, features, target, lookback, horizon, stride=1):
    """
    按城市分组构建滑动窗口序列
    
    Returns:
        X: (n_samples, lookback, n_features)
        y: (n_samples, horizon)
        meta: 每个样本的元数据 (city, timestamp)
    """
    sequences_X = []
    sequences_y = []
    meta_city = []
    meta_ts = []
    
    for city in sorted(df["city"].unique()):
        city_data = df[df["city"] == city].sort_values("timestamp").reset_index(drop=True)
        n = len(city_data)
        
        feature_data = city_data[features].values
        target_data = city_data[target].values
        timestamps = city_data["timestamp"].values
        
        for i in range(0, n - lookback - horizon + 1, stride):
            x = feature_data[i : i + lookback]
            y = target_data[i + lookback : i + lookback + horizon]
            
            # 跳过含 NaN 的序列
            if np.isnan(x).any() or np.isnan(y).any():
                continue
            
            sequences_X.append(x)
            sequences_y.append(y)
            meta_city.append(city)
            meta_ts.append(timestamps[i + lookback])  # 预测起始时间
    
    X = np.array(sequences_X, dtype=np.float32)
    y = np.array(sequences_y, dtype=np.float32)
    
    return X, y, meta_city, meta_ts


def split_by_time(X, y, meta_city, meta_ts, split_dates):
    """按时间戳划分训练/验证/测试集"""
    train_end = pd.Timestamp(split_dates["train_end"])
    val_end = pd.Timestamp(split_dates["val_end"])
    
    train_idx = []
    val_idx = []
    test_idx = []
    
    for i, ts in enumerate(meta_ts):
        t = pd.Timestamp(ts)
        if t <= train_end:
            train_idx.append(i)
        elif t <= val_end:
            val_idx.append(i)
        else:
            test_idx.append(i)
    
    logger.info(f"  训练集: {len(train_idx):,}")
    logger.info(f"  验证集: {len(val_idx):,}")
    logger.info(f"  测试集: {len(test_idx):,}")
    
    return (
        X[train_idx], y[train_idx],
        X[val_idx], y[val_idx],
        X[test_idx], y[test_idx],
        [meta_city[i] for i in test_idx],
        [meta_ts[i] for i in test_idx],
    )


def step2_build_sequences():
    """Step 2: 构建序列并划分"""
    print("\n" + "=" * 70)
    print("Step 2: 序列构建与归一化")
    print("=" * 70)
    
    # 加载预处理数据
    fpath = os.path.join(PROCESSED_DIR, "pv_processed.pkl")
    with open(fpath, "rb") as f:
        df = pickle.load(f)
    logger.info(f"加载: {fpath} ({len(df):,} 行)")
    
    # 确认可用特征
    features = [c for c in FEATURE_COLUMNS if c in df.columns]
    logger.info(f"特征数: {len(features)}")
    
    # 构建序列
    logger.info(f"构建序列 (lookback={LOOKBACK}, horizon={HORIZON}, stride={STRIDE})...")
    X, y, meta_city, meta_ts = build_sequences(
        df, features, TARGET_COLUMN, LOOKBACK, HORIZON, STRIDE
    )
    logger.info(f"  总序列数: {len(X):,}")
    logger.info(f"  X 形状: {X.shape}")
    logger.info(f"  y 形状: {y.shape}")
    
    # 时间序列划分
    logger.info("按时间划分...")
    X_train, y_train, X_val, y_val, X_test, y_test, test_cities, test_timestamps = \
        split_by_time(X, y, meta_city, meta_ts, SPLIT_DATES)
    
    # 归一化 (仅 fit 训练集)
    logger.info("归一化...")
    
    # 特征归一化: 3D -> 2D -> fit -> 3D
    X_train_2d = X_train.reshape(-1, X_train.shape[-1])
    feature_scaler = MinMaxScaler()
    feature_scaler.fit(X_train_2d)
    
    X_train_norm = feature_scaler.transform(X_train_2d).reshape(X_train.shape)
    X_val_norm = feature_scaler.transform(X_val.reshape(-1, X_val.shape[-1])).reshape(X_val.shape)
    X_test_norm = feature_scaler.transform(X_test.reshape(-1, X_test.shape[-1])).reshape(X_test.shape)
    
    # 目标归一化
    target_scaler = MinMaxScaler()
    target_scaler.fit(y_train.reshape(-1, 1))
    
    y_train_norm = target_scaler.transform(y_train.reshape(-1, 1)).reshape(y_train.shape)
    y_val_norm = target_scaler.transform(y_val.reshape(-1, 1)).reshape(y_val.shape)
    y_test_norm = target_scaler.transform(y_test.reshape(-1, 1)).reshape(y_test.shape)
    
    logger.info(f"  特征范围: [{X_train_norm.min():.3f}, {X_train_norm.max():.3f}]")
    logger.info(f"  目标范围: [{y_train_norm.min():.3f}, {y_train_norm.max():.3f}]")
    
    # 保存
    seq_data = {
        "X_train": X_train_norm.astype(np.float32),
        "y_train": y_train_norm.astype(np.float32),
        "X_val": X_val_norm.astype(np.float32),
        "y_val": y_val_norm.astype(np.float32),
        "X_test": X_test_norm.astype(np.float32),
        "y_test": y_test_norm.astype(np.float32),
        "y_test_orig": y_test.astype(np.float32),  # 原始值 (用于评估)
        "test_cities": test_cities,
        "test_timestamps": test_timestamps,
        "features": features,
        "lookback": LOOKBACK,
        "horizon": HORIZON,
    }
    
    seq_path = os.path.join(PROCESSED_DIR, "pv_sequences.pkl")
    with open(seq_path, "wb") as f:
        pickle.dump(seq_data, f)
    logger.info(f"保存序列: {seq_path}")
    
    scaler_data = {
        "feature_scaler": feature_scaler,
        "target_scaler": target_scaler,
    }
    scaler_path = os.path.join(PROCESSED_DIR, "pv_scalers.pkl")
    with open(scaler_path, "wb") as f:
        pickle.dump(scaler_data, f)
    logger.info(f"保存 Scaler: {scaler_path}")
    
    return seq_data


# ============================================================================
# 主入口
# ============================================================================
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    # Step 1
    df = step1_preprocess()
    
    # Step 2
    seq_data = step2_build_sequences()
    
    print("\n" + "=" * 70)
    print("数据预处理完成!")
    print(f"  训练集: {seq_data['X_train'].shape}")
    print(f"  验证集: {seq_data['X_val'].shape}")
    print(f"  测试集: {seq_data['X_test'].shape}")
    print(f"  特征数: {len(seq_data['features'])}")
    print("=" * 70)
