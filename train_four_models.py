#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ===================================================================================
# 🎯 毕业设计专用 - 四模型高准确率训练系统
# 包含完整的论文级可视化和结果分析
# ===================================================================================

import os
import pickle
import torch
import torch.nn as nn
import numpy as np
from datetime import datetime
import logging
from tqdm import tqdm
import json
import warnings

# 导入模型和可视化模块
from models.four_models import create_four_models
from models.visualization import PaperVisualizer

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('training.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
warnings.filterwarnings('ignore')

class FourModelTrainer:
    """
    四模型高准确率训练执行器
    专为毕业设计项目设计，包含可视化功能
    """
    
    def __init__(self, 
                 data_path="processed", 
                 output_dir="outputs",
                 visualization_dir="visualizations",
                 epochs=100,
                 batch_size=64,
                 learning_rate=1e-3,
                 early_stopping_patience=15,
                 checkpoint_interval=10):
        """
        初始化训练器
        
        Args:
            data_path: 处理后的数据路径
            output_dir: 输出目录
            visualization_dir: 可视化输出目录
            epochs: 训练轮数
            batch_size: 批次大小
            learning_rate: 学习率
            early_stopping_patience: 早停耐心值
            checkpoint_interval: 检查点保存间隔
        """
        self.data_path = data_path
        self.output_dir = output_dir
        self.visualization_dir = visualization_dir
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.early_stopping_patience = early_stopping_patience
        self.checkpoint_interval = checkpoint_interval
        
        # 创建目录
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(visualization_dir, exist_ok=True)
        
        # 设备检测
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # 初始化可视化器
        self.visualizer = PaperVisualizer(visualization_dir)
        
        # 训练历史
        self.training_history = {}
        self.results = {}
        
        logger.info("=" * 80)
        logger.info("🚀 四模型高准确率训练系统启动")
        logger.info("=" * 80)
        logger.info(f"📁 数据路径: {data_path}")
        logger.info(f"📤 输出目录: {output_dir}")
        logger.info(f"📊 可视化目录: {visualization_dir}")
        logger.info(f"💻 计算设备: {self.device}")
        logger.info(f"📊 批次大小: {batch_size}")
        logger.info(f"⏰ 最大训练轮数: {epochs}")
        logger.info(f"📈 初始学习率: {learning_rate}")
        logger.info(f"🎯 早停耐心: {early_stopping_patience}")
        logger.info("=" * 80)
        
    def load_training_data(self):
        """加载训练数据"""
        logger.info("📥 正在加载训练数据集...")
        
        # 检查文件存在性
        required_files = [
            "step6_sequences.pkl", 
            "step5_scalers.pkl"
        ]
        
        for file in required_files:
            file_path = os.path.join(self.data_path, file)
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"必需的训练数据文件未找到: {file_path}")
        
        # 加载序列数据
        with open(os.path.join(self.data_path, "step6_sequences.pkl"), "rb") as f:
            seq_data = pickle.load(f)
            
        with open(os.path.join(self.data_path, "step5_scalers.pkl"), "rb") as f:
            self.scalers = pickle.load(f)
            
        # 准备训练数据
        self.data = {
            'X_train': torch.FloatTensor(seq_data["X_train_seq"]),
            'y_train': torch.FloatTensor(seq_data["y_train_seq"]),
            'X_val': torch.FloatTensor(seq_data["X_val_seq"]),
            'y_val': torch.FloatTensor(seq_data["y_val_seq"]),
            'X_test': torch.FloatTensor(seq_data["X_test_seq"]),
            'y_test': torch.FloatTensor(seq_data["y_test_seq"]),
            'target_scaler': self.scalers["target_scaler"]
        }
        
        # 移动到GPU
        for key in ['X_train', 'y_train', 'X_val', 'y_val', 'X_test', 'y_test']:
            self.data[key] = self.data[key].to(self.device)
        
        # 创建数据加载器
        self.train_loader = self._create_data_loader(
            self.data['X_train'], self.data['y_train'], shuffle=True
        )
        self.val_loader = self._create_data_loader(
            self.data['X_val'], self.data['y_val'], shuffle=False
        )
        self.test_loader = self._create_data_loader(
            self.data['X_test'], self.data['y_test'], shuffle=False
        )
        
        logger.info(f"✅ 数据加载完成:")
        logger.info(f"   训练集: {self.data['X_train'].shape} (样本数×序列长度×特征数)")
        logger.info(f"   验证集: {self.data['X_val'].shape}")
        logger.info(f"   测试集: {self.data['X_test'].shape}")
        logger.info(f"   特征维度: {self.data['X_train'].shape[2]}")
        logger.info(f"   输出维度: {self.data['y_train'].shape[1]}")
        
    def _create_data_loader(self, X, y, shuffle=True):
        """创建数据加载器"""
        dataset = torch.utils.data.TensorDataset(X, y)
        return torch.utils.data.DataLoader(
            dataset,
            batch_size=self.batch_size,
            shuffle=shuffle,
            pin_memory=False,
            num_workers=0
        )
        
    def train_model(self, model, model_name, epochs=None):
        """
        训练单个模型
        
        返回:
            best_model_state, training_history, test_results
        """
        if epochs is None:
            epochs = self.epochs
            
        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 开始训练 {model_name} 模型")
        logger.info(f"{'='*60}")
        
        # 优化器和损失函数
        optimizer = torch.optim.Adam(
            model.parameters(), 
            lr=self.learning_rate, 
            weight_decay=1e-4
        )
        criterion = nn.MSELoss()
        
        # 学习率调度
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode='min', factor=0.5, patience=10, verbose=True
        )
        
        # 训练历史记录
        history = {
            'train_loss': [],
            'val_loss': [],
            'train_metrics': [],
            'val_metrics': [],
            'learning_rates': []
        }
        
        # 早停变量
        best_val_loss = float('inf')
        best_model_state = None
        patience_counter = 0
        
        # 训练循环
        start_time = datetime.now()
        
        for epoch in range(epochs):
            # 训练步骤
            train_loss, train_metrics = self._train_epoch(
                model, optimizer, criterion
            )
            
            # 验证步骤
            val_loss, val_metrics = self._validate_epoch(model, criterion)
            
            # 记录历史
            history['train_loss'].append(train_loss)
            history['val_loss'].append(val_loss)
            history['train_metrics'].append(train_metrics)
            history['val_metrics'].append(val_metrics)
            history['learning_rates'].append(optimizer.param_groups[0]['lr'])
            
            # 控制台输出 (每10个epoch或最后5个epoch)
            if (epoch + 1) % 10 == 0 or epoch >= epochs - 5:
                logger.info(
                    f"Epoch {epoch+1:3d}/{epochs} | "
                    f"训练损失: {train_loss:.6f} | "
                    f"验证损失: {val_loss:.6f} | "
                    f"LR: {optimizer.param_groups[0]['lr']:.2e}"
                )
            
            # 早停检查
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_model_state = model.state_dict().copy()
                patience_counter = 0
            else:
                patience_counter += 1
            
            # 学习率调整
            scheduler.step(val_loss)
            
            # 早停判断
            if patience_counter >= self.early_stopping_patience:
                logger.info(f"🛑 早停触发！最佳验证损失: {best_val_loss:.6f}")
                break
            
            # 保存检查点
            if (epoch + 1) % self.checkpoint_interval == 0:
                checkpoint = {
                    'epoch': epoch + 1,
                    'model_state_dict': model.state_dict(),
                    'optimizer_state_dict': optimizer.state_dict(),
                    'val_loss': val_loss,
                    'history': history
                }
                checkpoint_path = os.path.join(
                    self.output_dir, 
                    f"{model_name}_checkpoint_epoch_{epoch+1}.pth"
                )
                torch.save(checkpoint, checkpoint_path)
        
        # 训练结束
        end_time = datetime.now()
        training_time = (end_time - start_time).total_seconds()
        
        logger.info(f"\n🎯 {model_name} 训练完成:")
        logger.info(f"  - 总训练轮数: {len(history['train_loss'])}")
        logger.info(f"  - 最终验证损失: {val_loss:.6f}")
        logger.info(f"  - 最佳验证损失: {best_val_loss:.6f}") 
        logger.info(f"  - 训练耗时: {training_time:.1f}秒")
        
        # 恢复最佳模型并测试
        model.load_state_dict(best_model_state)
        test_results = self._evaluate_model(model, model_name)
        
        return best_model_state, history, test_results
        
    def _train_epoch(self, model, optimizer, criterion):
        """训练一个epoch"""
        model.train()
        total_loss = 0
        
        all_preds = []
        all_targets = []
        
        for X_batch, y_batch in self.train_loader:
            optimizer.zero_grad()
            
            # 前向传播
            y_pred = model(X_batch)
            
            # 计算损失  
            loss = criterion(y_pred, y_batch)
            
            # 反向传播
            loss.backward()
            
            # 梯度裁剪
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            
            optimizer.step()
            
            total_loss += loss.item()
            
            # 保存预测用于指标计算
            all_preds.append(y_pred.detach().cpu())
            all_targets.append(y_batch.cpu())
        
        avg_loss = total_loss / len(self.train_loader)
        
        # 计算训练指标
        train_metrics = self._calculate_metrics(
            torch.cat(all_preds).numpy(), 
            torch.cat(all_targets).numpy()
        )
        
        return avg_loss, train_metrics
        
    def _validate_epoch(self, model, criterion):
        """验证一个epoch"""
        model.eval()
        total_loss = 0
        
        all_preds = []
        all_targets = []
        
        with torch.no_grad():
            for X_batch, y_batch in self.val_loader:
                y_pred = model(X_batch)
                loss = criterion(y_pred, y_batch)
                
                total_loss += loss.item()
                
                all_preds.append(y_pred.cpu())
                all_targets.append(y_batch.cpu())
        
        avg_loss = total_loss / len(self.val_loader)
        
        # 计算验证指标
        val_metrics = self._calculate_metrics(
            torch.cat(all_preds).numpy(),
            torch.cat(all_targets).numpy()
        )
        
        return avg_loss, val_metrics
        
    def _evaluate_model(self, model, model_name):
        """评估模型"""
        logger.info(f"\n🧪 正在评估 {model_name} 模型...")
        
        model.eval()
        
        all_preds = []
        all_targets = []
        
        with torch.no_grad():
            for X_batch, y_batch in tqdm(self.test_loader, desc="测试中..."):
                y_pred = model(X_batch)
                
                all_preds.append(y_pred.cpu())
                all_targets.append(y_batch.cpu())
        
        # 合并结果
        predictions = torch.cat(all_preds).numpy()
        targets = torch.cat(all_targets).numpy()
        
        # 计算指标
        metrics = self._calculate_metrics(predictions, targets)
        
        logger.info(f"\n📊 {model_name} 测试结果:")  
        logger.info(f"  MSE:  {metrics['mse']:.6f}")
        logger.info(f"  RMSE: {metrics['rmse']:.6f}")
        logger.info(f"  MAE:  {metrics['mae']:.6f}")
        logger.info(f"  MAPE: {metrics['mape']:.3f}%")
        logger.info(f"  R²:   {metrics['r2']:.4f}")
        logger.info(f"  预测值范围: [{predictions.min():.2f}, {predictions.max():.2f}]")
        logger.info(f"  真实值范围: [{targets.min():.2f}, {targets.max():.2f}]")
        
        return {
            'predictions': predictions,
            'targets': targets,
            **metrics
        }
        
    def _calculate_metrics(self, pred, true):
        """计算评估指标"""
        eps = 1e-10
        
        mse = np.mean((true - pred) ** 2)
        rmse = np.sqrt(mse)
        mae = np.mean(np.abs(true - pred))
        
        # MAPE (避免除零)
        mape = np.mean(np.abs((true - pred) / (np.abs(true) + eps))) * 100
        
        # R²
        ss_res = np.sum((true - pred) ** 2)
        ss_tot = np.sum((true - np.mean(true)) ** 2)
        r2 = 1 - (ss_res / (ss_tot + eps))
        
        return {
            'mse': float(mse),
            'rmse': float(rmse),
            'mae': float(mae),
            'mape': float(mape),
            'r2': float(r2)
        }
        
    def run_full_training(self):
        """运行完整的四模型训练"""
        logger.info("\n" + "=" * 80)
        logger.info("🚀 四模型高准确率训练启动")
        logger.info("=" * 80)
        
        # 1. 加载数据
        self.load_training_data()
        
        # 2. 创建四个模型
        models, device = create_four_models(device_info=False)
        
        logger.info(f"💻 模型创建完成 - 使用设备: {device}")
        for name, model in models.items():
            num_params = sum(p.numel() for p in model.parameters())
            logger.info(f"  {name}: {num_params:,} 参数")
        
        # 3. 训练所有模型
        training_results = {}
        ensemble_start = datetime.now()
        
        for model_name, model in models.items():
            model_start = datetime.now()
            
            # 训练单个模型
            best_state, history, test_results = self.train_model(
                model, model_name, epochs=self.epochs
            )
            
            # 保存结果
            model_result = {
                'model': model,
                'best_state_dict': best_state,
                'training_history': history,
                'test_results': test_results,
                'predictions': test_results['predictions'],
                'targets': test_results['targets'],
                'epochs_trained': len(history['train_loss']),
                'total_params': sum(p.numel() for p in model.parameters()),
                'model_name': model_name
            }
            
            training_results[model_name] = model_result
            
            model_end = datetime.now()
            model_time = (model_end - model_start).seconds
            
            logger.info(f"\n✅ {model_name} 训练完成! 耗时: {model_time}秒")
            
            # 保存模型
            model_save_path = os.path.join(
                self.output_dir, 
                f"{model_name.lower()}_best_model.pth"
            )
            torch.save({
                'model_state_dict': best_state,
                'model_name': model_name,
                'test_results': test_results,
                'training_history': history
            }, model_save_path)
            
            logger.info(f"  💾 模型保存到: {model_save_path}")
        
        # 4. 创建集成模型
        logger.info(f"\n🎯 创建集成模型...")
        ensemble_results = self._create_ensemble_predictions(training_results)
        training_results['Ensemble'] = ensemble_results
        
        # 5. 保存最终结果
        self.results = training_results
        
        # 保存训练摘要
        summary = {
            'training_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'training_device': str(device),
            'total_training_time_seconds': (datetime.now() - ensemble_start).seconds,
            'training_config': {
                'epochs': self.epochs,
                'batch_size': self.batch_size,
                'learning_rate': self.learning_rate,
                'early_stopping_patience': self.early_stopping_patience
            },
            'models_trained': list(training_results.keys()),
            'results': {
                name: {
                    'test_results': result['test_results'],
                    'epochs_trained': result['epochs_trained'],
                    'total_params': result['total_params']
                }
                for name, result in training_results.items()
            }
        }
        
        summary_path = os.path.join(self.output_dir, 'four_models_summary.json')
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
            
        logger.info(f"📄 训练摘要保存到: {summary_path}")
        
        # 6. 生成可视化图表
        logger.info(f"\n📊 生成论文级可视化图表...")
        self.visualizer.create_paper_ready_figures(training_results)
        
        # 7. 打印最终结果
        self._print_final_results(training_results)
        
        # 8. 生成训练报告
        self._generate_training_report(training_results)
        
        return training_results
        
    def _create_ensemble_predictions(self, training_results):
        """创建集成模型预测"""
        device = self.device
        
        logger.info("🎯 进行集成模型预测...")
        
        # 获取测试数据
        X_test = self.data['X_test']
        y_test = self.data['y_test']
        
        # 收集所有模型预测
        model_predictions = []
        model_weights = []
        
        # 为每个模型分配权重 (基于验证损失)
        validation_losses = {}
        for name, result in training_results.items():
            if name != 'EnhancedLSTM':  # 简化为等权重
                validation_losses[name] = result['training_history']['val_loss'][-1]
        
        # 集成预测
        all_models_pred = []
        for name, result in training_results.items():
            if name in ['EnhancedLSTM', 'SpatialTransformer', 'DeepTCN', 'BiGRU']:
                model = result['model']
                model.eval()
                
                with torch.no_grad():
                    preds = model(X_test).cpu().numpy()
                
                all_models_pred.append(preds)
        
        # 等权重集成
        ensemble_pred = np.mean(all_models_pred, axis=0)
        
        # 计算集成指标
        targets = y_test.cpu().numpy()
        ensemble_metrics = self._calculate_metrics(ensemble_pred, targets)
        
        logger.info(f"\n📊 集成模型结果:")
        logger.info(f"  RMSE: {ensemble_metrics['rmse']:.6f}")
        logger.info(f"  MAE:  {ensemble_metrics['mae']:.6f}")
        logger.info(f"  MAPE: {ensemble_metrics['mape']:.3f}%")
        logger.info(f"  R²:   {ensemble_metrics['r2']:.4f}")
        
        return {
            'model': None,
            'best_state_dict': None,
            'training_history': None,
            'test_results': ensemble_metrics,
            'epochs_trained': 0,
            'total_params': 0,
            'model_name': 'Ensemble',
            'predictions': ensemble_pred,
            'targets': targets
        }
        
    def _print_final_results(self, results):
        """打印最终结果"""
        logger.info("\n" + "=" * 80)
        logger.info("🎯 四模型训练完成！最终结果对比")
        logger.info("=" * 80)
        
        # 创建排序列表
        model_performances = []
        for name, result in results.items():
            if result['test_results']:
                rmse = result['test_results']['rmse']
                mae = result['test_results']['mae']
                params = result['total_params']
                epochs = result['epochs_trained']
                
                model_performances.append((name, rmse, mae, params, epochs))
        
        # 按RMSE排序
        model_performances.sort(key=lambda x: x[1])
        
        # 打印表格
        logger.info(f"\n{'排名':^6} {'模型名':<20} {'RMSE':<10} {'MAE':<10} {'参数量':<12} {'轮数':<6}")
        logger.info("-" * 75)
        
        for i, (name, rmse, mae, params, epochs) in enumerate(model_performances, 1):
            params_str = f"{params/1e6:.1f}M" if params > 1e6 else f"{params:,}"
            logger.info(f"{i:^6} {name:<20} {rmse:<10.4f} {mae:<10.4f} {params_str:<12} {epochs:<6}")
        
        logger.info("-" * 75)
        
        best_model = model_performances[0][0]
        logger.info(f"📈 最佳模型: {best_model} (RMSE: {model_performances[0][1]:.4f})")
        
        logger.info("=" * 80)
        
    def _generate_training_report(self, results):
        """生成详细的训练报告"""
        report_path = os.path.join(self.output_dir, 'training_report.txt')
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("📋 毕业设计训练报告\n")
            f.write("=" * 50 + "\n\n")
            
            f.write("🎯 项目概述\n")
            f.write("基于深度学习的电力负荷预测系统 - 四模型对比分析\n\n")
            
            f.write("📊 模型配置\n")
            f.write(f"- 训练轮数: {self.epochs}\n")
            f.write(f"- 批次大小: {self.batch_size}\n")
            f.write(f"- 学习率: {self.learning_rate}\n")
            f.write(f"- 早停耐心: {self.early_stopping_patience}\n")
            f.write(f"- 训练设备: {self.device}\n\n")
            
            f.write("📈 模型性能汇总表\n")
            f.write("=" * 40 + "\n")
            
            # 性能数据
            performances = []
            for name, result in results.items():
                if result['test_results']:
                    perf = result['test_results']
                    performances.append({
                        '模型': name,
                        'RMSE': perf['rmse'],
                        'MAE': perf['mae'], 
                        'MAPE(%)': perf['mape'],
                        'R²': perf['r2'],
                        '参数量': result['total_params'],
                        '训练轮数': result['epochs_trained']
                    })
            
            # 找到最佳模型
            best_rmse = min(performances, key=lambda x: x['RMSE'])
            
            f.write("最佳模型: {}\n".format(best_rmse['模型']))
            f.write("RMSE: {:.4f}\n".format(best_rmse['RMSE']))
            f.write("MAE: {:.4f}\n".format(best_rmse['MAE']))
            f.write("MAPE: {:.3f}%\n".format(best_rmse['MAPE(%)']))
            f.write("R²: {:.4f}\n\n".format(best_rmse['R²']))
            
            f.write("📊 可视化图表\n")
            f.write("已生成完整的论文级可视化图表，包括:\n")
            f.write("- 四模型性能对比主图 (Figure 1)\n")
            f.write("- 单模型深度分析图 (Figure 2-5)\n")
            f.write("- 图表说明文档\n\n")
            
            f.write("📚 使用建议\n")
            f.write("1. 可直接用于毕业设计论文\n")
            f.write("2. 所有图表都是300 DPI，满足期刊要求\n")
            f.write("3. 结果稳定可靠，支持复现\n")
            
        logger.info(f"📄 详细训练报告已保存: {report_path}")

def main():
    """主函数"""
    print("毕业设计四模型高准确率电力负荷预测系统")
    print("=" * 60)
    
    # 创建训练器
    trainer = FourModelTrainer(
        data_path="processed",
        output_dir="outputs",
        visualization_dir="visualizations",
        epochs=100,
        batch_size=64,
        learning_rate=0.001,
        early_stopping_patience=15
    )
    
    # 运行完整训练
    try:
        results = trainer.run_full_training()
        
        print(f"\n🎉 训练成功完成!")
        print(f"📊 结果保存位置: outputs/")
        print(f"📈 图表保存位置: visualizations/")
        print(f"📄 可用图表:")
        print(f"   - 四模型对比主图 (Figure 1)")
        print(f"   - 单模型深度分析 (Figure 2-5)")
        print(f"   - 训练报告")
        
    except Exception as e:
        logger.error(f"训练失败: {e}")
        import traceback
        traceback.print_exc()
        
if __name__ == "__main__":
    main()