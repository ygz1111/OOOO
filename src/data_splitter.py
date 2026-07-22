"""
智能电网负荷预测 - 数据处理模块
第五步：数据划分与归一化

功能：
  1. 按时间顺序划分训练集/验证集/测试集（不能随机打乱！）
  2. 使用 MinMaxScaler 进行归一化（缩放到 [0, 1]）
  3. Scaler 仅在训练集上 fit，然后 transform 验证集和测试集
  4. 同时对目标变量进行归一化
  5. 保存 Scaler 和划分后的数据

数据划分方案：
  - 训练集: 2023-01-08 ~ 2024-12-31  (~67%)
  - 验证集: 2025-01-01 ~ 2025-09-30  (~25%)
  - 测试集: 2025-10-01 ~ 2025-12-31  (~8%)

关键原则：
  - 时间序列必须按时间顺序划分，不能随机打乱
  - Scaler 只能在训练集上 fit，避免数据泄露
  - 目标变量也需要归一化（在使用 LSTM 等模型时）
"""

import pandas as pd
import numpy as np
import os
import pickle
from sklearn.preprocessing import MinMaxScaler

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(PROJECT_ROOT, "processed")

# 划分日期
TRAIN_END = "2024-12-31 23:59:59"
VAL_END = "2025-09-30 23:59:59"
# TEST_END = 数据末尾


def load_step4_data():
    """加载第四步的输出"""
    fpath = os.path.join(PROCESSED_DIR, "step4_model_data.pkl")
    with open(fpath, "rb") as f:
        df = pickle.load(f)
    print(f"[加载] {fpath} ({len(df)} 行, {df.shape[1]} 列)")

    fpath_config = os.path.join(PROCESSED_DIR, "step4_feature_config.pkl")
    with open(fpath_config, "rb") as f:
        config = pickle.load(f)

    return df, config


def split_data(df):
    """
    按时间顺序划分训练集/验证集/测试集。

    划分点：
      训练集: 2023-01-08 ~ 2024-12-31 (2年)
      验证集: 2025-01-01 ~ 2025-09-30 (9个月)
      测试集: 2025-10-01 ~ 2025-12-31 (3个月)
    """
    print("\n[划分] 按时间顺序划分数据集...")

    train_mask = df.index <= TRAIN_END
    val_mask = (df.index > TRAIN_END) & (df.index <= VAL_END)
    test_mask = df.index > VAL_END

    train_df = df[train_mask].copy()
    val_df = df[val_mask].copy()
    test_df = df[test_mask].copy()

    print(f"  训练集: {train_df.index.min()} ~ {train_df.index.max()} ({len(train_df)} 行, {len(train_df)/len(df)*100:.1f}%)")
    print(f"  验证集: {val_df.index.min()} ~ {val_df.index.max()} ({len(val_df)} 行, {len(val_df)/len(df)*100:.1f}%)")
    print(f"  测试集: {test_df.index.min()} ~ {test_df.index.max()} ({len(test_df)} 行, {len(test_df)/len(df)*100:.1f}%)")

    # 验证无重叠
    assert train_df.index.max() < val_df.index.min(), "训练集和验证集有重叠!"
    assert val_df.index.max() < test_df.index.min(), "验证集和测试集有重叠!"
    print(f"  [OK] 数据集无重叠")

    return train_df, val_df, test_df


def fit_scalers(train_df, feature_cols, target_col):
    """
    在训练集上拟合 Scaler。

    为特征和目标分别创建 MinMaxScaler：
      - feature_scaler: 归一化输入特征
      - target_scaler: 归一化目标变量

    MinMaxScaler 选择原因：
      - 将所有特征缩放到 [0, 1] 范围
      - 对 LSTM/GRU 等神经网络友好
      - 保持了原始数据的分布形状
      - 比 StandardScaler 对异常值更鲁棒（电力数据有极端值）
    """
    print("\n[归一化] 在训练集上拟合 Scaler...")

    # 特征 Scaler
    feature_scaler = MinMaxScaler(feature_range=(0, 1))
    feature_scaler.fit(train_df[feature_cols])
    print(f"  特征 Scaler: {len(feature_cols)} 个特征")
    print(f"  特征范围 (训练前):")
    for i, col in enumerate(feature_cols):
        print(f"    {col:30s} [{feature_scaler.data_min_[i]:.2f}, {feature_scaler.data_max_[i]:.2f}]")

    # 目标 Scaler
    target_scaler = MinMaxScaler(feature_range=(0, 1))
    target_scaler.fit(train_df[[target_col]])
    print(f"\n  目标 Scaler: {target_col}")
    print(f"  目标范围 (训练前): [{target_scaler.data_min_[0]:.2f}, {target_scaler.data_max_[0]:.2f}]")

    return feature_scaler, target_scaler


def transform_data(train_df, val_df, test_df, feature_cols, target_col,
                   feature_scaler, target_scaler):
    """
    用训练集拟合的 Scaler 对三个数据集进行归一化。

    返回 numpy 数组（便于后续 TensorFlow 使用）：
      X_train, y_train, X_val, y_val, X_test, y_test
    """
    print("\n[归一化] Transform 数据集...")

    # Transform 特征
    X_train = feature_scaler.transform(train_df[feature_cols])
    X_val = feature_scaler.transform(val_df[feature_cols])
    X_test = feature_scaler.transform(test_df[feature_cols])

    # Transform 目标
    y_train = target_scaler.transform(train_df[[target_col]])
    y_val = target_scaler.transform(val_df[[target_col]])
    y_test = target_scaler.transform(test_df[[target_col]])

    print(f"  X_train: {X_train.shape}, y_train: {y_train.shape}")
    print(f"  X_val:   {X_val.shape}, y_val:   {y_val.shape}")
    print(f"  X_test:  {X_test.shape}, y_test:  {y_test.shape}")

    # 验证归一化后的范围
    print(f"\n  归一化后范围验证:")
    print(f"  X_train: [{X_train.min():.4f}, {X_train.max():.4f}]")
    print(f"  X_val:   [{X_val.min():.4f}, {X_val.max():.4f}]  (可能超出[0,1]，正常)")
    print(f"  X_test:  [{X_test.min():.4f}, {X_test.max():.4f}]  (可能超出[0,1]，正常)")
    print(f"  y_train: [{y_train.min():.4f}, {y_train.max():.4f}]")
    print(f"  y_val:   [{y_val.min():.4f}, {y_val.max():.4f}]")
    print(f"  y_test:  [{y_test.min():.4f}, {y_test.max():.4f}]")

    # 检查验证集/测试集是否有超出 [0,1] 的特征
    val_below = (X_val < 0).sum() + (X_val > 1).sum()
    test_below = (X_test < 0).sum() + (X_test > 1).sum()
    print(f"\n  验证集超出[0,1]的值数: {val_below} (正常现象，说明验证集有训练集未见的极端值)")
    print(f"  测试集超出[0,1]的值数: {test_below}")

    return X_train, y_train, X_val, y_val, X_test, y_test


def save_step5_data(X_train, y_train, X_val, y_val, X_test, y_test,
                    feature_scaler, target_scaler,
                    train_df, val_df, test_df, config):
    """保存第五步结果"""
    # 保存归一化后的 numpy 数组
    data = {
        "X_train": X_train, "y_train": y_train,
        "X_val": X_val, "y_val": y_val,
        "X_test": X_test, "y_test": y_test,
    }
    fpath = os.path.join(PROCESSED_DIR, "step5_normalized_data.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(data, f)
    print(f"\n[保存] {fpath}")

    # 保存 Scaler
    scalers = {
        "feature_scaler": feature_scaler,
        "target_scaler": target_scaler,
    }
    fpath = os.path.join(PROCESSED_DIR, "step5_scalers.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(scalers, f)
    print(f"[保存] {fpath}")

    # 保存划分信息
    split_info = {
        "train_start": str(train_df.index.min()),
        "train_end": str(train_df.index.max()),
        "train_size": len(train_df),
        "val_start": str(val_df.index.min()),
        "val_end": str(val_df.index.max()),
        "val_size": len(val_df),
        "test_start": str(test_df.index.min()),
        "test_end": str(test_df.index.max()),
        "test_size": len(test_df),
        "feature_cols": config["feature_cols"],
        "target": config["target"],
        "n_features": len(config["feature_cols"]),
    }
    fpath = os.path.join(PROCESSED_DIR, "step5_split_info.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(split_info, f)
    print(f"[保存] {fpath}")


# ============================================================================
# 主流程：执行第五步数据划分与归一化
# ============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("第五步：数据划分与归一化")
    print("=" * 70)

    # 1. 加载第四步数据
    df, config = load_step4_data()
    feature_cols = config["feature_cols"]
    target_col = config["target"]

    print(f"\n预测目标: {target_col}")
    print(f"输入特征数: {len(feature_cols)}")
    print(f"总数据量: {len(df)} 行")
    print(f"时间范围: {df.index.min()} ~ {df.index.max()}")

    # 2. 按时间划分
    train_df, val_df, test_df = split_data(df)

    # 3. 拟合 Scaler（仅在训练集上）
    feature_scaler, target_scaler = fit_scalers(train_df, feature_cols, target_col)

    # 4. Transform 数据
    X_train, y_train, X_val, y_val, X_test, y_test = transform_data(
        train_df, val_df, test_df, feature_cols, target_col,
        feature_scaler, target_scaler
    )

    # 5. 保存
    save_step5_data(X_train, y_train, X_val, y_val, X_test, y_test,
                    feature_scaler, target_scaler,
                    train_df, val_df, test_df, config)

    # 6. 概览
    print("\n" + "=" * 70)
    print("归一化后数据概览")
    print("=" * 70)
    print(f"X_train: {X_train.shape} (样本数, 特征数)")
    print(f"y_train: {y_train.shape}")
    print(f"X_val:   {X_val.shape}")
    print(f"y_val:   {y_val.shape}")
    print(f"X_test:  {X_test.shape}")
    print(f"y_test:  {y_test.shape}")

    # 反归一化验证（确保 Scaler 可逆）
    y_train_inverse = target_scaler.inverse_transform(y_train)
    print(f"\n反归一化验证:")
    print(f"  y_train 原始范围: [{train_df[target_col].min():.2f}, {train_df[target_col].max():.2f}]")
    print(f"  y_train 反归一化: [{y_train_inverse.min():.2f}, {y_train_inverse.max():.2f}]")
    print(f"  [OK] 反归一化正确" if np.allclose(y_train_inverse.flatten(), train_df[target_col].values) else "  [ERROR] 反归一化不匹配!")

    print("\n[第五步完成]")
