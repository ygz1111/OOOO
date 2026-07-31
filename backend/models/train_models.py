"""
训练脚本 - 本地版本
适用于本地有足够内存的场景（不推荐，优先使用 Colab）
"""

import os
import sys
import pickle
import numpy as np
import tensorflow as tf
from datetime import datetime

# 添加当前目录到路径
sys.path.append(os.path.dirname(__file__))

# 抑制 TF 日志
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

from lstm_model import LSTMModel
from transformer_model import TransformerModel
from tcn_model import TCNModel
from ensemble import EnsembleModelFactory, Evaluator, EnsembleModel
from visualizer import Visualizer


def load_data():
    """加载数据"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "processed")
    
    print(f"加载数据: {data_dir}")
    
    with open(os.path.join(data_dir, "step6_sequences.pkl"), "rb") as f:
        seq_data = pickle.load(f)
    
    with open(os.path.join(data_dir, "step5_scalers.pkl"), "rb") as f:
        scalers = pickle.load(f)
    
    return (seq_data["X_train_seq"], seq_data["y_train_seq"],
            seq_data["X_val_seq"], seq_data["y_val_seq"],
            seq_data["X_test_seq"], seq_data["y_test_seq"],
            scalers["target_scaler"])


def main():
    """主训练函数"""
    print("="*60)
    print("智能电网负荷预测 - 本地训练")
    print("="*60)
    print("⚠️  警告: 本地训练速度慢，建议使用 Google Colab")
    
    # 加载数据
    X_train, y_train, X_val, y_val, X_test, y_test, target_scaler = load_data()
    
    # 创建输出目录
    output_dir = os.path.join(os.path.dirname(__file__), "outputs")
    model_dir = os.path.join(output_dir, "saved_models")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(model_dir, exist_ok=True)
    
    # 创建可视化器
    visualizer = Visualizer(output_dir)
    
    # 训练配置
    EPOCHS = 100
    BATCH_SIZE = 32  # 本地减小批大小避免内存不足
    LEARNING_RATE = 1e-3
    
    # 模型配置
    LSTM_CONFIG = {"units": [128, 64], "dropout": 0.2, "l2_reg": 1e-5}
    TRANSFORMER_CONFIG = {"d_model": 128, "n_heads": 4, "n_layers": 2, "d_ff": 256, "dropout": 0.2, "l2_reg": 1e-5}
    TCN_CONFIG = {"nb_filters": [64, 128, 64], "kernel_size": 3, "dilations": [1, 2, 4], "dropout": 0.2, "l2_reg": 1e-5}
    
    # 训练全部模型
    ensemble, histories, weights = EnsembleModelFactory.train_all_ensemble(
        X_train, y_train, X_val, y_val,
        LSTM_CONFIG, TRANSFORMER_CONFIG, TCN_CONFIG,
        {"epochs": EPOCHS, "batch_size": BATCH_SIZE, "learning_rate": LEARNING_RATE},
        model_dir
    )
    
    # 评估和可视化
    results = {}
    for name, model in zip(["LSTM", "Transformer", "TCN"], ensemble.models):
        y_pred = model.predict(X_test)
        metrics, hourly_metrics, peak_metrics, _ = evaluate_model(model, X_test, y_test, target_scaler, name)
        
        visualize_results(model, X_test, y_pred, target_scaler, histories[name], name, metrics, hourly_metrics, visualizer)
        
        results[name] = {
            "metrics": metrics,
            "hourly_metrics": hourly_metrics,
            "peak_metrics": peak_metrics,
        }
    
    # 集成模型
    y_pred_ensemble = ensemble.predict(X_test)
    metrics, hourly_metrics, peak_metrics, _ = evaluate_model(ensemble, X_test, y_test, target_scaler, "Ensemble")
    visualize_results(ensemble, X_test, y_pred_ensemble, target_scaler, None, "Ensemble", metrics, hourly_metrics, visualizer)
    
    results["Ensemble"] = {
        "metrics": metrics,
        "hourly_metrics": hourly_metrics,
        "peak_metrics": peak_metrics,
        "weights": list(weights)
    }
    
    # 保存结果
    print("\n保存评估结果...")
    import json
    results_simple = {
        name: {
            "MAPE": float(r["metrics"]["MAPE"]),
            "RMSE": float(r["metrics"]["RMSE"]),
            "MAE": float(r["metrics"]["MAE"]),
            "R2": float(r["metrics"]["R2"]),
            "peak_MAPE": float(r["peak_metrics"]["peak_mape"]),
        }
        for name, r in results.items()
    }
    if "Ensemble" in results:
        results_simple["Ensemble"]["weights"] = results["Ensemble"]["weights"]
    
    visualizer.save_metrics_json(results_simple)
    
    # 生成对比图
    visualizer.plot_model_comparison({name: r["metrics"] for name, r in results.items()}, "MAPE")
    visualizer.plot_model_comparison({name: r["metrics"] for name, r in results.items()}, "RMSE")
    
    print("\n" + "="*60)
    print("训练完成！")
    print("="*60)
    for name, r in results_simple.items():
        print(f"\n{name}:")
        print(f"  MAPE: {r['MAPE']:.2f}%")
        print(f"  RMSE: {r['RMSE']:.2f} MW")
        print(f"  R²:   {r['R2']:.4f}")
        if 'peak_MAPE' in r:
            print(f"  峰值MAPE: {r['peak_MAPE']:.2f}%")
    
    print(f"\n所有文件已保存到: {output_dir}")


def evaluate_model(model, X_test, y_test, scaler, model_name):
    """评估模型"""
    y_pred = model.predict(X_test)
    metrics = Evaluator.calculate_metrics(y_test, y_pred)
    Evaluator.print_evaluation_report(metrics, model_name)
    return metrics, Evaluator.calculate_hourly_metrics(y_test, y_pred), Evaluator.calculate_peak_metrics(y_test, y_pred, scaler), y_pred


def visualize_results(model, y_test, y_pred, scaler, history, model_name, metrics, hourly_metrics, visualizer):
    """可视化结果"""
    visualizer.plot_training_history(history, model_name)
    visualizer.plot_prediction_comparison(y_test, y_pred, scaler, model_name)
    visualizer.plot_prediction_7days(y_test, y_pred, scaler, model_name)
    visualizer.plot_error_distribution(y_test, y_pred, scaler, model_name)
    visualizer.plot_scatter(y_test, y_pred, scaler, model_name)
    visualizer.plot_hourly_error(hourly_metrics, model_name)


if __name__ == "__main__":
    main()