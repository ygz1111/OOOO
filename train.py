"""
========================================
智能电网负荷预测 - 完整训练脚本
========================================
适用于 Google Colab / 本地训练

功能：
1. 自动下载数据（支持 Google Drive / GitHub）
2. 训练 3 个模型：LSTM / Transformer / TCN
3. 集成模型（加权平均）
4. 自动保存：
   - 模型权重
   - 训练曲线
   - 预测图表
   - 评估指标
   - 所有毕业论文所需图表和数据

使用方法（Google Colab）：
1. 上传本文件到 Colab
2. 修改 DATA_SOURCE 配置
3. 运行所有单元格
4. 下载 outputs/ 文件夹到本地

使用方法（本地）：
1. 确保数据处理已完成（已生成 processed/ 目录）
2. 运行脚本
3. 结果保存到 outputs/ 和 saved_models/
"""

import os
import sys
import pickle
import json
import numpy as np
import tensorflow as tf
from datetime import datetime

# 设置日志
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 抑制 TensorFlow 日志
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# ============================================================================
# 配置区域 - 修改这里
# ============================================================================

# ============ 数据源配置 ============
# 选项 1：从 Google Drive 下载（推荐用于 Colab）
# 1. 将 processed 文件夹压缩为 processed.zip
# 2. 上传到 Google Drive
# 3. 填写 file_id
DATA_SOURCE = "gdrive"  # 可选: "gdrive" | "github" | "local"

# Google Drive 配置
GDRIVE_FILE_ID = ""  # 填写 Google Drive file_id

# GitHub 配置
GITHUB_REPO = "your-username/your-repo"  # 修改为你的 GitHub 仓库
GITHUB_BRANCH = "main"

# 本地数据路径
LOCAL_DATA_DIR = "../processed"

# ============ 训练配置 ============
EPOCHS = 100  # 最大训练轮数
BATCH_SIZE = 64
LEARNING_RATE = 1e-3
PATIENCE = 10
MIN_LR = 1e-6

# 是否只训练单个模型（用于快速测试）
TRAIN_SINGLE_MODEL = False  # True 只训练 LSTM，False 训练全部3个模型
SINGLE_MODEL_NAME = "lstm"  # 可选: "lstm" | "transformer" | "tcn"

# ============ 模型配置 ============
LSTM_CONFIG = {
    "units": [128, 64],
    "dropout": 0.2,
    "l2_reg": 1e-5,
}

TRANSFORMER_CONFIG = {
    "d_model": 128,
    "n_heads": 4,
    "n_layers": 2,
    "d_ff": 256,
    "dropout": 0.2,
    "l2_reg": 1e-5,
}

TCN_CONFIG = {
    "nb_filters": [64, 128, 64],
    "kernel_size": 3,
    "dilations": [1, 2, 4],
    "dropout": 0.2,
    "l2_reg": 1e-5,
}

# ============================================================================
# 数据加载
# ============================================================================

def load_data_from_gdrive(file_id):
    """从 Google Drive 下载数据"""
    from google.colab import drive
    
    logger.info("挂载 Google Drive...")
    drive.mount('/content/drive')
    
    # 复制文件
    src_path = f"/content/drive/MyDrive/{file_id}"
    zip_path = f"/content/{file_id}"
    
    import shutil
    if os.path.exists(zip_path):
        logger.info(f"Google Drive 中找到文件，跳过下载")
    else:
        logger.info(f"从 Google Drive 复制: {file_id}")
        # 这里需要你先手动上传文件到 Drive，然后填正确的 file_id
    
    # 解压
    logger.info("解压数据...")
    import zipfile
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall('/content/data')
    
    data_dir = '/content/data/processed'
    return data_dir

def load_data_from_github(repo, branch):
    """从 GitHub 下载数据"""
    logger.info(f"从 GitHub 克隆仓库: {repo}, branch: {branch}")
    
    import subprocess
    subprocess.run(['git', 'clone', '-b', branch, f'https://github.com/{repo}.git', '/content/repo'])
    
    data_dir = '/content/repo/processed'
    return data_dir

def load_data_local():
    """使用本地数据"""
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), LOCAL_DATA_DIR))
    logger.info(f"使用本地数据目录: {data_dir}")
    return data_dir

def load_data():
    """加载数据（根据配置选择数据源）"""
    if DATA_SOURCE == "gdrive":
        return load_data_from_gdrive(GDRIVE_FILE_ID)
    elif DATA_SOURCE == "github":
        return load_data_from_github(GITHUB_REPO, GITHUB_BRANCH)
    else:
        return load_data_local()

def load_processed_data(data_dir):
    """加载预处理后的数据"""
    logger.info(f"从 {data_dir} 加载数据...")
    
    # 加载序列数据
    with open(os.path.join(data_dir, "step6_sequences.pkl"), "rb") as f:
        seq_data = pickle.load(f)
    
    # 加载 Scalers
    with open(os.path.join(data_dir, "step5_scalers.pkl"), "rb") as f:
        scalers = pickle.load(f)
    
    # 加载划分信息
    with open(os.path.join(data_dir, "step5_split_info.pkl"), "rb") as f:
        split_info = pickle.load(f)
    
    X_train = seq_data["X_train_seq"]
    y_train = seq_data["y_train_seq"]
    X_val = seq_data["X_val_seq"]
    y_val = seq_data["y_val_seq"]
    X_test = seq_data["X_test_seq"]
    y_test = seq_data["y_test_seq"]
    
    target_scaler = scalers["target_scaler"]
    
    logger.info(f"训练集: X={X_train.shape}, y={y_train.shape}")
    logger.info(f"验证集: X={X_val.shape}, y={y_val.shape}")
    logger.info(f"测试集: X={X_test.shape}, y={y_test.shape}")
    
    return X_train, y_train, X_val, y_val, X_test, y_test, target_scaler, split_info


# ============================================================================
# 模型导入
# ============================================================================

def import_models():
    """导入模型定义"""
    import sys
    sys.path.append('/content/models')  # Colab 路径
    
    from lstm_model import LSTMModel
    from transformer_model import TransformerModel
    from tcn_model import TCNModel
    from ensemble import EnsembleModel, EnsembleModelFactory, Evaluator
    from visualizer import Visualizer
    
    return LSTMModel, TransformerModel, TCNModel, EnsembleModel, EnsembleModelFactory, Evaluator, Visualizer


# ============================================================================
# 训练流程
# ============================================================================

def train_model(model_class, model_name, config, X_train, y_train, X_val, y_val, 
                 output_dir, checkpoint_path):
    """训练单个模型"""
    logger.info(f"\n{'='*60}")
    logger.info(f"训练 {model_name.upper()} 模型...")
    logger.info(f"{'='*60}")
    
    lookback, n_features = X_train.shape[1:]
    horizon = y_train.shape[1]
    
    # 创建模型
    model = model_class(
        input_shape=(lookback, n_features),
        output_dim=horizon,
        config=config
    )
    
    # 构建
    model.build()
    
    # 编译
    model.compile(learning_rate=LEARNING_RATE)
    
    # 训练
    history = model.train(
        X_train, y_train,
        X_val, y_val,
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        checkpoint_path=checkpoint_path
    )
    
    # 保存模型（不使用 checkpoint，因为已经保存了）
    model_save_path = os.path.join(output_dir, f"{model_name}_model.h5")
    model.save(model_save_path)
    
    return model, history


def evaluate_model(model, X_test, y_test, scaler, model_name):
    """评估模型"""
    logger.info(f"\n评估 {model_name}...")
    
    # 预测
    y_pred = model.predict(X_test)
    
    # 计算指标
    metrics = Evaluator.calculate_metrics(y_test, y_pred)
    hourly_metrics = Evaluator.calculate_hourly_metrics(y_test, y_pred)
    peak_metrics = Evaluator.calculate_peak_metrics(y_test, y_pred, scaler)
    
    Evaluator.print_evaluation_report(metrics, model_name)
    
    # 打印峰值指标
    print(f"\n峰值时段分析 (前95%分位数):")
    print(f"  峰值阈值: {peak_metrics['peak_threshold']:.2f} MW")
    print(f"  峰值样本数: {peak_metrics['peak_count']}")
    print(f"  峰值 MAPE: {peak_metrics['peak_mape']:.2f}%")
    print(f"  峰值 MAE: {peak_metrics['peak_mae']:.2f} MW")
    
    return metrics, hourly_metrics, peak_metrics, y_pred


def visualize_results(model, y_test, y_pred, scaler, history, 
                       model_name, metrics, hourly_metrics, visualizer):
    """生成可视化结果"""
    logger.info(f"\n生成 {model_name} 可视化图表...")
    
    # 1. 训练历史
    visualizer.plot_training_history(history, model_name)
    
    # 2. 24小时预测对比
    visualizer.plot_prediction_comparison(y_test, y_pred, scaler, model_name)
    
    # 3. 7天连续预测
    visualizer.plot_prediction_7days(y_test, y_pred, scaler, model_name)
    
    # 4. 误差分布
    visualizer.plot_error_distribution(y_test, y_pred, scaler, model_name)
    
    # 5. 散点图
    visualizer.plot_scatter(y_test, y_pred, scaler, model_name)
    
    # 6. 每小时误差
    visualizer.plot_hourly_error(hourly_metrics, model_name)
    
    logger.info(f"[完成] {model_name} 所有图表已生成")


# ============================================================================
# 主训练流程
# ============================================================================

def main():
    """主训练函数"""
    
    # 打印配置
    logger.info("="*60)
    logger.info("智能电网负荷预测 - 模型训练")
    logger.info("="*60)
    logger.info(f"数据源: {DATA_SOURCE}")
    logger.info(f"训练配置: epochs={EPOCHS}, batch_size={BATCH_SIZE}, lr={LEARNING_RATE}")
    logger.info(f"是否只训练单个模型: {TRAIN_SINGLE_MODEL}")
    
    # 1. 创建输出目录
    output_dir = "/content/outputs" if os.path.exists("/content") else "outputs"
    model_dir = os.path.join(output_dir, "saved_models")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(model_dir, exist_ok=True)
    
    # 复制模型文件到 Colab（如果需要）
    if os.path.exists("/content"):
        import shutil
        if not os.path.exists("/content/models"):
            logger.info("创建 models 目录...")
            # 这里需要在 Colab 中手动上传模型文件，或者从 GitHub 克隆
            
    # 2. 加载数据
    data_dir = load_data()
    X_train, y_train, X_val, y_val, X_test, y_test, target_scaler, split_info = load_processed_data(data_dir)
    
    # 3. 导入模型类
    LSTMModel, TransformerModel, TCNModel, EnsembleModel, EnsembleModelFactory, Evaluator, Visualizer = import_models()
    
    # 4. 创建可视化器
    visualizer = Visualizer(output_dir)
    
    # 5. 训练模型
    results = {}
    
    if TRAIN_SINGLE_MODEL:
        # 只训练单个模型（用于测试）
        if SINGLE_MODEL_NAME == "lstm":
            model, history = train_model(
                LSTMModel, "LSTM", LSTM_CONFIG,
                X_train, y_train, X_val, y_val,
                model_dir, os.path.join(model_dir, "lstm_best.h5")
            )
            metrics, hourly_metrics, peak_metrics, y_pred = evaluate_model(
                model, X_test, y_test, target_scaler, "LSTM"
            )
            visualize_results(model, y_test, y_pred, target_scaler, history, "LSTM", metrics, hourly_metrics, visualizer)
            results["LSTM"] = {
                "metrics": metrics,
                "hourly_metrics": hourly_metrics,
                "peak_metrics": peak_metrics,
                "history": history.history
            }
    else:
        # 训练全部 3 个模型 + 集成
        ensemble, histories, weights = EnsembleModelFactory.train_all_ensemble(
            X_train, y_train, X_val, y_val,
            LSTM_CONFIG, TRANSFORMER_CONFIG, TCN_CONFIG,
            {"epochs": EPOCHS, "batch_size": BATCH_SIZE, "learning_rate": LEARNING_RATE},
            model_dir
        )
        
        # 评估各子模型
        for i, (name, model) in enumerate(zip(["LSTM", "Transformer", "TCN"], ensemble.models)):
            y_pred = model.predict(X_test)
            metrics, hourly_metrics, peak_metrics, _ = evaluate_model(model, X_test, y_test, target_scaler, name)
            
            # 可视化
            visualize_results(model, X_test, y_pred, target_scaler, histories[name], name, metrics, hourly_metrics, visualizer)
            
            results[name] = {
                "metrics": metrics,
                "hourly_metrics": hourly_metrics,
                "peak_metrics": peak_metrics,
                "history": histories[name].history,
                "weight": float(weights[i])
            }
        
        # 评估集成模型
        logger.info(f"\n{'='*60}")
        logger.info("评估集成模型...")
        logger.info(f"{'='*60}")
        
        y_pred_ensemble = ensemble.predict(X_test)
        metrics, hourly_metrics, peak_metrics, _ = evaluate_model(ensemble, X_test, y_test, target_scaler, "Ensemble")
        visualize_results(ensemble, X_test, y_pred_ensemble, target_scaler, None, "Ensemble", metrics, hourly_metrics, visualizer)
        
        results["Ensemble"] = {
            "metrics": metrics,
            "hourly_metrics": hourly_metrics,
            "peak_metrics": peak_metrics,
            "weights": list(weights)
        }
    
    # 6. 生成模型对比图
    logger.info("\n生成模型对比图...")
    
    # MAPE 对比
    visualizer.plot_model_comparison(
        {name: r["metrics"] for name, r in results.items()},
        metric="MAPE"
    )
    
    # RMSE 对比
    visualizer.plot_model_comparison(
        {name: r["metrics"] for name, r in results.items()},
        metric="RMSE"
    )
    
    # R² 对比
    visualizer.plot_model_comparison(
        {name: r["metrics"] for name, r in results.items()},
        metric="R2"
    )
    
    # 7. 保存评估结果
    logger.info("\n保存评估结果...")
    
    # 简化结果（只保存关键指标）
    results_simple = {
        name: {
            "MAPE": float(r["metrics"]["MAPE"]),
            "RMSE": float(r["metrics"]["RMSE"]),
            "MAE": float(r["metrics"]["MAE"]),
            "R2": float(r["metrics"]["R2"]),
            "MaxAE": float(r["metrics"]["MaxAE"]),
            "peak_MAPE": float(r["peak_metrics"]["peak_mape"]),
        }
        for name, r in results.items()
    }
    
    if "Ensemble" in results:
        results_simple["Ensemble"]["weights"] = results["Ensemble"]["weights"]
    
    visualizer.save_metrics_json(results_simple)
    
    # 8. 打印最终结果汇总
    logger.info("\n" + "="*60)
    logger.info("训练完成！最终结果汇总")
    logger.info("="*60)
    
    for name, r in results_simple.items():
        logger.info(f"\n{name}:")
        logger.info(f"  MAPE:   {r['MAPE']:.2f}%")
        logger.info(f"  RMSE:   {r['RMSE']:.2f} MW")
        logger.info(f"  MAE:    {r['MAE']:.2f} MW")
        logger.info(f"  R²:     {r['R2']:.4f}")
        if 'peak_MAPE' in r:
            logger.info(f"  峰值MAPE: {r['peak_MAPE']:.2f}%")
        if 'weights' in r:
            logger.info(f"  权重: {r['weights']}")
    
    logger.info(f"\n所有文件已保存到: {output_dir}")
    logger.info(f"\n下一步:")
    logger.info("  1. 下载 outputs/ 文件夹到本地（包含所有图表和评估结果）")
    logger.info("  2. 模型权重保存在 outputs/saved_models/ 目录")
    logger.info("  3. 开始构建后端 API 服务")


# ============================================================================
# 单元格 1: 数据加载
# ============================================================================

# 单元格 2: 训练模型（运行这个单元格即可开始训练）
# ============================================================================

# ============================================================================
# 运行训练
# ============================================================================

if __name__ == "__main__":
    # 设置随机种子（可复现结果）
    np.random.seed(42)
    tf.random.set_seed(42)
    
    main()