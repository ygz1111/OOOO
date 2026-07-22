"""
智能电网负荷预测 - 数据处理模块
第六步：序列化与 TensorFlow 数据管道构建

功能：
  1. 将二维表格数据转换为三维时序张量（滑动窗口方法）
  2. 构建可配置的 lookback (回看窗口) 和 horizon (预测步长)
  3. 使用 tf.data.Dataset 构建高效数据管道
  4. 应用 shuffle (仅训练集)、batch、prefetch 优化

滑动窗口示例 (lookback=168, horizon=24, stride=1):
  样本1: t=0~167 的特征 -> 预测 t=168~191 的负荷
  样本2: t=1~168 的特征 -> 预测 t=169~192 的负荷
  样本3: t=2~169 的特征 -> 预测 t=170~193 的负荷
  ...

输出形状:
  X: (样本数, lookback, n_features)  - 三维时序张量
  y: (样本数, horizon)               - 二维目标张量

参数选择理由:
  lookback=168 (7天): 电力负荷有强烈的周周期性，7天历史能捕捉完整周期
  horizon=24 (24小时): 预测未来24小时，适合日前调度规划
  stride=1: 最大化训练样本数量
"""

import os
import sys
import pickle
import numpy as np

# 设置环境变量减少 TF 日志噪音
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

import tensorflow as tf

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(PROJECT_ROOT, "processed")

# 滑动窗口参数
LOOKBACK = 168    # 回看7天 (168小时)
HORIZON = 24      # 预测未来24小时
STRIDE = 1        # 滑动步长

# 数据管道参数
BATCH_SIZE = 64
SHUFFLE_BUFFER = 1000  # shuffle 缓冲区大小
PREFETCH = tf.data.AUTOTUNE  # 自动调整 prefetch 数量


def load_step5_data():
    """加载第五步的输出"""
    fpath = os.path.join(PROCESSED_DIR, "step5_normalized_data.pkl")
    with open(fpath, "rb") as f:
        data = pickle.load(f)
    print(f"[加载] {fpath}")
    print(f"  X_train: {data['X_train'].shape}, y_train: {data['y_train'].shape}")
    print(f"  X_val:   {data['X_val'].shape}, y_val:   {data['y_val'].shape}")
    print(f"  X_test:  {data['X_test'].shape}, y_test:  {data['y_test'].shape}")

    fpath_info = os.path.join(PROCESSED_DIR, "step5_split_info.pkl")
    with open(fpath_info, "rb") as f:
        split_info = pickle.load(f)

    return data, split_info


def create_sequences(X, y, lookback, horizon, stride=1):
    """
    使用滑动窗口将二维数据转换为三维时序序列。

    Args:
        X: 二维数组 (n_samples, n_features) - 归一化后的特征
        y: 二维数组 (n_samples, 1) - 归一化后的目标
        lookback: 回看窗口大小（用过去多少小时预测）
        horizon: 预测步长（预测未来多少小时）
        stride: 滑动步长

    Returns:
        X_seq: 三维数组 (n_sequences, lookback, n_features)
        y_seq: 二维数组 (n_sequences, horizon)

    示例 (lookback=3, horizon=2, stride=1):
      输入 X = [[1],[2],[3],[4],[5],[6]], y = [[10],[20],[30],[40],[50],[60]]
      输出 X_seq = [[[1],[2],[3]], [[2],[3],[4]], [[3],[4],[5]]]
      输出 y_seq = [[30,40], [40,50], [50,60]]

    注意：y_seq 取的是 X_seq 最后一个时间步之后的 horizon 个目标值。
         即 X_seq[i] 覆盖时间 t~t+lookback-1，
            y_seq[i] 覆盖时间 t+lookback~t+lookback+horizon-1。
    """
    n_samples = len(X)
    n_features = X.shape[1]

    # 计算可生成的序列数量
    # 需要满足: lookback + horizon <= n_samples
    n_sequences = (n_samples - lookback - horizon + 1) // stride

    if n_sequences <= 0:
        raise ValueError(
            f"数据量不足: n_samples={n_samples}, "
            f"lookback={lookback}, horizon={horizon}, "
            f"需要至少 {lookback + horizon} 个样本"
        )

    # 预分配数组（比动态 append 快得多）
    X_seq = np.zeros((n_sequences, lookback, n_features), dtype=np.float32)
    y_seq = np.zeros((n_sequences, horizon), dtype=np.float32)

    for i in range(n_sequences):
        start = i * stride
        end = start + lookback
        # X 序列: 从 start 到 start+lookback
        X_seq[i] = X[start:end]
        # y 序列: 从 start+lookback 到 start+lookback+horizon
        y_seq[i] = y[end:end + horizon].flatten()

    return X_seq, y_seq


def build_tf_dataset(X_seq, y_seq, shuffle=False, batch_size=BATCH_SIZE):
    """
    构建 TensorFlow 数据管道。

    Args:
        X_seq: 三维数组 (n_sequences, lookback, n_features)
        y_seq: 二维数组 (n_sequences, horizon)
        shuffle: 是否打乱（仅训练集打乱）
        batch_size: 批大小

    Returns:
        tf.data.Dataset
    """
    dataset = tf.data.Dataset.from_tensor_slices((X_seq, y_seq))

    if shuffle:
        dataset = dataset.shuffle(buffer_size=SHUFFLE_BUFFER)

    dataset = dataset.batch(batch_size)
    dataset = dataset.prefetch(PREFETCH)

    return dataset


def build_all_datasets(data, split_info):
    """
    构建全部训练/验证/测试的序列数据和 TF Dataset。

    Returns:
        datasets: dict 包含:
          - X_train_seq, y_train_seq: 训练集序列
          - X_val_seq, y_val_seq: 验证集序列
          - X_test_seq, y_test_seq: 测试集序列
          - train_ds, val_ds, test_ds: TF Dataset
          - metadata: 参数和形状信息
    """
    print(f"\n[序列化] 滑动窗口参数:")
    print(f"  lookback (回看窗口): {LOOKBACK} 小时 ({LOOKBACK//24} 天)")
    print(f"  horizon  (预测步长): {HORIZON} 小时")
    print(f"  stride   (滑动步长): {STRIDE}")
    print(f"  n_features: {split_info['n_features']}")

    # 1. 生成序列
    print(f"\n[序列化] 生成滑动窗口序列...")

    X_train_seq, y_train_seq = create_sequences(
        data["X_train"], data["y_train"], LOOKBACK, HORIZON, STRIDE
    )
    print(f"  训练集: X={X_train_seq.shape}, y={y_train_seq.shape}")

    X_val_seq, y_val_seq = create_sequences(
        data["X_val"], data["y_val"], LOOKBACK, HORIZON, STRIDE
    )
    print(f"  验证集: X={X_val_seq.shape}, y={y_val_seq.shape}")

    X_test_seq, y_test_seq = create_sequences(
        data["X_test"], data["y_test"], LOOKBACK, HORIZON, STRIDE
    )
    print(f"  测试集: X={X_test_seq.shape}, y={y_test_seq.shape}")

    # 2. 验证序列正确性
    print(f"\n[验证] 序列正确性检查...")

    # 检查训练集第一个序列的 X 是否与原始数据一致
    assert np.allclose(X_train_seq[0, 0, :], data["X_train"][0, :]), \
        "训练集第一个序列的起始位置不匹配!"
    assert np.allclose(X_train_seq[0, -1, :], data["X_train"][LOOKBACK - 1, :]), \
        "训练集第一个序列的结束位置不匹配!"
    assert np.allclose(y_train_seq[0, 0], data["y_train"][LOOKBACK, 0]), \
        "训练集第一个目标值不匹配!"
    print(f"  [OK] 序列数据与原始数据对齐验证通过")

    # 检查无 NaN
    for name, X_s, y_s in [("train", X_train_seq, y_train_seq),
                            ("val", X_val_seq, y_val_seq),
                            ("test", X_test_seq, y_test_seq)]:
        nan_count = np.isnan(X_s).sum() + np.isnan(y_s).sum()
        print(f"  {name} NaN 数量: {nan_count}")
        assert nan_count == 0, f"{name} 存在 NaN!"

    # 3. 构建 TF Dataset
    print(f"\n[管道] 构建 tf.data.Dataset...")

    train_ds = build_tf_dataset(X_train_seq, y_train_seq, shuffle=True)
    val_ds = build_tf_dataset(X_val_seq, y_val_seq, shuffle=False)
    test_ds = build_tf_dataset(X_test_seq, y_test_seq, shuffle=False)

    print(f"  训练集: {train_ds}")
    print(f"  验证集: {val_ds}")
    print(f"  测试集: {test_ds}")

    # 4. 验证 Dataset 输出形状
    print(f"\n[验证] Dataset 输出形状...")
    for x_batch, y_batch in train_ds.take(1):
        print(f"  训练集 batch: X={x_batch.shape}, y={y_batch.shape}")
        print(f"  X dtype: {x_batch.dtype}, y dtype: {y_batch.dtype}")
        assert x_batch.shape[1] == LOOKBACK, f"lookback 不匹配: {x_batch.shape[1]} != {LOOKBACK}"
        assert x_batch.shape[2] == split_info["n_features"], \
            f"n_features 不匹配: {x_batch.shape[2]} != {split_info['n_features']}"
        assert y_batch.shape[1] == HORIZON, f"horizon 不匹配: {y_batch.shape[1]} != {HORIZON}"
    print(f"  [OK] Dataset 形状验证通过")

    # 5. 汇总元数据
    metadata = {
        "lookback": LOOKBACK,
        "horizon": HORIZON,
        "stride": STRIDE,
        "n_features": split_info["n_features"],
        "feature_cols": split_info["feature_cols"],
        "target": split_info["target"],
        "batch_size": BATCH_SIZE,
        "shapes": {
            "X_train": list(X_train_seq.shape),
            "y_train": list(y_train_seq.shape),
            "X_val": list(X_val_seq.shape),
            "y_val": list(y_val_seq.shape),
            "X_test": list(X_test_seq.shape),
            "y_test": list(y_test_seq.shape),
        },
    }

    datasets = {
        "X_train_seq": X_train_seq, "y_train_seq": y_train_seq,
        "X_val_seq": X_val_seq, "y_val_seq": y_val_seq,
        "X_test_seq": X_test_seq, "y_test_seq": y_test_seq,
        "train_ds": train_ds, "val_ds": val_ds, "test_ds": test_ds,
        "metadata": metadata,
    }

    return datasets


def save_step6_data(datasets):
    """保存第六步结果"""
    # 保存序列数据（numpy 数组）
    seq_data = {
        "X_train_seq": datasets["X_train_seq"],
        "y_train_seq": datasets["y_train_seq"],
        "X_val_seq": datasets["X_val_seq"],
        "y_val_seq": datasets["y_val_seq"],
        "X_test_seq": datasets["X_test_seq"],
        "y_test_seq": datasets["y_test_seq"],
        "metadata": datasets["metadata"],
    }
    fpath = os.path.join(PROCESSED_DIR, "step6_sequences.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(seq_data, f)
    print(f"\n[保存] {fpath}")
    print(f"  X_train_seq: {seq_data['X_train_seq'].shape}")
    print(f"  y_train_seq: {seq_data['y_train_seq'].shape}")
    print(f"  X_val_seq:   {seq_data['X_val_seq'].shape}")
    print(f"  y_val_seq:   {seq_data['y_val_seq'].shape}")
    print(f"  X_test_seq:  {seq_data['X_test_seq'].shape}")
    print(f"  y_test_seq:  {seq_data['y_test_seq'].shape}")

    # 保存数据管道配置（便于模型训练时重建 Dataset）
    pipeline_config = {
        "lookback": LOOKBACK,
        "horizon": HORIZON,
        "stride": STRIDE,
        "batch_size": BATCH_SIZE,
        "shuffle_buffer": SHUFFLE_BUFFER,
        "n_features": datasets["metadata"]["n_features"],
        "feature_cols": datasets["metadata"]["feature_cols"],
        "target": datasets["metadata"]["target"],
    }
    fpath = os.path.join(PROCESSED_DIR, "step6_pipeline_config.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(pipeline_config, f)
    print(f"[保存] {fpath}")


# ============================================================================
# 主流程：执行第六步序列化与TF数据管道
# ============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("第六步：序列化与 TensorFlow 数据管道构建")
    print("=" * 70)

    # 1. 加载第五步数据
    data, split_info = load_step5_data()

    # 2. 构建序列和 TF Dataset
    datasets = build_all_datasets(data, split_info)

    # 3. 保存
    save_step6_data(datasets)

    # 4. 最终概览
    print("\n" + "=" * 70)
    print("数据处理全部完成！最终数据概览")
    print("=" * 70)

    meta = datasets["metadata"]
    print(f"\n模型输入参数:")
    print(f"  lookback (回看窗口):   {meta['lookback']} 小时 ({meta['lookback']//24} 天)")
    print(f"  horizon  (预测步长):   {meta['horizon']} 小时")
    print(f"  n_features (特征数):   {meta['n_features']}")
    print(f"  预测目标:              {meta['target']}")

    print(f"\n训练集序列:")
    print(f"  X_train_seq: {datasets['X_train_seq'].shape}  (样本数, lookback, 特征数)")
    print(f"  y_train_seq: {datasets['y_train_seq'].shape}  (样本数, horizon)")

    print(f"\n验证集序列:")
    print(f"  X_val_seq:   {datasets['X_val_seq'].shape}")
    print(f"  y_val_seq:   {datasets['y_val_seq'].shape}")

    print(f"\n测试集序列:")
    print(f"  X_test_seq:  {datasets['X_test_seq'].shape}")
    print(f"  y_test_seq:  {datasets['y_test_seq'].shape}")

    print(f"\nTensorFlow Dataset (batch_size={BATCH_SIZE}):")
    print(f"  train_ds: {datasets['train_ds']}")
    print(f"  val_ds:   {datasets['val_ds']}")
    print(f"  test_ds:  {datasets['test_ds']}")

    # 测试数据管道：取一个 batch 验证
    print(f"\n数据管道测试 (取1个batch):")
    for x_batch, y_batch in datasets["train_ds"].take(1):
        print(f"  X batch: shape={x_batch.shape}, dtype={x_batch.dtype}")
        print(f"  y batch: shape={y_batch.shape}, dtype={y_batch.dtype}")
        print(f"  X range: [{x_batch.numpy().min():.4f}, {x_batch.numpy().max():.4f}]")
        print(f"  y range: [{y_batch.numpy().min():.4f}, {y_batch.numpy().max():.4f}]")

    print(f"\n输入特征列表 ({len(meta['feature_cols'])} 个):")
    for i, col in enumerate(meta["feature_cols"]):
        print(f"  [{i:2d}] {col}")

    print("\n" + "=" * 70)
    print("全部六步数据处理完成！数据已准备好用于模型训练。")
    print("=" * 70)
    print("\n保存的文件清单:")
    for fname in sorted(os.listdir(PROCESSED_DIR)):
        fpath = os.path.join(PROCESSED_DIR, fname)
        size = os.path.getsize(fpath) / 1024
        print(f"  {fname:40s} {size:>8.1f} KB")
