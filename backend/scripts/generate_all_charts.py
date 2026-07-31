# -*- coding: utf-8 -*-
"""
毕业论文完整图表生成系统
生成论文所需的全部独立图表（共20+张）
"""
import os
import sys
import torch
import numpy as np
import pandas as pd
import pickle
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.gridspec import GridSpec
import json

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 300
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['font.size'] = 12

os.chdir(os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = "visualizations"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 颜色方案
MODEL_COLORS = {
    'EnhancedLSTM': '#2E86AB',
    'SpatialTransformer': '#A23B72',
    'DeepTCN': '#F18F01',
    'BiGRU': '#C73E1D',
    'Ensemble': '#1B998B'
}

def load_data():
    """加载模型结果和原始数据"""
    print("[1/5] Loading data and model results...")
    
    # 加载序列数据
    with open("processed/step6_sequences.pkl", "rb") as f:
        seq_data = pickle.load(f)
    
    # 加载模型结果
    model_names = ['EnhancedLSTM', 'SpatialTransformer', 'DeepTCN', 'BiGRU']
    results = {}
    
    for name in model_names:
        path = os.path.join("outputs", f"{name.lower()}_best_model.pth")
        ckpt = torch.load(path, map_location='cpu', weights_only=False)
        results[name] = {
            'predictions': ckpt['test_results']['predictions'],
            'targets': ckpt['test_results']['targets'],
            'training_history': ckpt['training_history'],
            'test_results': ckpt['test_results'],
            'epochs_trained': len(ckpt['training_history']['train_loss']),
        }
    
    # 集成预测
    all_preds = [results[n]['predictions'] for n in model_names]
    ensemble_pred = np.mean(all_preds, axis=0)
    targets = results['EnhancedLSTM']['targets']
    
    eps = 1e-10
    mse = np.mean((targets - ensemble_pred) ** 2)
    rmse = np.sqrt(mse)
    mae = np.mean(np.abs(targets - ensemble_pred))
    mape = np.mean(np.abs((targets - ensemble_pred) / (np.abs(targets) + eps))) * 100
    ss_res = np.sum((targets - ensemble_pred) ** 2)
    ss_tot = np.sum((targets - np.mean(targets)) ** 2)
    r2 = 1 - (ss_res / (ss_tot + eps))
    
    results['Ensemble'] = {
        'predictions': ensemble_pred,
        'targets': targets,
        'training_history': None,
        'test_results': {'mse': float(mse), 'rmse': float(rmse), 'mae': float(mae), 'mape': float(mape), 'r2': float(r2)},
        'epochs_trained': 0,
    }
    
    return results, seq_data

def save_fig(fig, filename):
    """保存图表"""
    path = os.path.join(OUTPUT_DIR, filename)
    fig.savefig(path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f"  [OK] {filename}")

# ============================================================
# 第一部分: 数据分析图表 (Figure 1-4)
# ============================================================
def generate_data_analysis_charts(results, seq_data):
    """生成数据分析相关图表"""
    print("[2/5] Generating data analysis charts...")
    
    y_test = seq_data["y_test_seq"]
    
    # Figure 1: 负荷数据时间序列图
    fig, ax = plt.subplots(figsize=(16, 5))
    sample_size = min(500, len(y_test))
    load_data = y_test[:sample_size, 0]
    ax.plot(range(sample_size), load_data, color='#2E86AB', linewidth=1, alpha=0.8)
    ax.fill_between(range(sample_size), load_data, alpha=0.2, color='#2E86AB')
    ax.set_xlabel('Time Step', fontsize=14)
    ax.set_ylabel('Normalized Load', fontsize=14)
    ax.set_title('Electricity Load Time Series (Test Set Sample)', fontsize=16, fontweight='bold')
    ax.grid(True, alpha=0.3)
    save_fig(fig, "fig01_load_timeseries.png")
    
    # Figure 2: 负荷分布直方图
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))
    
    all_load = np.array(seq_data["y_train_seq"]).flatten()
    axes[0].hist(all_load, bins=80, color='#2E86AB', alpha=0.7, edgecolor='white')
    axes[0].set_xlabel('Normalized Load Value', fontsize=13)
    axes[0].set_ylabel('Frequency', fontsize=13)
    axes[0].set_title('Training Set Load Distribution', fontsize=14, fontweight='bold')
    axes[0].grid(True, alpha=0.3)
    
    from scipy import stats
    axes[1].hist(all_load, bins=80, density=True, color='#A23B72', alpha=0.6, edgecolor='white')
    kde = stats.gaussian_kde(all_load)
    x_range = np.linspace(all_load.min(), all_load.max(), 300)
    axes[1].plot(x_range, kde(x_range), 'r-', linewidth=2.5, label='KDE')
    axes[1].set_xlabel('Normalized Load Value', fontsize=13)
    axes[1].set_ylabel('Density', fontsize=13)
    axes[1].set_title('Load Probability Density (KDE)', fontsize=14, fontweight='bold')
    axes[1].legend(fontsize=12)
    axes[1].grid(True, alpha=0.3)
    plt.tight_layout()
    save_fig(fig, "fig02_load_distribution.png")
    
    # Figure 3: 特征相关性热力图
    X_train = np.array(seq_data["X_train_seq"])
    # 取第一个时间步的特征
    X_flat = X_train[:, 0, :]  # [N, F]
    feature_names = [f'F{i+1}' for i in range(X_flat.shape[1])]
    
    corr = np.corrcoef(X_flat.T)
    fig, ax = plt.subplots(figsize=(16, 14))
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
    sns.heatmap(corr, mask=mask, cmap='RdBu_r', center=0, annot=False,
                square=True, linewidths=0.5, ax=ax,
                cbar_kws={'label': 'Correlation Coefficient', 'shrink': 0.8})
    ax.set_title('Feature Correlation Heatmap', fontsize=16, fontweight='bold')
    ax.set_xlabel('Feature Index', fontsize=13)
    ax.set_ylabel('Feature Index', fontsize=13)
    save_fig(fig, "fig03_feature_correlation.png")
    
    # Figure 4: 预测窗口示意 / 多步预测展示
    fig, ax = plt.subplots(figsize=(16, 5))
    sample_idx = 0
    input_seq = X_train[sample_idx, :, 0]  # 取第一个特征
    output_seq = seq_data["y_train_seq"][sample_idx]
    
    input_x = range(168)
    output_x = range(168, 168 + len(output_seq))
    
    ax.plot(input_x, input_seq, 'b-', linewidth=2, label='Input Sequence (168h)')
    ax.plot(output_x, output_seq, 'r-', linewidth=2.5, label='Prediction Target (24h)')
    ax.axvline(x=167, color='gray', linestyle='--', alpha=0.5)
    ax.fill_between(input_x, input_seq, alpha=0.15, color='blue')
    ax.fill_between(output_x, output_seq, alpha=0.15, color='red')
    ax.set_xlabel('Hour', fontsize=14)
    ax.set_ylabel('Normalized Value', fontsize=14)
    ax.set_title('Sequence-to-Sequence Prediction: 168h Input -> 24h Output', fontsize=15, fontweight='bold')
    ax.legend(fontsize=12, loc='upper right')
    ax.grid(True, alpha=0.3)
    save_fig(fig, "fig04_prediction_window.png")

# ============================================================
# 第二部分: 训练过程图表 (Figure 5-9)
# ============================================================
def generate_training_charts(results):
    """生成训练过程相关图表"""
    print("[3/5] Generating training process charts...")
    
    model_names = ['EnhancedLSTM', 'SpatialTransformer', 'DeepTCN', 'BiGRU']
    
    # Figure 5: 四模型训练损失对比
    fig, ax = plt.subplots(figsize=(14, 7))
    for name in model_names:
        hist = results[name]['training_history']
        epochs = range(1, len(hist['train_loss']) + 1)
        ax.plot(epochs, hist['train_loss'], '-', color=MODEL_COLORS[name],
                linewidth=2.5, label=f'{name}')
    ax.set_xlabel('Epoch', fontsize=14)
    ax.set_ylabel('Training Loss (MSE)', fontsize=14)
    ax.set_title('Training Loss Comparison Across Models', fontsize=16, fontweight='bold')
    ax.legend(fontsize=12, loc='upper right')
    ax.grid(True, alpha=0.3)
    ax.set_yscale('log')
    save_fig(fig, "fig05_train_loss_comparison.png")
    
    # Figure 6: 四模型验证损失对比
    fig, ax = plt.subplots(figsize=(14, 7))
    for name in model_names:
        hist = results[name]['training_history']
        epochs = range(1, len(hist['val_loss']) + 1)
        ax.plot(epochs, hist['val_loss'], '-', color=MODEL_COLORS[name],
                linewidth=2.5, label=f'{name}')
    ax.set_xlabel('Epoch', fontsize=14)
    ax.set_ylabel('Validation Loss (MSE)', fontsize=14)
    ax.set_title('Validation Loss Comparison Across Models', fontsize=16, fontweight='bold')
    ax.legend(fontsize=12, loc='upper right')
    ax.grid(True, alpha=0.3)
    ax.set_yscale('log')
    save_fig(fig, "fig06_val_loss_comparison.png")
    
    # Figure 7: 训练 vs 验证损失（每个模型单独一张，2x2）
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    for idx, name in enumerate(model_names):
        ax = axes[idx // 2, idx % 2]
        hist = results[name]['training_history']
        epochs = range(1, len(hist['train_loss']) + 1)
        ax.plot(epochs, hist['train_loss'], 'b-', linewidth=2, label='Train')
        ax.plot(epochs, hist['val_loss'], 'r-', linewidth=2, label='Validation')
        ax.set_xlabel('Epoch', fontsize=12)
        ax.set_ylabel('Loss', fontsize=12)
        ax.set_title(f'{name}', fontsize=14, fontweight='bold')
        ax.legend(fontsize=11)
        ax.grid(True, alpha=0.3)
        ax.set_yscale('log')
    fig.suptitle('Train vs Validation Loss for Each Model', fontsize=16, fontweight='bold', y=1.01)
    plt.tight_layout()
    save_fig(fig, "fig07_train_val_loss_each_model.png")
    
    # Figure 8: 学习率变化曲线
    fig, ax = plt.subplots(figsize=(14, 6))
    for name in model_names:
        hist = results[name]['training_history']
        if 'learning_rates' in hist:
            lrs = hist['learning_rates']
            epochs = range(1, len(lrs) + 1)
            ax.plot(epochs, lrs, '-', color=MODEL_COLORS[name],
                    linewidth=2.5, label=f'{name}')
    ax.set_xlabel('Epoch', fontsize=14)
    ax.set_ylabel('Learning Rate', fontsize=14)
    ax.set_title('Learning Rate Schedule Comparison', fontsize=16, fontweight='bold')
    ax.legend(fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.set_yscale('log')
    save_fig(fig, "fig08_learning_rate_schedule.png")
    
    # Figure 9: R²指标随epoch变化
    fig, ax = plt.subplots(figsize=(14, 7))
    for name in model_names:
        hist = results[name]['training_history']
        if 'val_metrics' in hist:
            r2_vals = [m['r2'] for m in hist['val_metrics']]
            epochs = range(1, len(r2_vals) + 1)
            ax.plot(epochs, r2_vals, '-', color=MODEL_COLORS[name],
                    linewidth=2.5, label=f'{name}')
    ax.set_xlabel('Epoch', fontsize=14)
    ax.set_ylabel('R² Score', fontsize=14)
    ax.set_title('Validation R² Score During Training', fontsize=16, fontweight='bold')
    ax.legend(fontsize=12, loc='lower right')
    ax.grid(True, alpha=0.3)
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.3)
    save_fig(fig, "fig09_r2_during_training.png")

# ============================================================
# 第三部分: 预测性能图表 (Figure 10-14)
# ============================================================
def generate_prediction_charts(results):
    """生成预测性能相关图表"""
    print("[4/5] Generating prediction performance charts...")
    
    model_names = ['EnhancedLSTM', 'SpatialTransformer', 'DeepTCN', 'BiGRU', 'Ensemble']
    
    # Figure 10: 各模型预测vs真实值（时间序列，取前200个样本的均值）
    fig, axes = plt.subplots(3, 2, figsize=(18, 15))
    n_show = 200
    
    for idx, name in enumerate(model_names):
        ax = axes[idx // 2, idx % 2]
        preds = results[name]['predictions'][:n_show]
        targets = results[name]['targets'][:n_show]
        
        pred_mean = np.mean(preds, axis=1)
        target_mean = np.mean(targets, axis=1)
        
        ax.plot(range(n_show), target_mean, 'k-', linewidth=2, alpha=0.7, label='Actual')
        ax.plot(range(n_show), pred_mean, '-', color=MODEL_COLORS[name], linewidth=2, label='Predicted')
        ax.fill_between(range(n_show), target_mean, pred_mean, alpha=0.15, color=MODEL_COLORS[name])
        
        r2 = results[name]['test_results']['r2']
        rmse = results[name]['test_results']['rmse']
        ax.set_title(f'{name} (R²={r2:.4f}, RMSE={rmse:.4f})', fontsize=13, fontweight='bold')
        ax.set_xlabel('Sample Index', fontsize=11)
        ax.set_ylabel('Normalized Load', fontsize=11)
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)
    
    axes[2, 1].axis('off')
    fig.suptitle('Predicted vs Actual Load for All Models', fontsize=16, fontweight='bold', y=1.01)
    plt.tight_layout()
    save_fig(fig, "fig10_prediction_vs_actual_timeseries.png")
    
    # Figure 11: 预测散点图（每个模型）
    fig, axes = plt.subplots(2, 3, figsize=(18, 11))
    for idx, name in enumerate(model_names):
        ax = axes[idx // 3, idx % 3]
        preds = results[name]['predictions'].flatten()
        targets = results[name]['targets'].flatten()
        
        ax.scatter(targets, preds, alpha=0.3, s=8, color=MODEL_COLORS[name], edgecolors='none')
        
        min_val = min(targets.min(), preds.min())
        max_val = max(targets.max(), preds.max())
        ax.plot([min_val, max_val], [min_val, max_val], 'r--', linewidth=2, label='Perfect Fit')
        
        r2 = results[name]['test_results']['r2']
        ax.set_title(f'{name} (R²={r2:.4f})', fontsize=13, fontweight='bold')
        ax.set_xlabel('Actual', fontsize=11)
        ax.set_ylabel('Predicted', fontsize=11)
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.set_aspect('equal')
    
    axes[1, 2].axis('off')
    fig.suptitle('Scatter Plot: Predicted vs Actual', fontsize=16, fontweight='bold', y=1.01)
    plt.tight_layout()
    save_fig(fig, "fig11_scatter_plot.png")
    
    # Figure 12: 误差分布对比
    fig, ax = plt.subplots(figsize=(14, 7))
    for name in model_names:
        preds = results[name]['predictions']
        targets = results[name]['targets']
        errors = (preds - targets).flatten()
        sns.kdeplot(errors, ax=ax, label=name, color=MODEL_COLORS[name], linewidth=2.5, fill=True, alpha=0.15)
    
    ax.axvline(x=0, color='red', linestyle='--', linewidth=2, alpha=0.8)
    ax.set_xlabel('Prediction Error', fontsize=14)
    ax.set_ylabel('Density', fontsize=14)
    ax.set_title('Prediction Error Distribution Comparison', fontsize=16, fontweight='bold')
    ax.legend(fontsize=12)
    ax.grid(True, alpha=0.3)
    save_fig(fig, "fig12_error_distribution.png")
    
    # Figure 13: 误差箱线图
    fig, ax = plt.subplots(figsize=(14, 7))
    error_data = []
    labels = []
    for name in model_names:
        preds = results[name]['predictions']
        targets = results[name]['targets']
        errors = (preds - targets).flatten()
        # 采样以加速
        if len(errors) > 5000:
            errors = np.random.choice(errors, 5000, replace=False)
        error_data.append(errors)
        labels.append(name)
    
    bp = ax.boxplot(error_data, tick_labels=labels, patch_artist=True, widths=0.5,
                    showfliers=True, flierprops=dict(marker='o', markersize=2, alpha=0.3))
    for patch, name in zip(bp['boxes'], labels):
        patch.set_facecolor(MODEL_COLORS[name])
        patch.set_alpha(0.6)
    
    ax.axhline(y=0, color='red', linestyle='--', linewidth=2, alpha=0.8)
    ax.set_ylabel('Prediction Error', fontsize=14)
    ax.set_title('Prediction Error Box Plot', fontsize=16, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    save_fig(fig, "fig13_error_boxplot.png")
    
    # Figure 14: 各模型残差自相关图 (取最佳模型)
    best_model = max(['EnhancedLSTM', 'SpatialTransformer', 'DeepTCN', 'BiGRU'],
                     key=lambda x: results[x]['test_results']['r2'])
    
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    
    # 残差分布
    preds = results[best_model]['predictions'].flatten()
    targets = results[best_model]['targets'].flatten()
    residuals = preds - targets
    
    axes[0].hist(residuals, bins=100, color=MODEL_COLORS[best_model], alpha=0.7, edgecolor='white', density=True)
    from scipy import stats
    mu, sigma = stats.norm.fit(residuals)
    x_range = np.linspace(residuals.min(), residuals.max(), 300)
    axes[0].plot(x_range, stats.norm.pdf(x_range, mu, sigma), 'r-', linewidth=2.5, label=f'Normal Fit\nmu={mu:.4f}, sigma={sigma:.4f}')
    axes[0].set_xlabel('Residual', fontsize=13)
    axes[0].set_ylabel('Density', fontsize=13)
    axes[0].set_title(f'Residual Distribution ({best_model})', fontsize=14, fontweight='bold')
    axes[0].legend(fontsize=11)
    axes[0].grid(True, alpha=0.3)
    
    # QQ图
    from scipy import stats as scistats
    scistats.probplot(residuals, dist="norm", plot=axes[1])
    axes[1].set_title(f'Q-Q Plot ({best_model})', fontsize=14, fontweight='bold')
    axes[1].grid(True, alpha=0.3)
    axes[1].get_lines()[0].set_color(MODEL_COLORS[best_model])
    axes[1].get_lines()[0].set_markersize(2)
    axes[1].get_lines()[1].set_color('red')
    axes[1].get_lines()[1].set_linewidth(2)
    
    plt.tight_layout()
    save_fig(fig, "fig14_residual_analysis.png")

# ============================================================
# 第四部分: 模型对比图表 (Figure 15-18)
# ============================================================
def generate_comparison_charts(results):
    """生成模型对比图表"""
    print("[5/5] Generating model comparison charts...")
    
    model_names = ['EnhancedLSTM', 'SpatialTransformer', 'DeepTCN', 'BiGRU', 'Ensemble']
    
    # 提取指标
    metrics = {}
    for name in model_names:
        tr = results[name]['test_results']
        metrics[name] = {
            'RMSE': tr['rmse'],
            'MAE': tr['mae'],
            'MAPE': tr['mape'],
            'R2': tr['r2'],
            'MSE': tr['mse']
        }
    
    # Figure 15: 性能指标柱状图对比 (4个子图)
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    metric_names = ['RMSE', 'MAE', 'MAPE', 'R2']
    titles = ['RMSE (Lower is Better)', 'MAE (Lower is Better)', 
              'MAPE % (Lower is Better)', 'R² (Higher is Better)']
    
    for idx, (metric, title) in enumerate(zip(metric_names, titles)):
        ax = axes[idx // 2, idx % 2]
        values = [metrics[name][metric] for name in model_names]
        colors = [MODEL_COLORS[name] for name in model_names]
        bars = ax.bar(model_names, values, color=colors, alpha=0.8, edgecolor='white', linewidth=1.5)
        
        for bar, val in zip(bars, values):
            y_pos = bar.get_height()
            if metric == 'R2':
                ax.text(bar.get_x() + bar.get_width()/2, y_pos + 0.01,
                        f'{val:.4f}', ha='center', fontsize=11, fontweight='bold')
            else:
                ax.text(bar.get_x() + bar.get_width()/2, y_pos + max(values)*0.01,
                        f'{val:.4f}', ha='center', fontsize=11, fontweight='bold')
        
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_ylabel(metric, fontsize=13)
        ax.grid(True, alpha=0.3, axis='y')
        ax.tick_params(axis='x', rotation=30)
    
    fig.suptitle('Model Performance Comparison', fontsize=16, fontweight='bold', y=1.01)
    plt.tight_layout()
    save_fig(fig, "fig15_metrics_bar_comparison.png")
    
    # Figure 16: 雷达图
    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(projection='polar'))
    
    # 标准化指标 (0-1, 越大越好)
    categories = ['RMSE', 'MAE', 'MAPE', 'R2']
    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]
    
    # 标准化（越小越好的指标取反）
    max_vals = {m: max(metrics[n][m] for n in model_names) for m in categories}
    min_vals = {m: min(metrics[n][m] for n in model_names) for m in categories}
    
    for name in model_names:
        values = []
        for m in categories:
            if m == 'R2':
                # 越大越好
                v = (metrics[name][m] - min_vals[m]) / (max_vals[m] - min_vals[m] + 1e-10)
            else:
                # 越小越好，取反
                v = 1 - (metrics[name][m] - min_vals[m]) / (max_vals[m] - min_vals[m] + 1e-10)
            values.append(v)
        values += values[:1]
        
        ax.plot(angles, values, '-', linewidth=2.5, label=name, color=MODEL_COLORS[name])
        ax.fill(angles, values, alpha=0.1, color=MODEL_COLORS[name])
    
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=14)
    ax.set_title('Model Performance Radar Chart\n(Normalized, Outer = Better)', 
                 fontsize=15, fontweight='bold', pad=25)
    ax.legend(loc='upper right', bbox_to_anchor=(1.35, 1.1), fontsize=12)
    save_fig(fig, "fig16_radar_chart.png")
    
    # Figure 17: 预测相关性矩阵
    fig, ax = plt.subplots(figsize=(10, 8))
    pred_matrix = []
    for name in model_names:
        pred_matrix.append(results[name]['predictions'].flatten())
    
    pred_corr = np.corrcoef(pred_matrix)
    labels_short = ['LSTM', 'Transformer', 'TCN', 'GRU', 'Ensemble']
    
    mask = np.triu(np.ones_like(pred_corr, dtype=bool), k=1)
    sns.heatmap(pred_corr, annot=True, fmt='.3f', cmap='YlOrRd',
                xticklabels=labels_short, yticklabels=labels_short,
                square=True, linewidths=1, ax=ax,
                cbar_kws={'label': 'Correlation', 'shrink': 0.8})
    ax.set_title('Inter-Model Prediction Correlation Matrix', fontsize=15, fontweight='bold')
    save_fig(fig, "fig17_prediction_correlation.png")
    
    # Figure 18: 24小时预测误差对比 (每小时一个箱线图)
    fig, axes = plt.subplots(1, 2, figsize=(18, 7))
    
    # 取最佳单模型和集成模型
    for ax_idx, (model_name, ax) in enumerate(zip(
        [best_name := max(['EnhancedLSTM', 'SpatialTransformer', 'DeepTCN', 'BiGRU'],
                          key=lambda x: results[x]['test_results']['r2']),
         'Ensemble'], axes)):
        
        preds = results[model_name]['predictions']
        targets = results[model_name]['targets']
        hourly_errors = np.abs(preds - targets)  # [N, 24]
        
        parts = ax.boxplot([hourly_errors[:, h] for h in range(24)],
                          patch_artist=True, widths=0.6,
                          tick_labels=[str(h+1) for h in range(24)],
                          flierprops=dict(marker='o', markersize=1.5, alpha=0.3))
        
        for patch in parts['boxes']:
            patch.set_facecolor(MODEL_COLORS[model_name])
            patch.set_alpha(0.6)
        
        ax.set_xlabel('Forecast Hour (1-24)', fontsize=13)
        ax.set_ylabel('Absolute Error', fontsize=13)
        ax.set_title(f'{model_name}: Hourly Forecast Error', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')
        ax.set_xticks(range(1, 25))
    
    plt.tight_layout()
    save_fig(fig, "fig18_hourly_error.png")

# ============================================================
# 第五部分: 综合汇总表 (Figure 19-20)
# ============================================================
def generate_summary_charts(results):
    """生成汇总图表"""
    print("[5/5] Generating summary charts...")
    
    model_names = ['EnhancedLSTM', 'SpatialTransformer', 'DeepTCN', 'BiGRU', 'Ensemble']
    
    # Figure 19: 综合性能表格图
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.axis('off')
    
    # 表格数据
    col_labels = ['Model', 'RMSE', 'MAE', 'MAPE(%)', 'R²', 'Epochs', 'Rank']
    table_data = []
    
    # 按R2排序
    sorted_models = sorted(model_names, key=lambda x: results[x]['test_results']['r2'], reverse=True)
    
    for rank, name in enumerate(sorted_models, 1):
        tr = results[name]['test_results']
        epochs = results[name].get('epochs_trained', 0)
        table_data.append([
            name,
            f"{tr['rmse']:.6f}",
            f"{tr['mae']:.6f}",
            f"{tr['mape']:.3f}",
            f"{tr['r2']:.4f}",
            str(epochs) if epochs > 0 else '-',
            f'#{rank}'
        ])
    
    table = ax.table(cellText=table_data, colLabels=col_labels,
                     cellLoc='center', loc='center',
                     colColours=['#4472C4'] * len(col_labels))
    
    table.auto_set_font_size(False)
    table.set_fontsize(13)
    table.scale(1.2, 2.0)
    
    # 设置表头颜色
    for j in range(len(col_labels)):
        table[0, j].set_text_props(color='white', fontweight='bold')
    
    # 第一名高亮
    for j in range(len(col_labels)):
        table[1, j].set_facecolor('#E2EFDA')
        table[1, j].set_text_props(fontweight='bold')
    
    ax.set_title('Model Performance Summary Table', fontsize=16, fontweight='bold', pad=20)
    save_fig(fig, "fig19_performance_table.png")
    
    # Figure 20: 模型参数量与性能关系
    param_counts = {
        'EnhancedLSTM': 458144,
        'SpatialTransformer': 908024,
        'DeepTCN': 157400,
        'BiGRU': 1408088,
        'Ensemble': 2931656
    }
    
    fig, ax = plt.subplots(figsize=(12, 8))
    
    for name in model_names[:4]:  # 不含Ensemble
        rmse = results[name]['test_results']['rmse']
        r2 = results[name]['test_results']['r2']
        params = param_counts[name]
        
        ax.scatter(params / 1e6, rmse, s=300, color=MODEL_COLORS[name],
                  alpha=0.7, edgecolors='white', linewidth=2, zorder=5)
        ax.annotate(f'{name}\n(R²={r2:.4f})', (params / 1e6, rmse),
                   textcoords="offset points", xytext=(15, 10),
                   fontsize=11, fontweight='bold',
                   arrowprops=dict(arrowstyle='->', color='gray'))
    
    ax.set_xlabel('Model Parameters (Millions)', fontsize=14)
    ax.set_ylabel('RMSE (Lower is Better)', fontsize=14)
    ax.set_title('Model Complexity vs Performance', fontsize=16, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.set_xscale('log')
    save_fig(fig, "fig20_complexity_vs_performance.png")
    
    # 保存结果JSON
    summary = {}
    for name in model_names:
        tr = results[name]['test_results']
        summary[name] = {
            'RMSE': tr['rmse'],
            'MAE': tr['mae'],
            'MAPE': tr['mape'],
            'R2': tr['r2'],
            'Parameters': param_counts.get(name, 0),
        }
    
    with open(os.path.join(OUTPUT_DIR, 'all_results.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print("\n" + "=" * 60)
    print("ALL CHARTS GENERATED SUCCESSFULLY!")
    print("=" * 60)
    print(f"Total: 20 charts saved to: {OUTPUT_DIR}/")
    print("\nChart list:")
    chart_list = [
        "fig01_load_timeseries.png          - Load time series",
        "fig02_load_distribution.png        - Load distribution & KDE",
        "fig03_feature_correlation.png      - Feature correlation heatmap",
        "fig04_prediction_window.png        - Prediction window illustration",
        "fig05_train_loss_comparison.png    - Training loss comparison",
        "fig06_val_loss_comparison.png      - Validation loss comparison",
        "fig07_train_val_loss_each_model.png- Train/val loss per model",
        "fig08_learning_rate_schedule.png   - Learning rate schedule",
        "fig09_r2_during_training.png       - R² during training",
        "fig10_prediction_vs_actual.png     - Prediction vs actual (timeseries)",
        "fig11_scatter_plot.png             - Prediction scatter plots",
        "fig12_error_distribution.png       - Error distribution KDE",
        "fig13_error_boxplot.png            - Error box plot",
        "fig14_residual_analysis.png        - Residual analysis & QQ plot",
        "fig15_metrics_bar_comparison.png   - Metrics bar comparison",
        "fig16_radar_chart.png              - Performance radar chart",
        "fig17_prediction_correlation.png   - Inter-model correlation",
        "fig18_hourly_error.png             - Hourly forecast error",
        "fig19_performance_table.png        - Performance summary table",
        "fig20_complexity_vs_performance.png- Complexity vs performance",
    ]
    for c in chart_list:
        print(f"  {c}")

def main():
    print("=" * 60)
    print("Thesis Chart Generation System")
    print("=" * 60)
    
    results, seq_data = load_data()
    generate_data_analysis_charts(results, seq_data)
    generate_training_charts(results)
    generate_prediction_charts(results)
    generate_comparison_charts(results)
    generate_summary_charts(results)

if __name__ == "__main__":
    main()
