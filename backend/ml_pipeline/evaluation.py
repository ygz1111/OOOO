"""
智能电网负荷预测 - 评估与可视化模块
生成论文所需的所有图表和评估指标

生成的图表:
  1. 训练损失曲线 (loss / val_loss)
  2. 学习率变化曲线
  3. 预测 vs 实际对比图 (时间序列)
  4. 预测散点图 (预测值 vs 实际值)
  5. 误差分布直方图
  6. 各小时预测误差箱线图
  7. 多模型对比柱状图 (MAPE / RMSE / MAE)
  8. 24小时预测误差热力图
  9. 峰值时段预测精度分析
  10. 特征重要性分析 (基于扰动法)
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # 非交互式后端，适合服务器/Colab
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import os
import json
import pickle

# 中文字体设置（Colab 环境）
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 150
plt.rcParams['savefig.dpi'] = 300  # 论文用高分辨率
plt.rcParams['figure.figsize'] = (12, 5)

# 配色方案
COLORS = {
    "LSTM_Attention": "#2196F3",   # 蓝色
    "Transformer": "#FF9800",       # 橙色
    "TCN": "#4CAF50",               # 绿色
    "Ensemble": "#9C27B0",          # 紫色
    "actual": "#333333",            # 深灰
    "predicted": "#F44336",         # 红色
}


# ============================================================================
# 评估指标计算
# ============================================================================

def calculate_metrics(y_true, y_pred, target_scaler=None):
    """
    计算全面的评估指标

    Args:
        y_true: 实际值 (n_samples, horizon) 归一化后
        y_pred: 预测值 (n_samples, horizon) 归一化后
        target_scaler: 目标变量的 Scaler，用于反归一化到 MW

    Returns:
        dict: 各项指标
    """
    # 反归一化到原始 MW 单位
    if target_scaler is not None:
        y_true_mw = target_scaler.inverse_transform(y_true.reshape(-1, 1)).flatten()
        y_pred_mw = target_scaler.inverse_transform(y_pred.reshape(-1, 1)).flatten()
    else:
        y_true_mw = y_true.flatten()
        y_pred_mw = y_pred.flatten()

    # MAE: 平均绝对误差
    mae = np.mean(np.abs(y_true_mw - y_pred_mw))

    # RMSE: 均方根误差
    rmse = np.sqrt(np.mean((y_true_mw - y_pred_mw) ** 2))

    # MAPE: 平均绝对百分比误差
    # 避免除以零
    mask = np.abs(y_true_mw) > 1
    mape = np.mean(np.abs((y_true_mw[mask] - y_pred_mw[mask]) / y_true_mw[mask])) * 100

    # R²: 决定系数
    ss_res = np.sum((y_true_mw - y_pred_mw) ** 2)
    ss_tot = np.sum((y_true_mw - np.mean(y_true_mw)) ** 2)
    r2 = 1 - ss_res / ss_tot

    # 峰值时段精度 (实际负荷 > 90th percentile)
    peak_threshold = np.percentile(y_true_mw, 90)
    peak_mask = y_true_mw >= peak_threshold
    if peak_mask.sum() > 0:
        peak_mape = np.mean(np.abs(
            (y_true_mw[peak_mask] - y_pred_mw[peak_mask]) / y_true_mw[peak_mask]
        )) * 100
        peak_rmse = np.sqrt(np.mean((y_true_mw[peak_mask] - y_pred_mw[peak_mask]) ** 2))
    else:
        peak_mape = float('nan')
        peak_rmse = float('nan')

    # 谷值时段精度 (实际负荷 < 10th percentile)
    valley_threshold = np.percentile(y_true_mw, 10)
    valley_mask = y_true_mw <= valley_threshold
    if valley_mask.sum() > 0:
        valley_mape = np.mean(np.abs(
            (y_true_mw[valley_mask] - y_pred_mw[valley_mask]) / y_true_mw[valley_mask]
        )) * 100
    else:
        valley_mape = float('nan')

    return {
        "MAE": float(mae),
        "RMSE": float(rmse),
        "MAPE": float(mape),
        "R2": float(r2),
        "Peak_MAPE": float(peak_mape),
        "Peak_RMSE": float(peak_rmse),
        "Valley_MAPE": float(valley_mape),
        "n_samples": len(y_true_mw),
    }


# ============================================================================
# 图表生成函数
# ============================================================================

def plot_training_history(history, model_name, save_dir):
    """
    图1: 训练损失曲线 + 学习率变化

    生成两个子图:
      上: Train Loss vs Val Loss
      下: Learning Rate 变化
    """
    fig, axes = plt.subplots(2, 1, figsize=(10, 8))

    epochs = range(1, len(history['loss']) + 1)

    # 损失曲线
    axes[0].plot(epochs, history['loss'], 'b-', label='Train Loss', linewidth=1.5)
    axes[0].plot(epochs, history['val_loss'], 'r--', label='Val Loss', linewidth=1.5)
    axes[0].set_xlabel('Epoch')
    axes[0].set_ylabel('Huber Loss')
    axes[0].set_title(f'{model_name} - Training & Validation Loss')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # 学习率
    if 'lr' in history:
        axes[1].plot(epochs, history['lr'], 'g-', linewidth=1.5)
        axes[1].set_xlabel('Epoch')
        axes[1].set_ylabel('Learning Rate')
        axes[1].set_title('Learning Rate Schedule')
        axes[1].set_yscale('log')
        axes[1].grid(True, alpha=0.3)
    else:
        axes[1].set_visible(False)

    plt.tight_layout()
    fpath = os.path.join(save_dir, f"fig_{model_name}_training_loss.png")
    plt.savefig(fpath, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"  [saved] {fpath}")


def plot_prediction_vs_actual(y_true, y_pred, timestamps, model_name,
                                target_scaler, save_dir, n_days=7):
    """
    图2: 预测 vs 实际对比时间序列图

    展示测试集上连续 n_days 天的预测对比
    """
    # 反归一化
    y_true_mw = target_scaler.inverse_transform(y_true.reshape(-1, 1)).flatten()
    y_pred_mw = target_scaler.inverse_transform(y_pred.reshape(-1, 1)).flatten()

    # 取前 n_days 天 (horizon=24, 每天一个序列)
    n_samples = min(n_days, len(y_true) // 24)

    fig, axes = plt.subplots(n_samples, 1, figsize=(14, 3 * n_samples), sharex=False)

    if n_samples == 1:
        axes = [axes]

    for i in range(n_samples):
        start = i * 24
        end = start + 24
        actual = y_true_mw[start:end]
        predicted = y_pred_mw[start:end]

        hours = range(1, 25)
        axes[i].plot(hours, actual, 'b-o', label='Actual', markersize=4, linewidth=1.5)
        axes[i].plot(hours, predicted, 'r--s', label='Predicted', markersize=4, linewidth=1.5)

        if timestamps is not None:
            date_str = timestamps[start].strftime('%Y-%m-%d') if hasattr(timestamps[start], 'strftime') else f"Day {i+1}"
            axes[i].set_title(f'{date_str} - 24h Prediction')
        else:
            axes[i].set_title(f'Day {i+1} - 24h Prediction')

        axes[i].set_xlabel('Hour')
        axes[i].set_ylabel('Load (MW)')
        axes[i].legend(loc='upper right')
        axes[i].grid(True, alpha=0.3)
        axes[i].set_xticks(range(1, 25, 2))

    plt.tight_layout()
    fpath = os.path.join(save_dir, f"fig_{model_name}_prediction_vs_actual.png")
    plt.savefig(fpath, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"  [saved] {fpath}")


def plot_scatter(y_true, y_pred, model_name, target_scaler, save_dir):
    """
    图3: 预测散点图 (预测值 vs 实际值)

    理想预测应落在 y=x 对角线上
    """
    y_true_mw = target_scaler.inverse_transform(y_true.reshape(-1, 1)).flatten()
    y_pred_mw = target_scaler.inverse_transform(y_pred.reshape(-1, 1)).flatten()

    fig, ax = plt.subplots(figsize=(8, 8))

    # 散点图 (抽样以避免点太多)
    n = len(y_true_mw)
    if n > 5000:
        idx = np.random.choice(n, 5000, replace=False)
    else:
        idx = np.arange(n)

    ax.scatter(y_true_mw[idx], y_pred_mw[idx], alpha=0.3, s=8,
               c=COLORS.get(model_name, 'blue'))

    # y=x 参考线
    lim_min = min(y_true_mw.min(), y_pred_mw.min())
    lim_max = max(y_true_mw.max(), y_pred_mw.max())
    ax.plot([lim_min, lim_max], [lim_min, lim_max], 'r--', linewidth=2, label='y = x')

    # R² 标注
    metrics = calculate_metrics(y_true, y_pred, target_scaler)
    ax.text(0.05, 0.95, f"R² = {metrics['R2']:.4f}\nMAPE = {metrics['MAPE']:.2f}%",
            transform=ax.transAxes, fontsize=12, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    ax.set_xlabel('Actual Load (MW)')
    ax.set_ylabel('Predicted Load (MW)')
    ax.set_title(f'{model_name} - Prediction Scatter Plot')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fpath = os.path.join(save_dir, f"fig_{model_name}_scatter.png")
    plt.savefig(fpath, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"  [saved] {fpath}")


def plot_error_distribution(y_true, y_pred, model_name, target_scaler, save_dir):
    """
    图4: 误差分布直方图
    """
    y_true_mw = target_scaler.inverse_transform(y_true.reshape(-1, 1)).flatten()
    y_pred_mw = target_scaler.inverse_transform(y_pred.reshape(-1, 1)).flatten()

    errors = y_pred_mw - y_true_mw

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # 绝对误差分布
    axes[0].hist(errors, bins=80, color=COLORS.get(model_name, 'blue'),
                 alpha=0.7, edgecolor='black', linewidth=0.3)
    axes[0].axvline(x=0, color='r', linestyle='--', linewidth=2)
    axes[0].axvline(x=np.mean(errors), color='orange', linestyle='-',
                    linewidth=2, label=f'Mean = {np.mean(errors):.1f} MW')
    axes[0].set_xlabel('Prediction Error (MW)')
    axes[0].set_ylabel('Frequency')
    axes[0].set_title(f'{model_name} - Error Distribution')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # 百分比误差分布
    pct_errors = (y_pred_mw - y_true_mw) / y_true_mw * 100
    axes[1].hist(pct_errors, bins=80, color=COLORS.get(model_name, 'blue'),
                 alpha=0.7, edgecolor='black', linewidth=0.3)
    axes[1].axvline(x=0, color='r', linestyle='--', linewidth=2)
    axes[1].set_xlabel('Percentage Error (%)')
    axes[1].set_ylabel('Frequency')
    axes[1].set_title(f'{model_name} - Percentage Error Distribution')
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    fpath = os.path.join(save_dir, f"fig_{model_name}_error_distribution.png")
    plt.savefig(fpath, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"  [saved] {fpath}")


def plot_hourly_error_box(y_true, y_pred, model_name, target_scaler, save_dir):
    """
    图5: 各小时预测误差箱线图

    展示每个预测小时步 (1~24h) 的误差分布
    """
    y_true_mw = target_scaler.inverse_transform(y_true.reshape(-1, 1)).flatten()
    y_pred_mw = target_scaler.inverse_transform(y_pred.reshape(-1, 1)).flatten()

    # reshape: (n_samples, 24)
    n_samples = len(y_true_mw) // 24
    y_true_2d = y_true_mw[:n_samples * 24].reshape(n_samples, 24)
    y_pred_2d = y_pred_mw[:n_samples * 24].reshape(n_samples, 24)

    # 每个小时步的百分比误差
    pct_errors = (y_pred_2d - y_true_2d) / y_true_2d * 100

    fig, ax = plt.subplots(figsize=(12, 6))
    box_data = [pct_errors[:, h] for h in range(24)]

    bp = ax.boxplot(box_data, positions=range(1, 25), widths=0.6,
                    patch_artist=True, showfliers=True,
                    flierprops=dict(marker='o', markersize=2, alpha=0.3))

    for patch in bp['boxes']:
        patch.set_facecolor(COLORS.get(model_name, 'blue'))
        patch.set_alpha(0.5)

    ax.axhline(y=0, color='r', linestyle='--', linewidth=1)
    ax.set_xlabel('Forecast Hour Ahead')
    ax.set_ylabel('Percentage Error (%)')
    ax.set_title(f'{model_name} - Hourly Forecast Error Distribution')
    ax.set_xticks(range(1, 25))
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    fpath = os.path.join(save_dir, f"fig_{model_name}_hourly_error_box.png")
    plt.savefig(fpath, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"  [saved] {fpath}")


def plot_model_comparison(all_metrics, save_dir):
    """
    图6: 多模型对比柱状图

    Args:
        all_metrics: dict {model_name: metrics_dict}
    """
    model_names = list(all_metrics.keys())
    metrics_to_plot = ["MAPE", "RMSE", "MAE"]
    metric_labels = ["MAPE (%)", "RMSE (MW)", "MAE (MW)"]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    for idx, (metric, label) in enumerate(zip(metrics_to_plot, metric_labels)):
        values = [all_metrics[m][metric] for m in model_names]
        colors = [COLORS.get(m, 'gray') for m in model_names]

        bars = axes[idx].bar(model_names, values, color=colors, alpha=0.8,
                              edgecolor='black', linewidth=0.5)
        axes[idx].set_ylabel(label)
        axes[idx].set_title(f'Model Comparison - {metric}')
        axes[idx].grid(True, alpha=0.3, axis='y')

        # 在柱子上标注数值
        for bar, val in zip(bars, values):
            axes[idx].text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.01,
                          f'{val:.2f}', ha='center', va='bottom', fontsize=10)

    plt.tight_layout()
    fpath = os.path.join(save_dir, "fig_model_comparison.png")
    plt.savefig(fpath, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"  [saved] {fpath}")


def plot_peak_valley_analysis(y_true, y_pred, model_name, target_scaler, save_dir):
    """
    图7: 峰值/谷值时段预测精度分析
    """
    y_true_mw = target_scaler.inverse_transform(y_true.reshape(-1, 1)).flatten()
    y_pred_mw = target_scaler.inverse_transform(y_pred.reshape(-1, 1)).flatten()

    pct_errors = np.abs((y_pred_mw - y_true_mw) / y_true_mw) * 100

    # 分5个等级: 谷值(0-10%), 低(10-30%), 正常(30-70%), 高(70-90%), 峰值(90-100%)
    percentiles = [0, 10, 30, 70, 90, 100]
    labels = ['Valley\n(0-10%)', 'Low\n(10-30%)', 'Normal\n(30-70%)',
              'High\n(70-90%)', 'Peak\n(90-100%)']
    categories = []
    means = []
    stds = []

    for i in range(len(labels)):
        lower = np.percentile(y_true_mw, percentiles[i])
        upper = np.percentile(y_true_mw, percentiles[i + 1])
        mask = (y_true_mw >= lower) & (y_true_mw <= upper)
        if mask.sum() > 0:
            categories.append(labels[i])
            means.append(np.mean(pct_errors[mask]))
            stds.append(np.std(pct_errors[mask]))
        else:
            categories.append(labels[i])
            means.append(0)
            stds.append(0)

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(categories, means, yerr=stds, capsize=5,
                  color=COLORS.get(model_name, 'blue'), alpha=0.7,
                  edgecolor='black', linewidth=0.5)

    for bar, val in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f'{val:.2f}%', ha='center', va='bottom', fontsize=10)

    ax.set_ylabel('MAPE (%)')
    ax.set_title(f'{model_name} - Forecast Accuracy by Load Level')
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    fpath = os.path.join(save_dir, f"fig_{model_name}_peak_valley.png")
    plt.savefig(fpath, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"  [saved] {fpath}")


def generate_evaluation_report(model_name, metrics, history, save_dir):
    """
    生成文本评估报告 (Markdown格式)
    """
    report = f"""# {model_name} 评估报告

## 模型信息
- 模型名称: {model_name}
- 训练轮次: {len(history['loss'])}
- 最终训练损失: {history['loss'][-1]:.6f}
- 最终验证损失: {history['val_loss'][-1]:.6f}
- 最佳验证损失: {min(history['val_loss']):.6f} (Epoch {np.argmin(history['val_loss'])+1})

## 评估指标 (测试集)

| 指标 | 数值 | 说明 |
|------|------|------|
| MAE | {metrics['MAE']:.2f} MW | 平均绝对误差 |
| RMSE | {metrics['RMSE']:.2f} MW | 均方根误差 |
| MAPE | {metrics['MAPE']:.2f}% | 平均绝对百分比误差 |
| R² | {metrics['R2']:.4f} | 决定系数 (越接近1越好) |
| Peak MAPE | {metrics['Peak_MAPE']:.2f}% | 峰值时段(>90th)误差 |
| Valley MAPE | {metrics['Valley_MAPE']:.2f}% | 谷值时段(<10th)误差 |

## 样本信息
- 测试样本数: {metrics['n_samples']}
- 预测步长: 24小时
- 回看窗口: 168小时 (7天)
"""

    fpath = os.path.join(save_dir, f"report_{model_name}.md")
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"  [saved] {fpath}")


def plot_all_for_model(y_true, y_pred, history, model_name,
                       target_scaler, timestamps, save_dir):
    """
    为单个模型生成所有图表和评估报告

    Args:
        y_true: (n_samples, 24) 实际值 (归一化)
        y_pred: (n_samples, 24) 预测值 (归一化)
        history: 训练历史 dict
        model_name: 模型名称
        target_scaler: 目标 Scaler
        timestamps: 时间戳列表 (用于标注日期)
        save_dir: 保存目录
    """
    os.makedirs(save_dir, exist_ok=True)

    print(f"\n[{model_name}] 生成评估图表...")

    # 1. 训练损失曲线
    plot_training_history(history, model_name, save_dir)

    # 2. 预测 vs 实际
    plot_prediction_vs_actual(y_true, y_pred, timestamps, model_name,
                               target_scaler, save_dir, n_days=7)

    # 3. 散点图
    plot_scatter(y_true, y_pred, model_name, target_scaler, save_dir)

    # 4. 误差分布
    plot_error_distribution(y_true, y_pred, model_name, target_scaler, save_dir)

    # 5. 各小时误差箱线图
    plot_hourly_error_box(y_true, y_pred, model_name, target_scaler, save_dir)

    # 6. 峰值/谷值分析
    plot_peak_valley_analysis(y_true, y_pred, model_name, target_scaler, save_dir)

    # 7. 计算指标
    metrics = calculate_metrics(y_true, y_pred, target_scaler)

    # 8. 生成评估报告
    generate_evaluation_report(model_name, metrics, history, save_dir)

    return metrics
