#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
论文图表生成：加载已训练模型 → 测试集推理 → 生成图表（无需重训）

复用 models/visualization.py 的 PaperVisualizer：
  - 四模型性能对比主图（训练收敛/预测效果/雷达图/特征重要性/误差分布/复杂度）
  - 每个模型的深度分析图（训练过程/预测对比/残差/不确定性）
  - 图表说明文档（300 DPI）

用法：
    cd backend
    python scripts/generate_paper_figures.py [--sample 150] [--output ../../visualizations]
"""
import os
import sys
import argparse
import pickle
import logging
from datetime import datetime

import numpy as np
import torch

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(BACKEND_DIR, "..", "processed")
MODELS_DIR = os.path.join(BACKEND_DIR, "models", "models")
DEFAULT_OUTPUT = os.path.join(BACKEND_DIR, "..", "visualizations")

sys.path.insert(0, BACKEND_DIR)
from models.four_models import (  # noqa: E402
    EnhancedLSTM,
    SpatialTemporalTransformer,
    DeepTCN,
    BiGRU,
)
from models.visualization import PaperVisualizer  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("paper_figures")

MODEL_SPECS = {
    "EnhancedLSTM": ("enhancedlstm_best_model.pth", EnhancedLSTM,
                     dict(input_size=38, hidden_size=128, num_layers=3,
                          output_size=24, dropout=0.3, l2_reg=1e-4)),
    "SpatialTransformer": ("spatialtransformer_best_model.pth", SpatialTemporalTransformer,
                           dict(input_size=38, d_model=128, nhead=8, num_layers=4,
                                d_ff=512, output_size=24, dropout=0.3, l2_reg=1e-4)),
    "DeepTCN": ("deeptcn_best_model.pth", DeepTCN,
                dict(input_size=38, num_channels=[64, 128, 64, 32],
                     output_size=24, dropout=0.3, l2_reg=1e-4)),
    "BiGRU": ("bigru_best_model.pth", BiGRU,
              dict(input_size=38, hidden_size=128, num_layers=3,
                   output_size=24, dropout=0.3, l2_reg=1e-4)),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=150,
                        help="测试集抽样序列数（CPU 推理，默认 150）")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", type=str, default="auto")
    args = parser.parse_args()

    device = torch.device(
        "cuda" if torch.cuda.is_available() and args.device == "auto" else
        ("cuda" if args.device == "cuda" and torch.cuda.is_available() else "cpu")
    )
    logger.info(f"推理设备: {device} | 输出目录: {args.output}")

    # 1. 加载测试集
    with open(os.path.join(PROCESSED_DIR, "step6_sequences.pkl"), "rb") as f:
        seq = pickle.load(f)
    with open(os.path.join(PROCESSED_DIR, "step5_scalers.pkl"), "rb") as f:
        scalers = pickle.load(f)
    X_test = torch.FloatTensor(np.array(seq["X_test_seq"]))
    y_test = torch.FloatTensor(np.array(seq["y_test_seq"]))
    target_scaler = scalers["target_scaler"]
    logger.info(f"测试集: {len(X_test)} 序列, 输入 {tuple(X_test.shape[1:])}")

    # 抽样控制推理时间
    if args.sample and args.sample < len(X_test):
        rng = np.random.RandomState(42)
        idx = rng.choice(len(X_test), args.sample, replace=False)
        X_test, y_test = X_test[idx], y_test[idx]

    # 2. 加载模型并推理
    training_results = {}
    for name, (fname, model_cls, kwargs) in MODEL_SPECS.items():
        path = os.path.join(MODELS_DIR, fname)
        if not os.path.exists(path):
            logger.warning(f"模型文件缺失，跳过 {name}: {path}")
            continue
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        model = model_cls(**kwargs)
        model.load_state_dict(ckpt["model_state_dict"])
        model.to(device).eval()

        with torch.no_grad():
            pred_norm = model(X_test.to(device)).cpu().numpy()
        true_norm = y_test.numpy()

        # 反归一化到 MW
        pred_mw = target_scaler.inverse_transform(
            pred_norm.reshape(-1, 1)).reshape(pred_norm.shape)
        true_mw = target_scaler.inverse_transform(
            true_norm.reshape(-1, 1)).reshape(true_norm.shape)

        training_results[name] = {
            "model": model,
            "best_state_dict": ckpt["model_state_dict"],
            "training_history": ckpt.get("training_history") or {
                "train_loss": [], "val_loss": []},
            "predictions": pred_mw,
            "targets": true_mw,
            "epochs_trained": len((ckpt.get("training_history") or {}).get("train_loss", [])),
            "total_params": sum(p.numel() for p in model.parameters()),
            "model_name": name,
            # 真实特征重要性所需
            "X_test": X_test,
            "y_test": y_test,
            "feature_names": None,
        }
        logger.info(f"  {name} 推理完成（{len(pred_mw)} 序列）")

    if not training_results:
        logger.error("没有任何模型可加载，请先训练模型")
        sys.exit(1)

    # 加载真实特征名（供特征重要性图）
    split_info_path = os.path.join(PROCESSED_DIR, "step5_split_info.pkl")
    if os.path.exists(split_info_path):
        with open(split_info_path, "rb") as f:
            training_results["feature_names"] = pickle.load(f).get("feature_cols")

    # 3. 生成图表（model_names 只传 4 个模型，feature_names 是顶层元数据）
    os.makedirs(args.output, exist_ok=True)
    visualizer = PaperVisualizer(args.output)
    visualizer.create_paper_ready_figures(
        training_results, model_names=list(MODEL_SPECS.keys())
    )
    logger.info(f"✅ 论文图表已生成到 {args.output}")


if __name__ == "__main__":
    main()
