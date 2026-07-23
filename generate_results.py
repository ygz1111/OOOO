# -*- coding: utf-8 -*-
"""
从已保存的模型结果生成集成预测和论文图表
（无需重新训练）
"""
import os
import torch
import numpy as np
import pickle
import logging
from models.four_models import create_four_models
from models.visualization import PaperVisualizer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def main():
    output_dir = "outputs"
    visualization_dir = "visualizations"
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    logger.info(f"使用设备: {device}")
    
    # 1. 加载测试数据
    logger.info("加载数据...")
    with open("processed/step6_sequences.pkl", "rb") as f:
        seq_data = pickle.load(f)
    
    X_test = torch.FloatTensor(seq_data["X_test_seq"]).to(device)
    y_test = torch.FloatTensor(seq_data["y_test_seq"]).to(device)
    
    # 2. 加载已保存的模型结果
    model_names = ['EnhancedLSTM', 'SpatialTransformer', 'DeepTCN', 'BiGRU']
    training_results = {}
    
    for name in model_names:
        model_path = os.path.join(output_dir, f"{name.lower()}_best_model.pth")
        logger.info(f"加载 {name} 模型: {model_path}")
        
        checkpoint = torch.load(model_path, map_location=device, weights_only=False)
        
        training_results[name] = {
            'model': None,  # 不需要模型实例
            'best_state_dict': checkpoint['model_state_dict'],
            'training_history': checkpoint['training_history'],
            'test_results': checkpoint['test_results'],
            'predictions': checkpoint['test_results']['predictions'],
            'targets': checkpoint['test_results']['targets'],
            'epochs_trained': len(checkpoint['training_history']['train_loss']),
            'total_params': 0,  # 后面补充
            'model_name': name
        }
        
        logger.info(f"  {name}: R²={checkpoint['test_results']['r2']:.4f}, RMSE={checkpoint['test_results']['rmse']:.6f}")
    
    # 3. 创建模型实例获取参数量
    models, _ = create_four_models(device_info=False)
    for name in model_names:
        training_results[name]['total_params'] = sum(p.numel() for p in models[name].parameters())
    
    # 4. 集成预测
    logger.info("\n生成集成模型预测...")
    all_preds = []
    for name in model_names:
        all_preds.append(training_results[name]['predictions'])
    
    ensemble_pred = np.mean(all_preds, axis=0)
    targets = training_results['EnhancedLSTM']['targets']
    
    # 计算集成指标
    eps = 1e-10
    mse = np.mean((targets - ensemble_pred) ** 2)
    rmse = np.sqrt(mse)
    mae = np.mean(np.abs(targets - ensemble_pred))
    mape = np.mean(np.abs((targets - ensemble_pred) / (np.abs(targets) + eps))) * 100
    ss_res = np.sum((targets - ensemble_pred) ** 2)
    ss_tot = np.sum((targets - np.mean(targets)) ** 2)
    r2 = 1 - (ss_res / (ss_tot + eps))
    
    ensemble_metrics = {
        'mse': float(mse), 'rmse': float(rmse), 'mae': float(mae),
        'mape': float(mape), 'r2': float(r2)
    }
    
    logger.info(f"\n集成模型结果:")
    logger.info(f"  RMSE: {ensemble_metrics['rmse']:.6f}")
    logger.info(f"  MAE:  {ensemble_metrics['mae']:.6f}")
    logger.info(f"  MAPE: {ensemble_metrics['mape']:.3f}%")
    logger.info(f"  R²:   {ensemble_metrics['r2']:.4f}")
    
    training_results['Ensemble'] = {
        'model': None,
        'best_state_dict': None,
        'training_history': None,
        'test_results': ensemble_metrics,
        'predictions': ensemble_pred,
        'targets': targets,
        'epochs_trained': 0,
        'total_params': 0,
        'model_name': 'Ensemble'
    }
    
    # 5. 生成可视化图表
    logger.info("\n生成论文级可视化图表...")
    visualizer = PaperVisualizer(visualization_dir)
    visualizer.create_paper_ready_figures(training_results)
    
    # 6. 打印最终结果对比
    logger.info("\n" + "=" * 80)
    logger.info("四模型 + 集成模型 最终结果对比")
    logger.info("=" * 80)
    logger.info(f"{'模型':<25} {'RMSE':<12} {'MAE':<12} {'R²':<10}")
    logger.info("-" * 60)
    
    for name, result in training_results.items():
        tr = result['test_results']
        logger.info(f"{name:<25} {tr['rmse']:<12.6f} {tr['mae']:<12.6f} {tr['r2']:<10.4f}")
    
    logger.info("=" * 80)
    
    # 7. 保存训练摘要
    import json
    summary = {
        'models': list(training_results.keys()),
        'results': {
            name: {
                'rmse': result['test_results']['rmse'],
                'mae': result['test_results']['mae'],
                'mape': result['test_results']['mape'],
                'r2': result['test_results']['r2'],
            }
            for name, result in training_results.items()
        }
    }
    
    with open(os.path.join(output_dir, 'final_results.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\n结果摘要已保存: {output_dir}/final_results.json")
    logger.info(f"可视化图表已保存: {visualization_dir}/")
    logger.info("\n全部完成!")

if __name__ == "__main__":
    main()
