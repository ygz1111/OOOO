#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重新计算四个模型 + 集成模型在测试集上的真实评估指标。

背景：原 train_four_models.py 在"归一化空间"计算 RMSE/MAPE，且 MAPE 公式三处
实现不一致（分母趋零导致 MAPE 虚高 16%~44%）。本脚本统一口径：

  1. 加载 step6_sequences.pkl 的测试集（归一化空间）
  2. 用 target_scaler 反归一化到真实 MW 单位
  3. 统一指标公式（反归一化后计算 MAE/RMSE/MAPE/R²，MAPE 用 |y_true|>1 掩码防除零）
  4. 集成模型 = 四模型等权重平均（与系统 ensemble_weights 一致）
  5. 将真实指标写回 models/models/final_results.json

用法：
    cd backend
    python scripts/recompute_final_metrics.py [--sample N]
"""

import os
import sys
import json
import argparse
import pickle
import logging
from datetime import datetime

import numpy as np
import torch

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("recompute_metrics")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(BACKEND_DIR, "..", "processed")
MODELS_DIR = os.path.join(BACKEND_DIR, "models", "models")

sys.path.insert(0, BACKEND_DIR)
from models.four_models import (  # noqa: E402
    EnhancedLSTM,
    SpatialTemporalTransformer,
    DeepTCN,
    BiGRU,
)

MODEL_SPECS = {
    "EnhancedLSTM": ("enhancedlstm_best_model.pth", EnhancedLSTM),
    "SpatialTransformer": ("spatialtransformer_best_model.pth", SpatialTemporalTransformer),
    "DeepTCN": ("deeptcn_best_model.pth", DeepTCN),
    "BiGRU": ("bigru_best_model.pth", BiGRU),
}

# 与训练脚本 create_four_models 完全一致的模型参数
MODEL_KWARGS = {
    "EnhancedLSTM": dict(input_size=38, hidden_size=128, num_layers=3,
                         output_size=24, dropout=0.3, l2_reg=1e-4),
    "SpatialTransformer": dict(input_size=38, d_model=128, nhead=8, num_layers=4,
                               d_ff=512, output_size=24, dropout=0.3, l2_reg=1e-4),
    "DeepTCN": dict(input_size=38, num_channels=[64, 128, 64, 32],
                    output_size=24, dropout=0.3, l2_reg=1e-4),
    "BiGRU": dict(input_size=38, hidden_size=128, num_layers=3,
                  output_size=24, dropout=0.3, l2_reg=1e-4),
}


def load_test_data(sample: int):
    """加载测试集与目标 scaler"""
    with open(os.path.join(PROCESSED_DIR, "step6_sequences.pkl"), "rb") as f:
        seq = pickle.load(f)
    with open(os.path.join(PROCESSED_DIR, "step5_scalers.pkl"), "rb") as f:
        scalers = pickle.load(f)

    X_test = torch.FloatTensor(np.array(seq["X_test_seq"]))
    y_test = torch.FloatTensor(np.array(seq["y_test_seq"]))
    target_scaler = scalers["target_scaler"]

    if sample and sample < len(X_test):
        rng = np.random.RandomState(0)
        idx = rng.choice(len(X_test), sample, replace=False)
        X_test = X_test[idx]
        y_test = y_test[idx]

    logger.info(f"测试集: {len(X_test)} 个序列, 输入 {tuple(X_test.shape[1:])}, "
                f"目标 {tuple(y_test.shape[1:])}")
    return X_test, y_test, target_scaler


def load_model(model_name: str, device: torch.device):
    """加载训练好的模型权重"""
    fname, model_cls = MODEL_SPECS[model_name]
    path = os.path.join(MODELS_DIR, fname)
    if not os.path.exists(path):
        raise FileNotFoundError(f"模型文件不存在: {path}")
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    model = model_cls(**MODEL_KWARGS[model_name])
    model.load_state_dict(ckpt["model_state_dict"])
    model.to(device).eval()
    logger.info(f"  加载 {model_name} <- {fname}")
    return model


def compute_metrics(y_true_mw: np.ndarray, y_pred_mw: np.ndarray) -> dict:
    """统一指标：全部在真实 MW 单位计算"""
    y_true = y_true_mw.flatten()
    y_pred = y_pred_mw.flatten()

    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    # MAPE：|y_true|>1 MW 掩码，避免小值放大误差
    mask = np.abs(y_true) > 1.0
    mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100) if np.any(mask) else float("nan")
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")

    return {"mae": mae, "rmse": rmse, "mape": mape, "r2": r2}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0,
                        help="抽样序列数（默认 0 = 全量测试集）")
    parser.add_argument("--device", type=str, default="auto")
    args = parser.parse_args()

    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    logger.info(f"推理设备: {device}")

    X_test, y_test, target_scaler = load_test_data(args.sample)

    all_preds = {}
    for name in MODEL_SPECS:
        model = load_model(name, device)
        with torch.no_grad():
            pred = model(X_test).cpu().numpy()
        all_preds[name] = pred
        logger.info(f"  {name} 推理完成: {pred.shape}")

    # 集成 = 等权重平均（与系统 ensemble_weights 0.25/0.25/0.25/0.25 一致）
    ensemble_pred = np.mean([all_preds[n] for n in MODEL_SPECS], axis=0)

    # 反归一化到 MW
    def inv_transform(x):
        return target_scaler.inverse_transform(x.reshape(-1, 1)).reshape(x.shape)

    y_test_mw = inv_transform(np.array(y_test))
    results = {"models": [], "results": {}, "meta": {}}
    for name in MODEL_SPECS:
        pred_mw = inv_transform(all_preds[name])
        metrics = compute_metrics(y_test_mw, pred_mw)
        results["results"][name] = metrics
        results["models"].append(name)
        logger.info(f"  {name}: MAE={metrics['mae']:.1f}MW RMSE={metrics['rmse']:.1f}MW "
                    f"MAPE={metrics['mape']:.2f}% R²={metrics['r2']:.4f}")

    ens_metrics = compute_metrics(y_test_mw, inv_transform(ensemble_pred))
    results["results"]["Ensemble"] = ens_metrics
    results["models"].append("Ensemble")
    logger.info(f"  Ensemble: MAE={ens_metrics['mae']:.1f}MW RMSE={ens_metrics['rmse']:.1f}MW "
                f"MAPE={ens_metrics['mape']:.2f}% R²={ens_metrics['r2']:.4f}")

    results["meta"] = {
        "test_samples": len(X_test),
        "unit": "MW (反归一化后)",
        "computed_at": datetime.now().isoformat(),
        "note": "指标基于测试集真实反归一化值计算；MAPE 使用 |y_true|>1 掩码。"
                "旧版归一化空间指标已作废。",
    }

    out_path = os.path.join(MODELS_DIR, "final_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ 真实指标已写入: {out_path}")


if __name__ == "__main__":
    main()
