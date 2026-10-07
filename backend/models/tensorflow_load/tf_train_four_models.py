# -*- coding: utf-8 -*-
"""TensorFlow 四模型实验训练脚本。

数据: processed/step6_sequences.pkl（原始 2023~2025 数据）
      已按时序切分:
        Train: 2023-01-08 ~ 2024-12-31
        Val:   2025-01-01 ~ 2025-09-30
        Test:  2025-10-01 ~ 2025-12-31
Scaler: processed/step5_scalers.pkl（原始 scaler，只读用于逆归一化）

训练超参数:
  - loss = MSE (归一化空间) + coupled L2: 0.5 * 1e-4 * Σ w²
  - optimizer = Adam(learning_rate=1e-3, clipnorm=1.0)
  - batch_size = 64
  - epochs = 100
  - EarlyStopping: monitor=val_loss, patience=15, restore_best_weights=True
  - ReduceLROnPlateau: monitor=val_loss, factor=0.5, patience=10
  - Dropout = 0.3

训练顺序:
  EnhancedLSTM → SpatialTransformer → DeepTCN → BiGRU
"""

import argparse
import json
import os
import pickle
import sys
import time
from datetime import datetime

import numpy as np
import tensorflow as tf

# 尝试灵活导入
try:
    from models.tensorflow_load.tf_four_models import (
        create_tf_four_models,
        build_enhanced_lstm,
        build_spatial_transformer,
        build_deep_tcn,
        build_bigru,
        LOOKBACK,
        INPUT_DIM,
        OUTPUT_DIM,
    )
except ImportError:
    from tf_four_models import (
        create_tf_four_models,
        build_enhanced_lstm,
        build_spatial_transformer,
        build_deep_tcn,
        build_bigru,
        LOOKBACK,
        INPUT_DIM,
        OUTPUT_DIM,
    )

L2_REG = 1e-4

PRODUCTION_WEIGHTS = {
    "EnhancedLSTM": 0.2412,
    "BiGRU": 0.1875,
    "DeepTCN": 0.1757,
    "SpatialTransformer": 0.3956,
}


def check_environment():
    """按要求自检环境并打印 GPU / 框架信息"""
    print("=" * 64)
    print("【训练环境检查】")
    print(f"  Python Version:     {sys.version.split()[0]}")
    print(f"  TensorFlow Version: {tf.__version__}")
    gpus = tf.config.list_physical_devices("GPU")
    print(f"  GPU Device Count:   {len(gpus)}")
    gpu_name = "None"
    if gpus:
        try:
            gpu_details = tf.config.experimental.get_device_details(gpus[0])
            gpu_name = gpu_details.get("device_name", str(gpus[0]))
        except Exception:
            gpu_name = str(gpus[0])
    print(f"  GPU Device:         {gpus[0] if gpus else 'No GPU'}")
    print(f"  GPU Name:           {gpu_name}")
    print(f"  CUDA Built:         {tf.test.is_built_with_cuda()}")
    print("=" * 64)

    if not gpus:
        print("❌ 警告：未检测到 GPU 加速设备！请检查 CUDA / GPU 分配。")
    return bool(gpus)


def load_data(data_path: str, scalers_path: str):
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"序列数据文件未找到: {data_path}")
    if not os.path.exists(scalers_path):
        raise FileNotFoundError(f"Scaler 文件未找到: {scalers_path}")

    with open(data_path, "rb") as f:
        seq = pickle.load(f)
    with open(scalers_path, "rb") as f:
        scalers = pickle.load(f)

    data = {
        k: np.asarray(seq[k], dtype=np.float32)
        for k in ("X_train_seq", "y_train_seq", "X_val_seq", "y_val_seq", "X_test_seq", "y_test_seq")
    }
    target_scaler = scalers["target_scaler"]
    meta = seq.get("metadata", {})
    return data, target_scaler, meta


def make_tf_dataset(X, y, batch_size, shuffle):
    ds = tf.data.Dataset.from_tensor_slices((X, y))
    if shuffle:
        ds = ds.shuffle(buffer_size=len(X), reshuffle_each_iteration=True)
    ds = ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)
    return ds


def coupled_l2_loss(model, wd=L2_REG):
    """MSE + 0.5 * wd * Σ w² 的耦合 L2 损失。"""
    def loss_fn(y_true, y_pred):
        mse = tf.reduce_mean(tf.square(y_true - y_pred))
        l2 = tf.add_n([tf.reduce_sum(tf.square(w)) for w in model.trainable_weights])
        return mse + 0.5 * wd * l2
    return loss_fn


def compute_metrics_mw(pred_mw: np.ndarray, true_mw: np.ndarray):
    """计算真实 MW 空间的评估指标"""
    mse = float(np.mean((true_mw - pred_mw) ** 2))
    rmse = float(np.sqrt(mse))
    mae = float(np.mean(np.abs(true_mw - pred_mw)))
    mask = np.abs(true_mw) > 1.0
    mape = float(np.mean(np.abs((true_mw[mask] - pred_mw[mask]) / true_mw[mask])) * 100) if np.any(mask) else None
    ss_res = float(np.sum((true_mw - pred_mw) ** 2))
    ss_tot = float(np.sum((true_mw - np.mean(true_mw)) ** 2))
    r2 = float(1.0 - ss_res / (ss_tot + 1e-10))
    return {
        "mae_mw": round(mae, 1),
        "rmse_mw": round(rmse, 1),
        "mape": round(mape, 3) if mape is not None else None,
        "r2": round(r2, 4),
        "pred_min_mw": round(float(pred_mw.min()), 1),
        "pred_max_mw": round(float(pred_mw.max()), 1),
    }


def train_one_model(model_name, model_fn, data, target_scaler, batch_size, epochs, lr, out_dir, smoke):
    """训练单模型，返回 (history, metrics, pred_mw)"""
    model_dir = os.path.join(out_dir, model_name)
    os.makedirs(model_dir, exist_ok=True)

    X_train, y_train = data["X_train_seq"], data["y_train_seq"]
    X_val, y_val = data["X_val_seq"], data["y_val_seq"]
    X_test, y_test = data["X_test_seq"], data["y_test_seq"]

    train_ds = make_tf_dataset(X_train, y_train, batch_size, shuffle=True)
    val_ds = make_tf_dataset(X_val, y_val, batch_size, shuffle=False)

    model = model_fn()
    n_params = sum(int(np.prod(w.shape)) for w in model.trainable_weights)
    print(f"\n========================================================")
    print(f"🚀 开始训练: {model_name} (参数量: {n_params:,})")
    print(f"========================================================")

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=lr, clipnorm=1.0),
        loss=coupled_l2_loss(model),
        metrics=["mse"],
    )

    ckpt_path = os.path.join(model_dir, "ckpt_best.keras")
    callbacks = [
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=10, verbose=1
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=15, restore_best_weights=True, verbose=1
        ),
        tf.keras.callbacks.ModelCheckpoint(
            filepath=ckpt_path, monitor="val_loss", save_best_only=True, save_freq="epoch", verbose=0
        ),
    ]

    t0 = time.time()
    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=smoke if smoke else epochs,
        callbacks=callbacks,
        verbose=2,
    )
    train_seconds = round(time.time() - t0, 1)

    hist_dict = {k: [float(v) for v in vals] for k, vals in history.history.items()}
    best_epoch = int(np.argmin(hist_dict["val_loss"])) + 1

    # 保存最终模型及配置
    final_model_path = os.path.join(model_dir, f"best_{model_name}.keras")
    model.save(final_model_path)
    with open(os.path.join(model_dir, "training_history.json"), "w", encoding="utf-8") as f:
        json.dump(hist_dict, f, indent=2)

    # 测试集评估
    pred_norm = model.predict(X_test, batch_size=1024, verbose=0)
    pred_mw = target_scaler.inverse_transform(pred_norm.reshape(-1, 1)).reshape(pred_norm.shape)
    true_mw = target_scaler.inverse_transform(y_test.reshape(-1, 1)).reshape(y_test.shape)

    metrics = compute_metrics_mw(pred_mw, true_mw)
    metrics["epochs_trained"] = len(hist_dict.get("loss", []))
    metrics["best_epoch"] = best_epoch
    metrics["train_seconds"] = train_seconds
    metrics["params"] = n_params

    # 保存预测值与真值
    np.save(os.path.join(model_dir, "predictions.npy"), pred_mw)

    with open(os.path.join(model_dir, "model_config.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": model_name,
            "params": n_params,
            "best_epoch": best_epoch,
            "epochs_trained": metrics["epochs_trained"],
            "train_seconds": train_seconds,
            "metrics": metrics,
        }, f, indent=2)

    print(f"\n📊 [{model_name} 训练完成]")
    print(f"   耗时: {train_seconds}s | 训练轮数: {metrics['epochs_trained']} | 最优 Epoch: {best_epoch}")
    print(f"   MAE: {metrics['mae_mw']} MW | RMSE: {metrics['rmse_mw']} MW | MAPE: {metrics['mape']}% | R²: {metrics['r2']}")

    return model, hist_dict, metrics, pred_mw, true_mw


def main():
    parser = argparse.ArgumentParser(description="TensorFlow 四模型标准训练")
    parser.add_argument("--data", default="processed/step6_sequences.pkl")
    parser.add_argument("--scalers", default="processed/step5_scalers.pkl")
    parser.add_argument("--out", default="models/tensorflow_load/artifacts/tf_orig")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--model", type=str, default="all", help="指定模型名称或 all")
    parser.add_argument("--smoke", type=int, default=0, help="冒烟测试 epoch 数")
    args = parser.parse_args()

    check_environment()

    os.makedirs(args.out, exist_ok=True)
    print(f"\n[数据配置]")
    print(f"  序列文件: {args.data}")
    print(f"  Scaler文件: {args.scalers}")
    print(f"  输出目录: {args.out}")

    data, target_scaler, meta = load_data(args.data, args.scalers)
    print(f"  Train: X {data['X_train_seq'].shape}, y {data['y_train_seq'].shape}")
    print(f"  Val:   X {data['X_val_seq'].shape}, y {data['y_val_seq'].shape}")
    print(f"  Test:  X {data['X_test_seq'].shape}, y {data['y_test_seq'].shape}")

    # 保存测试集真值 (真实 MW)
    y_test = data["y_test_seq"]
    true_mw = target_scaler.inverse_transform(y_test.reshape(-1, 1)).reshape(y_test.shape)
    np.save(os.path.join(args.out, "predictions_true.npy"), true_mw)

    model_registry = {
        "EnhancedLSTM": lambda: build_enhanced_lstm(input_size=INPUT_DIM, output_size=OUTPUT_DIM),
        "SpatialTransformer": lambda: build_spatial_transformer(input_size=INPUT_DIM, output_size=OUTPUT_DIM),
        "DeepTCN": lambda: build_deep_tcn(input_size=INPUT_DIM, output_size=OUTPUT_DIM),
        "BiGRU": lambda: build_bigru(input_size=INPUT_DIM, output_size=OUTPUT_DIM),
    }

    if args.model != "all":
        if args.model not in model_registry:
            raise ValueError(f"未知模型 {args.model}，可选: {list(model_registry.keys())}")
        to_train = [args.model]
    else:
        to_train = ["EnhancedLSTM", "SpatialTransformer", "DeepTCN", "BiGRU"]

    results = {}
    preds_dict = {}

    for name in to_train:
        model, hist, metrics, pred_mw, _ = train_one_model(
            model_name=name,
            model_fn=model_registry[name],
            data=data,
            target_scaler=target_scaler,
            batch_size=args.batch,
            epochs=args.epochs,
            lr=args.lr,
            out_dir=args.out,
            smoke=args.smoke,
        )
        results[name] = metrics
        preds_dict[name] = pred_mw

    # 如果训练完全部 4 个模型，计算生产权重加权集成
    if len(preds_dict) == 4:
        print("\n========================================================")
        print("🎯 计算生产权重 Ensemble (EnhancedLSTM:0.2412, BiGRU:0.1875, DeepTCN:0.1757, SpatialTransformer:0.3956)")
        print("========================================================")
        ens_pred_mw = sum(PRODUCTION_WEIGHTS[n] * preds_dict[n] for n in PRODUCTION_WEIGHTS)
        ens_metrics = compute_metrics_mw(ens_pred_mw, true_mw)
        results["Ensemble"] = ens_metrics
        np.save(os.path.join(args.out, "predictions_ensemble.npy"), ens_pred_mw)
        print(f"   Ensemble 指标: MAE {ens_metrics['mae_mw']} MW | RMSE {ens_metrics['rmse_mw']} MW | "
              f"MAPE {ens_metrics['mape']}% | R² {ens_metrics['r2']}")

    # 汇总保存 evaluation_results.json 与 metrics.json
    summary = {
        "results": results,
        "weights": PRODUCTION_WEIGHTS,
        "config": {
            "epochs": args.epochs,
            "batch_size": args.batch,
            "learning_rate": args.lr,
            "l2_reg": L2_REG,
            "trained_at": datetime.now().isoformat(timespec="seconds"),
        },
        "test_samples": len(true_mw),
    }

    eval_file = os.path.join(args.out, "evaluation_results.json")
    metrics_file = os.path.join(args.out, "metrics.json")
    with open(eval_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    with open(metrics_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 全部训练与评估产物已保存: {eval_file}")


if __name__ == "__main__":
    main()
