# -*- coding: utf-8 -*-
"""
补充图表生成：
1. 数据预处理前后对比图
2. 模型训练时间和参数量对比图
"""
import os
import sys
import pickle
import numpy as np
import pandas as pd
import torch
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['font.size'] = 12

os.chdir(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = "visualizations"
os.makedirs(OUTPUT_DIR, exist_ok=True)

MODEL_COLORS = {
    'EnhancedLSTM': '#2E86AB',
    'SpatialTransformer': '#A23B72',
    'DeepTCN': '#F18F01',
    'BiGRU': '#C73E1D',
}

def save_fig(fig, filename):
    path = os.path.join(OUTPUT_DIR, filename)
    fig.savefig(path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f"  [OK] {filename}")

# ============================================================
# 图1: 数据预处理前后对比图
# ============================================================
def generate_preprocessing_comparison():
    """生成数据预处理前后对比图"""
    print("[1/2] Generating preprocessing comparison chart...")

    # 加载各步骤数据
    with open("processed/step1_system_data.pkl", "rb") as f:
        step1 = pickle.load(f)
    with open("processed/step2_cleaned_data.pkl", "rb") as f:
        step2 = pickle.load(f)
    with open("processed/step4_engineered_data.pkl", "rb") as f:
        step4 = pickle.load(f)
    with open("processed/step5_normalized_data.pkl", "rb") as f:
        step5 = pickle.load(f)
    with open("processed/step2_anomaly_report.pkl", "rb") as f:
        anomaly = pickle.load(f)

    fig, axes = plt.subplots(2, 3, figsize=(20, 12))

    # --- 子图1: 原始数据负荷曲线 ---
    ax = axes[0, 0]
    # 找到负荷列
    load_col = None
    for col in step1.columns:
        if 'load' in col.lower() or 'demand' in col.lower():
            load_col = col
            break
    if load_col is None:
        load_col = step1.columns[0]

    sample = step1[load_col].values[:720]  # 取前30天
    ax.plot(range(len(sample)), sample, color='#2E86AB', linewidth=1, alpha=0.8)
    ax.set_title('(a) Original Load Data\n(Before Cleaning)', fontsize=13, fontweight='bold')
    ax.set_xlabel('Hour', fontsize=11)
    ax.set_ylabel('Load Value', fontsize=11)
    ax.grid(True, alpha=0.3)

    # --- 子图2: 清洗后负荷曲线 ---
    ax = axes[0, 1]
    load_col2 = None
    for col in step2.columns:
        if 'load' in col.lower() or 'demand' in col.lower():
            load_col2 = col
            break
    if load_col2 is None:
        load_col2 = step2.columns[0]

    sample2 = step2[load_col2].values[:720]
    ax.plot(range(len(sample2)), sample2, color='#1B998B', linewidth=1, alpha=0.8)
    ax.set_title('(b) Cleaned Load Data\n(After Anomaly Removal)', fontsize=13, fontweight='bold')
    ax.set_xlabel('Hour', fontsize=11)
    ax.set_ylabel('Load Value', fontsize=11)
    ax.grid(True, alpha=0.3)

    # --- 子图3: 归一化后负荷分布 ---
    ax = axes[0, 2]
    # 原始 vs 归一化 分布对比
    orig_vals = step1[load_col].dropna().values
    norm_vals = step5['X_train'][:, 0] if isinstance(step5, dict) and 'X_train' in step5 else None
    if norm_vals is None:
        # try other keys
        for k, v in step5.items():
            if isinstance(v, np.ndarray) and v.ndim == 2:
                norm_vals = v[:, 0]
                break

    if norm_vals is not None:
        ax.hist(orig_vals, bins=80, alpha=0.5, color='#2E86AB', label='Before Normalization', density=True)
        ax.hist(norm_vals, bins=80, alpha=0.5, color='#C73E1D', label='After Normalization', density=True)
        ax.legend(fontsize=10)
    ax.set_title('(c) Distribution: Before vs\nAfter Normalization', fontsize=13, fontweight='bold')
    ax.set_xlabel('Value', fontsize=11)
    ax.set_ylabel('Density', fontsize=11)
    ax.grid(True, alpha=0.3)

    # --- 子图4: 数据量变化 ---
    ax = axes[1, 0]
    stages = ['Raw Data', 'Cleaned', 'Feature\nEngineered', 'Train Split', 'Val Split', 'Test Split']
    counts = [
        len(step1),
        len(step2),
        len(step4),
        step5.get('X_train', np.array([])).shape[0] if isinstance(step5, dict) else 0,
        step5.get('X_val', np.array([])).shape[0] if isinstance(step5, dict) else 0,
        step5.get('X_test', np.array([])).shape[0] if isinstance(step5, dict) else 0,
    ]
    bar_colors = ['#2E86AB', '#1B998B', '#A23B72', '#F18F01', '#6A4C93', '#C73E1D']
    bars = ax.bar(stages, counts, color=bar_colors, alpha=0.8, edgecolor='white')
    for bar, count in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(counts)*0.01,
                f'{count:,}', ha='center', fontsize=10, fontweight='bold')
    ax.set_title('(d) Sample Count at Each Stage', fontsize=13, fontweight='bold')
    ax.set_ylabel('Number of Samples', fontsize=11)
    ax.grid(True, alpha=0.3, axis='y')

    # --- 子图5: 特征数量变化 ---
    ax = axes[1, 1]
    feat_stages = ['Raw', 'Cleaned', 'Engineered', 'Final Selected']
    feat_counts = [step1.shape[1], step2.shape[1], step4.shape[1], 38]
    bars = ax.bar(feat_stages, feat_counts, color=['#2E86AB', '#1B998B', '#A23B72', '#C73E1D'],
                  alpha=0.8, edgecolor='white')
    for bar, count in zip(bars, feat_counts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{count}', ha='center', fontsize=12, fontweight='bold')
    ax.set_title('(e) Feature Count Evolution', fontsize=13, fontweight='bold')
    ax.set_ylabel('Number of Features', fontsize=11)
    ax.grid(True, alpha=0.3, axis='y')

    # --- 子图6: 异常值统计 ---
    ax = axes[1, 2]
    if isinstance(anomaly, dict):
        # 尝试提取异常值信息
        anomaly_types = list(anomaly.keys())[:6]
        anomaly_counts = []
        for k in anomaly_types:
            v = anomaly[k]
            if isinstance(v, (int, float)):
                anomaly_counts.append(v)
            elif isinstance(v, (list, np.ndarray)):
                anomaly_counts.append(len(v))
            elif isinstance(v, dict):
                anomaly_counts.append(sum(v.values()) if all(isinstance(x, (int, float)) for x in v.values()) else len(v))
            else:
                anomaly_counts.append(0)

        if anomaly_types and anomaly_counts:
            bars = ax.barh(range(len(anomaly_types)), anomaly_counts,
                          color=['#C73E1D', '#F18F01', '#A23B72', '#2E86AB', '#1B998B', '#6A4C93'][:len(anomaly_types)],
                          alpha=0.8)
            ax.set_yticks(range(len(anomaly_types)))
            ax.set_yticklabels([str(k)[:20] for k in anomaly_types], fontsize=10)
            for i, v in enumerate(anomaly_counts):
                ax.text(v + max(anomaly_counts)*0.01, i, str(v), va='center', fontsize=10, fontweight='bold')
            ax.set_title('(f) Anomaly Detection Summary', fontsize=13, fontweight='bold')
            ax.set_xlabel('Count', fontsize=11)
            ax.grid(True, alpha=0.3, axis='x')
        else:
            ax.text(0.5, 0.5, 'No anomaly data', ha='center', va='center', transform=ax.transAxes, fontsize=14)
            ax.set_title('(f) Anomaly Detection Summary', fontsize=13, fontweight='bold')
    else:
        ax.text(0.5, 0.5, 'No anomaly data', ha='center', va='center', transform=ax.transAxes, fontsize=14)
        ax.set_title('(f) Anomaly Detection Summary', fontsize=13, fontweight='bold')

    fig.suptitle('Data Preprocessing Pipeline: Before vs After Comparison',
                 fontsize=17, fontweight='bold', y=1.01)
    plt.tight_layout()
    save_fig(fig, "fig21_preprocessing_comparison.png")

# ============================================================
# 图2: 模型训练时间和参数量对比图
# ============================================================
def generate_training_time_comparison():
    """生成模型训练时间和参数量对比图"""
    print("[2/2] Generating training time & parameters comparison chart...")

    model_names = ['EnhancedLSTM', 'SpatialTransformer', 'DeepTCN', 'BiGRU']
    param_counts = {
        'EnhancedLSTM': 458144,
        'SpatialTransformer': 908024,
        'DeepTCN': 157400,
        'BiGRU': 1408088,
    }

    # 从checkpoint获取训练信息
    epochs_trained = {}
    for name in model_names:
        path = os.path.join("outputs", f"{name.lower()}_best_model.pth")
        ckpt = torch.load(path, map_location='cpu', weights_only=False)
        epochs_trained[name] = len(ckpt['training_history']['train_loss'])

    # 从日志解析训练时间
    training_times = {}
    log_path = "training.log"
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            log_content = f.read()

        # 尝试从日志中提取训练耗时
        import re
        for name in model_names:
            # 匹配 "xxx 训练完成! 耗时: xxx秒" 或类似模式
            patterns = [
                rf'{name}.*?(\d+)\s*秒',
                rf'{name}.*?(\d+)\s*seconds',
                rf'{name}.*?(\d+)\s*s\b',
            ]
            for pattern in patterns:
                match = re.search(pattern, log_content)
                if match:
                    training_times[name] = int(match.group(1))
                    break

    # 如果无法从日志提取，使用已知数据
    if not training_times:
        # 从之前的训练记录中获取
        training_times = {
            'EnhancedLSTM': 445,
            'SpatialTransformer': 1443,  # 约24分钟
            'DeepTCN': 126,
            'BiGRU': 1392,
        }

    print(f"  Training times: {training_times}")
    print(f"  Epochs trained: {epochs_trained}")

    fig, axes = plt.subplots(1, 3, figsize=(20, 6))

    # --- 子图1: 训练时间柱状图 ---
    ax = axes[0]
    times = [training_times.get(n, 0) for n in model_names]
    colors = [MODEL_COLORS[n] for n in model_names]
    bars = ax.bar(model_names, times, color=colors, alpha=0.8, edgecolor='white', linewidth=1.5)

    for bar, t in zip(bars, times):
        mins = t // 60
        secs = t % 60
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(times)*0.01,
                f'{mins}m{secs}s', ha='center', fontsize=11, fontweight='bold')

    ax.set_ylabel('Training Time (seconds)', fontsize=13)
    ax.set_title('(a) Training Time Comparison', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    ax.tick_params(axis='x', rotation=25)

    # --- 子图2: 参数量柱状图 ---
    ax = axes[1]
    params = [param_counts[n] for n in model_names]
    bars = ax.bar(model_names, params, color=colors, alpha=0.8, edgecolor='white', linewidth=1.5)

    for bar, p in zip(bars, params):
        if p > 1e6:
            label = f'{p/1e6:.2f}M'
        else:
            label = f'{p/1e3:.1f}K'
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(params)*0.01,
                label, ha='center', fontsize=11, fontweight='bold')

    ax.set_ylabel('Number of Parameters', fontsize=13)
    ax.set_title('(b) Model Parameters Comparison', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    ax.tick_params(axis='x', rotation=25)

    # --- 子图3: 训练时间 vs 参数量散点图 ---
    ax = axes[2]
    for name in model_names:
        ax.scatter(param_counts[name]/1e6, training_times.get(name, 0),
                  s=300, color=MODEL_COLORS[name], alpha=0.7, edgecolors='white', linewidth=2, zorder=5)
        ax.annotate(f'{name}\n({epochs_trained[name]} epochs)',
                   (param_counts[name]/1e6, training_times.get(name, 0)),
                   textcoords="offset points", xytext=(12, 8),
                   fontsize=10, fontweight='bold',
                   arrowprops=dict(arrowstyle='->', color='gray'))

    ax.set_xlabel('Parameters (Millions)', fontsize=13)
    ax.set_ylabel('Training Time (seconds)', fontsize=13)
    ax.set_title('(c) Training Time vs Model Complexity', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)

    fig.suptitle('Model Training Time and Parameters Comparison',
                 fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    save_fig(fig, "fig22_training_time_params.png")

    # 额外生成一张：每个epoch平均训练时间对比
    fig, ax = plt.subplots(figsize=(12, 6))
    per_epoch_times = []
    for name in model_names:
        total_time = training_times.get(name, 1)
        n_epochs = epochs_trained.get(name, 1)
        per_epoch_times.append(total_time / n_epochs)

    bars = ax.bar(model_names, per_epoch_times, color=colors, alpha=0.8, edgecolor='white', linewidth=1.5)
    for bar, t in zip(bars, per_epoch_times):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(per_epoch_times)*0.01,
                f'{t:.1f}s/epoch', ha='center', fontsize=11, fontweight='bold')

    ax.set_ylabel('Time per Epoch (seconds)', fontsize=13)
    ax.set_xlabel('Model', fontsize=13)
    ax.set_title('Average Training Time per Epoch', fontsize=15, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    ax.tick_params(axis='x', rotation=25)
    save_fig(fig, "fig23_time_per_epoch.png")

def main():
    print("=" * 60)
    print("Supplementary Chart Generation")
    print("=" * 60)
    generate_preprocessing_comparison()
    generate_training_time_comparison()
    print("\nDone! All supplementary charts generated.")

if __name__ == "__main__":
    main()
