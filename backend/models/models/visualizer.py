"""
可视化工具：生成训练曲线、预测对比、误差分析等图表
"""

import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端（保存图片）
import numpy as np
from datetime import datetime, timedelta
import json
import os


class Visualizer:
    """可视化器"""

    def __init__(self, output_dir="outputs"):
        """
        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        # 设置中文字体（可选）
        plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False

        # 默认样式
        plt.style.use('seaborn-v0_8-darkgrid')

    def plot_training_history(self, history, model_name, save_path=None):
        """
        绘制训练历史曲线

        Args:
            history: 训练历史
            model_name: 模型名称
            save_path: 保存路径
        """
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        # Loss 曲线
        axes[0].plot(history.history['loss'], label='Train Loss', linewidth=2)
        axes[0].plot(history.history['val_loss'], label='Val Loss', linewidth=2)
        axes[0].set_xlabel('Epoch')
        axes[0].set_ylabel('Loss')
        axes[0].set_title(f'{model_name} - Training Loss')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)

        # MAE 曲线
        axes[1].plot(history.history['mae'], label='Train MAE', linewidth=2)
        axes[1].plot(history.history['val_mae'], label='Val MAE', linewidth=2)
        axes[1].set_xlabel('Epoch')
        axes[1].set_ylabel('MAE (MW)')
        axes[1].set_title(f'{model_name} - Training MAE')
        axes[1].legend()
        axes[1].grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path is None:
            save_path = os.path.join(self.output_dir, f"{model_name}_training_history.png")
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[保存] 训练历史: {save_path}")
        return save_path

    def plot_prediction_comparison(self, y_true, y_pred, scaler,
                                   model_name, n_samples=168, save_path=None):
        """
        绘制预测对比图（过去7天 + 未来24小时）

        Args:
            y_true: 真实值 (n_samples, horizon)
            y_pred: 预测值 (n_samples, horizon)
            scaler: 目标Scaler
            model_name: 模型名称
            n_samples: 显示样本数
            save_path: 保存路径
        """
        # 反归一化
        y_true_orig = scaler.inverse_transform(y_true)
        y_pred_orig = scaler.inverse_transform(y_pred)

        # 取第一个样本的预测结果（未来24小时）
        true_24h = y_true_orig[0, :]  # 24小时真实值
        pred_24h = y_pred_orig[0, :]  # 24小时预测值

        # 过去7天历史（n_samples个样本，取n_samples-168+1开始）
        history_168h = y_true_orig[n_samples-168: n_samples, 0]  # 只取第0小时

        # 组合：过去7天 + 未来24小时
        total_hours = 168 + 24
        hours = list(range(-168, 24))
        total_values = np.concatenate([history_168h, true_24h])
        pred_values = np.concatenate([np.full(168, np.nan), pred_24h])

        # 绘制
        fig, ax = plt.subplots(1, 1, figsize=(14, 6))

        ax.plot(hours, total_values, label='实际负荷', linewidth=2, color='#2196F3')
        ax.plot(hours, pred_values, label='预测负荷', linewidth=2, color='#FF9800', linestyle='--')

        # 分隔线（当前时刻）
        ax.axvline(x=0, color='gray', linestyle=':', linewidth=2, label='当前时刻')

        # 填充预测区域
        ax.fill_between(hours[168:], pred_values, alpha=0.3, color='#FF9800')

        ax.set_xlabel('时间 (小时, 负=过去, 正=未来)')
        ax.set_ylabel('负荷 (MW)')
        ax.set_title(f'{model_name} - 24小时负荷预测对比')
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path is None:
            save_path = os.path.join(self.output_dir, f"{model_name}_prediction_24h.png")
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[保存] 预测对比图 (24h): {save_path}")
        return save_path

    def plot_prediction_7days(self, y_true, y_pred, scaler,
                              model_name, n_samples=168, save_path=None):
        """
        绘制7天连续预测对比（滚动预测）

        Args:
            y_true: 真实值
            y_pred: 预测值
            scaler: Scaler
            model_name: 模型名称
            n_samples: 起始样本索引
            save_path: 保存路径
        """
        # 反归一化
        y_true_orig = scaler.inverse_transform(y_true[n_samples:n_samples+168])
        y_pred_orig = scaler.inverse_transform(y_pred[n_samples:n_samples+168])

        hours = range(168)

        fig, ax = plt.subplots(1, 1, figsize=(14, 6))

        ax.plot(hours, y_true_orig.flatten(), label='实际负荷', linewidth=2)
        ax.plot(hours, y_pred_orig.flatten(), label='预测负荷', linewidth=2, linestyle='--')
        ax.fill_between(hours, y_true_orig.flatten(), y_pred_orig.flatten(), alpha=0.3)

        ax.set_xlabel('小时')
        ax.set_ylabel('负荷 (MW)')
        ax.set_title(f'{model_name} - 7天连续预测对比')
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path is None:
            save_path = os.path.join(self.output_dir, f"{model_name}_prediction_7d.png")
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[保存] 预测对比图 (7d): {save_path}")
        return save_path

    def plot_error_distribution(self, y_true, y_pred, scaler, model_name, save_path=None):
        """
        绘制误差分布直方图

        Args:
            y_true: 真实值
            y_pred: 预测值
            scaler: Scaler
            model_name: 模型名称
            save_path: 保存路径
        """
        # 反归一化
        y_true_orig = scaler.inverse_transform(y_true)
        y_pred_orig = scaler.inverse_transform(y_pred)

        errors = (y_true_orig - y_pred_orig).flatten()
        errors_percent = (errors / y_true_orig.flatten()) * 100

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        # 绝对误差分布
        axes[0].hist(errors, bins=50, edgecolor='black', alpha=0.7)
        axes[0].axvline(0, color='red', linestyle='--', linewidth=2)
        axes[0].set_xlabel('绝对误差 (MW)')
        axes[0].set_ylabel('频次')
        axes[0].set_title(f'{model_name} - 误差绝对分布')
        axes[0].grid(True, alpha=0.3)

        # 相对误差分布
        axes[1].hist(errors_percent, bins=50, edgecolor='black', alpha=0.7)
        axes[1].axvline(0, color='red', linestyle='--', linewidth=2)
        axes[1].set_xlabel('相对误差 (%)')
        axes[1].set_ylabel('频次')
        axes[1].set_title(f'{model_name} - 误差相对分布')
        axes[1].grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path is None:
            save_path = os.path.join(self.output_dir, f"{model_name}_error_distribution.png")
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[保存] 误差分布图: {save_path}")
        return save_path

    def plot_scatter(self, y_true, y_pred, scaler, model_name, save_path=None):
        """
        绘制预测值 vs 真实值散点图

        Args:
            y_true: 真实值
            y_pred: 预测值
            scaler: Scaler
            model_name: 模型名称
            save_path: 保存路径
        """
        # 反归一化
        y_true_orig = scaler.inverse_transform(y_true)
        y_pred_orig = scaler.inverse_transform(y_pred)

        fig, ax = plt.subplots(1, 1, figsize=(8, 8))

        ax.scatter(y_true_orig.flatten(), y_pred_orig.flatten(), alpha=0.3, s=1)
        
        # 理想预测线
        min_val = min(y_true_orig.min(), y_pred_orig.min())
        max_val = max(y_true_orig.max(), y_pred_orig.max())
        ax.plot([min_val, max_val], [min_val, max_val], 'r--', linewidth=2, label='理想预测')

        ax.set_xlabel('真实负荷 (MW)')
        ax.set_ylabel('预测负荷 (MW)')
        ax.set_title(f'{model_name} - 预测散点图')
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path is None:
            save_path = os.path.join(self.output_dir, f"{model_name}_scatter.png")
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[保存] 散点图: {save_path}")
        return save_path

    def plot_hourly_error(self, hourly_metrics, model_name, save_path=None):
        """
        绘制每个预测步长的误差

        Args:
            hourly_metrics: 每小时的指标列表
            model_name: 模型名称
            save_path: 保存路径
        """
        hours = [m['Hour'] for m in hourly_metrics]
        mapes = [m['MAPE'] for m in hourly_metrics]
        maes = [m['MAE'] for m in hourly_metrics]

        fig, ax1 = plt.subplots(1, 1, figsize=(12, 6))

        ax2 = ax1.twinx()

        # MAPE 柱状图
        ax1.bar(hours, mapes, alpha=0.7, color='#2196F3', label='MAPE (%)')
        ax1.set_xlabel('预测步长 (小时)')
        ax1.set_ylabel('MAPE (%)', color='#2196F3')
        ax1.tick_params(axis='y', labelcolor='#2196F3')

        # MAE 折线图
        ax2.plot(hours, maes, color='#FF9800', linewidth=2, marker='o', label='MAE (MW)')
        ax2.set_ylabel('MAE (MW)', color='#FF9800')
        ax2.tick_params(axis='y', labelcolor='#FF9800')

        ax1.set_title(f'{model_name} - 每小时预测误差')
        ax1.legend(loc='upper left')
        ax2.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path is None:
            save_path = os.path.join(self.output_dir, f"{model_name}_hourly_error.png")
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[保存] 每小时误差图: {save_path}")
        return save_path

    def plot_model_comparison(self, results_dict, metric="MAPE", save_path=None):
        """
        绘制多模型对比图

        Args:
            results_dict: {model_name: {metrics: {...}}}
            metric: 要对比的指标
            save_path: 保存路径
        """
        models = list(results_dict.keys())
        values = [results_dict[m][metric] for m in models]

        fig, ax = plt.subplots(1, 1, figsize=(10, 6))

        colors = ['#2196F3', '#4CAF50', '#FF9800', '#F44336', '#9C27B0']
        bars = ax.bar(models, values, color=colors[:len(models)])

        # 在柱子上标注数值
        for bar, value in zip(bars, values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{value:.2f}', ha='center', va='bottom')

        ax.set_ylabel(f'{metric}')
        ax.set_title(f'模型对比 - {metric}')
        ax.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()

        if save_path is None:
            save_path = os.path.join(self.output_dir, f"model_comparison_{metric}.png")
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[保存] 模型对比图 ({metric}): {save_path}")
        return save_path

    def save_metrics_json(self, results_dict, save_path=None):
        """保存评估指标为 JSON"""
        if save_path is None:
            save_path = os.path.join(self.output_dir, "evaluation_results.json")

        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(results_dict, f, indent=2, ensure_ascii=False)

        print(f"[保存] 评估指标 JSON: {save_path}")
        return save_path