#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 预测结果对比分析模块

功能：
  1. 多模型预测结果对比
  2. 历史预测准确性趋势分析
  3. 预测误差分布分析
  4. 时间维度分析（日/周/月）
  5. 负荷特性分析（峰谷/节假日）

作者: 毕业设计项目
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, deque
import logging

# 项目路径
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PredictionComparator:
    """预测结果对比分析器"""
    
    def __init__(self):
        logger.info("✅ 预测结果对比分析器初始化完成")
    
    def compare_models(self, predictions_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        多模型预测结果对比
        
        Args:
            predictions_data: 预测数据列表，每个元素包含模型预测结果
            
        Returns:
            对比分析结果
        """
        if not predictions_data:
            return {"error": "无预测数据"}
        
        # 按模型类型分组
        model_predictions = defaultdict(list)
        for pred in predictions_data:
            model_type = pred.get('model_type', 'unknown')
            model_predictions[model_type].append(pred)
        
        comparison_results = {}
        model_stats = {}
        
        # 计算每个模型的统计指标
        for model_type, preds in model_predictions.items():
            if not preds:
                continue
                
            # 提取预测值和实际值
            # 2026-08 修复：按行成对过滤（同时含预测值与实际值），
            # 此前 predictions[:len(actuals)] 按长度截断，中间缺 actual 时错位配对。
            predictions = [p.get('load_forecast_mw', 0) for p in preds]
            paired = [
                (p.get('load_forecast_mw'), p.get('actual_load_mw'))
                for p in preds
                if p.get('load_forecast_mw') is not None and p.get('actual_load_mw') is not None
            ]
            actuals = [a for _, a in paired]

            if len(actuals) == 0:
                # 如果没有实际值，只计算预测统计
                model_stats[model_type] = {
                    "count": len(predictions),
                    "pred_mean": np.mean(predictions),
                    "pred_std": np.std(predictions),
                    "pred_min": np.min(predictions),
                    "pred_max": np.max(predictions)
                }
            else:
                # 计算预测准确性指标
                predictions = [p for p, _ in paired]

                mae = np.mean(np.abs(np.array(actuals) - np.array(predictions)))
                rmse = np.sqrt(np.mean((np.array(actuals) - np.array(predictions)) ** 2))
                
                # MAPE计算（避免除以零）
                mask = np.abs(np.array(actuals)) > 1e-6
                if np.any(mask):
                    mape = np.mean(np.abs((np.array(actuals)[mask] - np.array(predictions)[mask]) / np.array(actuals)[mask])) * 100
                else:
                    mape = 0.0
                
                # R²计算
                ss_res = np.sum((np.array(actuals) - np.array(predictions)) ** 2)
                ss_tot = np.sum((np.array(actuals) - np.mean(actuals)) ** 2)
                r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0
                
                model_stats[model_type] = {
                    "count": len(predictions),
                    "mae": float(mae),
                    "rmse": float(rmse),
                    "mape": float(mape),
                    "r2": float(r2),
                    "pred_mean": float(np.mean(predictions)),
                    "pred_std": float(np.std(predictions)),
                    "actual_mean": float(np.mean(actuals)),
                    "actual_std": float(np.std(actuals))
                }
        
        # 找出最佳模型
        best_model = None
        best_mape = float('inf')
        
        for model_type, stats in model_stats.items():
            if 'mape' in stats and stats['mape'] < best_mape:
                best_mape = stats['mape']
                best_model = model_type
        
        comparison_results = {
            "model_comparison": model_stats,
            "best_model": best_model,
            "best_mape": best_mape if best_model else None,
            "total_predictions": len(predictions_data),
            "models_count": len(model_stats)
        }
        
        return comparison_results
    
    def analyze_temporal_trends(self, predictions_data: List[Dict[str, Any]], 
                              time_window: str = 'daily') -> Dict[str, Any]:
        """
        时间维度趋势分析
        
        Args:
            predictions_data: 预测数据
            time_window: 时间窗口 ('hourly', 'daily', 'weekly')
            
        Returns:
            时间趋势分析结果
        """
        if not predictions_data:
            return {"error": "无预测数据"}
        
        # 转换为DataFrame以便分析
        df_data = []
        for pred in predictions_data:
            if 'target_timestamp' not in pred:
                continue
                
            try:
                timestamp = datetime.fromisoformat(pred['target_timestamp'].replace('Z', '+00:00'))
                
                record = {
                    'timestamp': timestamp,
                    'target_timestamp': timestamp,
                    'prediction': pred.get('load_forecast_mw', 0),
                    'actual': pred.get('actual_load_mw', 0) if 'actual_load_mw' in pred else None,
                    'model_type': pred.get('model_type', 'unknown')
                }
                
                if record['actual'] is not None:
                    record['error'] = record['actual'] - record['prediction']
                    record['abs_error'] = abs(record['error'])
                    if abs(record['actual']) > 1e-6:
                        record['percentage_error'] = (record['error'] / record['actual']) * 100
                    else:
                        record['percentage_error'] = 0.0
                
                df_data.append(record)
            except Exception as e:
                logger.warning(f"时间戳解析失败: {e}")
                continue
        
        if not df_data:
            return {"error": "无有效时间数据"}
        
        df = pd.DataFrame(df_data)
        df.set_index('target_timestamp', inplace=True)
        
        analysis_results = {}
        
        # 按时间窗口分组分析
        if time_window == 'hourly':
            grouped = df.groupby(df.index.hour)
            time_label = 'hour'
        elif time_window == 'daily':
            grouped = df.groupby(df.index.date)
            time_label = 'date'
        elif time_window == 'weekly':
            grouped = df.groupby(df.index.weekday)
            time_label = 'weekday'
        else:
            return {"error": "不支持的时间窗口"}
        
        temporal_stats = {}
        
        for time_period, group in grouped:
            if len(group) == 0:
                continue
                
            if 'actual' in group.columns and group['actual'].notna().any():
                # 有实际值的数据
                valid_group = group.dropna(subset=['actual'])
                
                stats = {
                    "count": len(valid_group),
                    "pred_mean": float(valid_group['prediction'].mean()),
                    "pred_std": float(valid_group['prediction'].std()),
                    "actual_mean": float(valid_group['actual'].mean()),
                    "actual_std": float(valid_group['actual'].std()),
                    "mae": float(valid_group['abs_error'].mean()),
                    "rmse": float(np.sqrt((valid_group['error'] ** 2).mean())),
                }
                
                # 计算MAPE
                mask = abs(valid_group['actual']) > 1e-6
                if mask.any():
                    mape = (abs(valid_group.loc[mask, 'error']) / abs(valid_group.loc[mask, 'actual'])).mean() * 100
                    stats["mape"] = float(mape)
                else:
                    stats["mape"] = 0.0
                    
            else:
                # 只有预测值的数据
                stats = {
                    "count": len(group),
                    "pred_mean": float(group['prediction'].mean()),
                    "pred_std": float(group['prediction'].std()),
                    "pred_min": float(group['prediction'].min()),
                    "pred_max": float(group['prediction'].max())
                }
            
            temporal_stats[str(time_period)] = stats
        
        analysis_results = {
            "time_window": time_window,
            "temporal_analysis": temporal_stats,
            "total_records": len(df),
            "time_range": {
                "start": df.index.min().isoformat() if len(df) > 0 else None,
                "end": df.index.max().isoformat() if len(df) > 0 else None
            }
        }
        
        return analysis_results
    
    def analyze_error_distribution(self, predictions_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        预测误差分布分析
        
        Args:
            predictions_data: 预测数据
            
        Returns:
            误差分布分析结果
        """
        errors = []
        percentage_errors = []
        
        for pred in predictions_data:
            if 'actual_load_mw' not in pred:
                continue
                
            prediction = pred.get('load_forecast_mw', 0)
            actual = pred.get('actual_load_mw', 0)
            
            # 全站统一：正误差表示预测高于实际。
            error = prediction - actual
            errors.append(error)
            
            if abs(actual) > 1e-6:
                percentage_error = (error / actual) * 100
                percentage_errors.append(percentage_error)
        
        if not errors:
            return {"error": "无有效的误差数据"}
        
        errors = np.array(errors)
        percentage_errors = np.array(percentage_errors)
        
        # 误差分布统计
        error_stats = {
            "count": len(errors),
            "mean": float(np.mean(errors)),
            "std": float(np.std(errors)),
            "min": float(np.min(errors)),
            "max": float(np.max(errors)),
            "q25": float(np.percentile(errors, 25)),
            "q50": float(np.percentile(errors, 50)),  # 中位数
            "q75": float(np.percentile(errors, 75)),
            "rmse": float(np.sqrt(np.mean(errors ** 2))),
            "mae": float(np.mean(np.abs(errors)))
        }
        
        # 百分比误差统计
        if len(percentage_errors) > 0:
            percentage_stats = {
                "count": len(percentage_errors),
                "mean": float(np.mean(percentage_errors)),
                "std": float(np.std(percentage_errors)),
                "min": float(np.min(percentage_errors)),
                "max": float(np.max(percentage_errors)),
                "q25": float(np.percentile(percentage_errors, 25)),
                "q50": float(np.percentile(percentage_errors, 50)),
                "q75": float(np.percentile(percentage_errors, 75)),
                "mape": float(np.mean(np.abs(percentage_errors)))
            }
        else:
            percentage_stats = {}
        
        # 误差分布直方图数据（简化版）
        hist_bins = 20
        hist_range = (np.percentile(errors, 1), np.percentile(errors, 99))
        hist_counts, hist_edges = np.histogram(errors, bins=hist_bins, range=hist_range)
        
        histogram_data = {
            "counts": hist_counts.tolist(),
            "edges": hist_edges.tolist(),
            "bins": hist_bins,
            "range": [float(hist_range[0]), float(hist_range[1])]
        }
        
        return {
            "error_distribution": error_stats,
            "percentage_error_distribution": percentage_stats,
            "histogram": histogram_data
        }
    
    def analyze_load_patterns(self, predictions_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        负荷特性分析
        
        Args:
            predictions_data: 预测数据
            
        Returns:
            负荷特性分析结果
        """
        hourly_loads = defaultdict(list)
        daily_loads = defaultdict(list)
        
        for pred in predictions_data:
            if 'target_timestamp' not in pred:
                continue
                
            try:
                timestamp = datetime.fromisoformat(pred['target_timestamp'].replace('Z', '+00:00'))
                hour = timestamp.hour
                date = timestamp.date()
                
                actual_load = pred.get('actual_load_mw')
                if actual_load is not None:
                    hourly_loads[hour].append(actual_load)
                    daily_loads[str(date)].append(actual_load)
                    
            except Exception as e:
                logger.warning(f"时间戳解析失败: {e}")
                continue
        
        # 小时负荷特性
        hourly_patterns = {}
        for hour in range(24):
            if hour in hourly_loads and hourly_loads[hour]:
                loads = hourly_loads[hour]
                hourly_patterns[str(hour)] = {
                    "count": len(loads),
                    "mean": float(np.mean(loads)),
                    "std": float(np.std(loads)),
                    "min": float(np.min(loads)),
                    "max": float(np.max(loads)),
                    "q50": float(np.percentile(loads, 50))
                }
        
        # 找出峰谷时段
        peak_hours = []
        valley_hours = []
        
        if hourly_patterns:
            avg_loads = {hour: stats["mean"] for hour, stats in hourly_patterns.items()}
            sorted_hours = sorted(avg_loads.items(), key=lambda x: x[1], reverse=True)
            
            # 前25%为高峰时段，后25%为低谷时段
            n_hours = len(sorted_hours)
            peak_count = max(1, n_hours // 4)
            valley_count = max(1, n_hours // 4)
            
            peak_hours = [int(hour) for hour, _ in sorted_hours[:peak_count]]
            valley_hours = [int(hour) for hour, _ in sorted_hours[-valley_count:]]
        
        # 日负荷特性
        daily_stats = {}
        for date_str, loads in daily_loads.items():
            if loads:
                daily_stats[date_str] = {
                    "count": len(loads),
                    "mean": float(np.mean(loads)),
                    "peak": float(np.max(loads)),
                    "valley": float(np.min(loads)),
                    "peak_valley_ratio": float(np.max(loads) / np.min(loads)) if np.min(loads) > 0 else 1.0
                }
        
        return {
            "hourly_patterns": hourly_patterns,
            "peak_hours": sorted(peak_hours),
            "valley_hours": sorted(valley_hours),
            "daily_patterns": daily_stats,
            "analysis_summary": {
                "total_hours_analyzed": len(hourly_patterns),
                "peak_valley_hours_identified": len(peak_hours) + len(valley_hours)
            }
        }
    
    def generate_comprehensive_report(self, predictions_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        生成综合分析报告
        
        Args:
            predictions_data: 预测数据
            
        Returns:
            综合分析报告
        """
        logger.info(f"开始生成综合分析报告，共 {len(predictions_data)} 条预测记录")
        
        # 执行各项分析
        model_comparison = self.compare_models(predictions_data)
        temporal_analysis = self.analyze_temporal_trends(predictions_data, 'daily')
        error_analysis = self.analyze_error_distribution(predictions_data)
        load_patterns = self.analyze_load_patterns(predictions_data)
        
        # 生成总结
        summary = {
            "total_predictions": len(predictions_data),
            "analysis_timestamp": datetime.now().isoformat(),
            "key_findings": []
        }
        
        # 分析关键发现
        if 'best_model' in model_comparison and model_comparison['best_model']:
            best_model = model_comparison['best_model']
            best_mape = model_comparison.get('best_mape', 0)
            summary["key_findings"].append(f"最佳模型: {best_model} (MAPE: {best_mape:.2f}%)")
        
        if error_analysis and 'error_distribution' in error_analysis:
            mape = error_analysis['percentage_error_distribution'].get('mape', 0)
            summary["key_findings"].append(f"整体MAPE: {mape:.2f}%")
            
            # 误差水平评估
            if mape < 3:
                summary["key_findings"].append("预测精度: 优秀 (< 3%)")
            elif mape < 5:
                summary["key_findings"].append("预测精度: 良好 (3-5%)")
            elif mape < 10:
                summary["key_findings"].append("预测精度: 一般 (5-10%)")
            else:
                summary["key_findings"].append("预测精度: 需改进 (> 10%)")
        
        if load_patterns and 'peak_hours' in load_patterns:
            peak_hours = load_patterns['peak_hours']
            summary["key_findings"].append(f"高峰时段: {peak_hours}")
        
        return {
            "summary": summary,
            "model_comparison": model_comparison,
            "temporal_analysis": temporal_analysis,
            "error_analysis": error_analysis,
            "load_patterns": load_patterns
        }


# 单例实例
prediction_analytics = PredictionComparator()

def get_prediction_analytics() -> PredictionComparator:
    """获取预测分析器单例"""
    return prediction_analytics
