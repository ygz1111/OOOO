# ==========================================================================
# PyTorch GPU训练器 - 智能电网负荷预测
# ==========================================================================

import os
import pickle
import torch
import torch.nn as nn
import numpy as np
from datetime import datetime
import logging
from tqdm import tqdm
import json

# 设置日志格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # 控制台输出
    ]
)
logger = logging.getLogger(__name__)

class PyTorchGPUTrainer:
    """
    PyTorch GPU训练执行器
    """
    
    def __init__(self, 
                 data_path="processed", 
                 output_path="outputs",
                 epochs=50,
                 batch_size=32,
                 learning_rate=1e-3,
                 early_stopping_patience=8):
        """
        初始化训练器
        
        Args:
            data_path: 数据路径
            output_path: 输出路径
            epochs: 训练轮数
            batch_size: 批次大小
            learning_rate: 学习率
            early_stopping_patience: 早停耐心值
        """
        self.data_path = data_path
        self.output_path = output_path
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.early_stopping_patience = early_stopping_patience
        
        # 设备检测
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # 确保输出目录存在
        os.makedirs(output_path, exist_ok=True)
        
        logger.info("=" * 60)
        logger.info("🚀 PyTorch GPU训练器初始化")
        logger.info("=" * 60)
        
        logger.info(f"📁 数据路径: {data_path}")
        logger.info(f"📤 输出路径: {output_path}")
        logger.info(f"💻 训练设备: {self.device}")
        
        if torch.cuda.is_available():
            logger.info(f"🎯 GPU: {torch.cuda.get_device_name()}")
            logger.info(f"💽 GPU显存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f}GB")
        
        logger.info(f"📊 批次大小: {batch_size}")
        logger.info(f"⏰ 训练轮数: {epochs}")
        logger.info(f"📈 学习率: {learning_rate}")
        logger.info(f"🎯 早停耐心: {early_stopping_patience}")
        logger.info("=" * 60)
        
        # 加载数据
        self.load_data()
        
    def load_data(self):
        """加载训练数据"""
        logger.info("📥 开始加载训练数据...")
        
        # 加载序列数据
        with open(os.path.join(self.data_path, "step6_sequences.pkl"), "rb") as f:
            seq_data = pickle.load(f)
            
        with open(os.path.join(self.data_path, "step5_scalers.pkl"), "rb") as f:
            self.scalers = pickle.load(f)
            
        # 准备训练数据
        self.X_train = torch.FloatTensor(seq_data["X_train_seq"])
        self.y_train = torch.FloatTensor(seq_data["y_train_seq"])
        self.X_val = torch.FloatTensor(seq_data["X_val_seq"])
        self.y_val = torch.FloatTensor(seq_data["y_val_seq"])
        self.X_test = torch.FloatTensor(seq_data["X_test_seq"])
        self.y_test = torch.FloatTensor(seq_data["y_test_seq"])
        
        self.target_scaler = self.scalers["target_scaler"]
        
        # 移动到GPU
        self.X_train = self.X_train.to(self.device)
        self.y_train = self.y_train.to(self.device)
        self.X_val = self.X_val.to(self.device) 
        self.y_val = self.y_val.to(self.device)
        self.X_test = self.X_test.to(self.device)
        self.y_test = self.y_test.to(self.device)
        
        logger.info(f"✅ 数据加载完成:")
        logger.info(f"  训练集: {self.X_train.shape}")
        logger.info(f"  验证集: {self.X_val.shape}")
        logger.info(f"  测试集: {self.X_test.shape}")
        logger.info(f"  特征数: {self.X_train.shape[2]}")
        logger.info(f"  输出维度: {self.y_train.shape[1]}")
        
    def create_data_loader(self, X, y, shuffle=True):
        """创建数据加载器"""
        dataset = torch.utils.data.TensorDataset(X, y)
        return torch.utils.data.DataLoader(
            dataset,
            batch_size=self.batch_size,
            shuffle=shuffle,
            pin_memory=torch.cuda.is_available()
        )
        
    def train_epoch(self, model, train_loader, optimizer, criterion):
        """训练一个epoch"""
        model.train()
        epoch_loss = 0
        
        for X_batch, y_batch in train_loader:
            optimizer.zero_grad()
            
            # 前向传播
            y_pred = model(X_batch)
            
            # 计算损失
            loss = criterion(y_pred, y_batch)
            
            # 反向传播
            loss.backward()
            optimizer.step()
            
            epoch_loss += loss.item()
        
        return epoch_loss / len(train_loader)
        
    def validate(self, model, val_loader, criterion):
        """验证模型"""
        model.eval()
        val_loss = 0
        
        with torch.no_grad():
            for X_batch, y_batch in val_loader:
                # 前向传播
                y_pred = model(X_batch)
                
                # 计算损失
                loss = criterion(y_pred, y_batch)
                val_loss += loss.item()
        
        return val_loss / len(val_loader)
        
    def test_model(self, model, criterion):
        """测试模型"""
        model.eval()
        test_loader = self.create_data_loader(self.X_test, self.y_test, shuffle=False)
        
        all_preds = []
        all_targets = []
        
        with torch.no_grad():
            for X_batch, y_batch in tqdm(test_loader, desc="测试中..."):
                preds = model(X_batch)
                
                all_preds.append(preds.cpu().numpy())
                all_targets.append(y_batch.cpu().numpy())
        
        # 合并结果
        predictions = np.vstack(all_preds)
        targets = np.vstack(all_targets)
        
        # 计算指标
        mse = np.mean((targets - predictions) ** 2)
        rmse = np.sqrt(mse)
        mae = np.mean(np.abs(targets - predictions))
        
        return {
            'mse': float(mse),
            'rmse': float(rmse),
            'mae': float(mae),
            'predictions': predictions,
            'targets': targets
        }
        
    def train_single_model(self, model, model_name):
        """训练单个模型"""
        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 开始训练 {model_name} (PyTorch)")
        logger.info(f"{'='*60}")
        
        # 创建数据加载器
        train_loader = self.create_data_loader(self.X_train, self.y_train, shuffle=True)
        val_loader = self.create_data_loader(self.X_val, self.y_val, shuffle=False)
        
        # 配置优化器和损失函数
        optimizer = torch.optim.Adam(
            model.parameters(), 
            lr=self.learning_rate, 
            weight_decay=1e-4
        )
        criterion = nn.MSELoss()
        
        # 早停设置
        best_val_loss = float('inf')
        best_model_state = None
        patience_counter = 0
        
        # 训练循环
        for epoch in range(self.epochs):
            # 训练
            train_loss = self.train_epoch(model, train_loader, optimizer, criterion)
            
            # 验证
            val_loss = self.validate(model, val_loader, criterion)
            
            # 记录训练日志
            if epoch % 5 == 0 or epoch == self.epochs - 1:
                logger.info(f"\n📊 Epoch {epoch+1:2d}/{self.epochs}")
                logger.info(f"  训练损失: {train_loss:.6f}")
                logger.info(f"  验证损失: {val_loss:.6f}")
            
            # 早停检查
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_model_state = model.state_dict().copy()
                patience_counter = 0
            else:
                patience_counter += 1
            
            if patience_counter >= self.early_stopping_patience:
                logger.info(f"\n🛑 早停触发! 最佳验证损失: {best_val_loss:.6f}")
                break
        
        # 恢复最佳模型
        model.load_state_dict(best_model_state)
        
        # 测试评估
        logger.info(f"\n🧪 测试评估: {model_name}")
        test_results = self.test_model(model, criterion)
        
        logger.info(f"  MSE:  {test_results['mse']:.6f}")
        logger.info(f"  RMSE: {test_results['rmse']:.6f}")
        logger.info(f"  MAE:  {test_results['mae']:.6f}")
        
        # 保存模型
        model_save_path = os.path.join(self.output_path, f"{model_name.lower()}_best_model.pth")
        torch.save({
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'best_val_loss': best_val_loss,
            'test_results': test_results,
        }, model_save_path)
        
        logger.info(f"✅ 模型保存到: {model_save_path}")
        
        # 返回结果
        return {
            'model_name': model_name,
            'best_val_loss': best_val_loss,
            'test_results': test_results,
            'model_path': model_save_path,
            'epochs_trained': epoch + 1,
            'total_params': sum(p.numel() for p in model.parameters()),
        }
        
    def create_ensemble_predictions(self, models_dict):
        """创建集成预测"""
        logger.info(f"\n🎯 创建集成预测...")
        
        model_predictions = []
        model_weights = [1.0, 1.0, 1.0]  # 等权重
        
        for model_name, model in models_dict.items():
            logger.info(f"  获取 {model_name} 预测...")
            
            model.eval()
            with torch.no_grad():
                preds = model(self.X_test).cpu().numpy()
            
            model_predictions.append(preds)
        
        # 加权平均
        ensemble_pred = np.zeros_like(model_predictions[0])
        for pred, weight in zip(model_predictions, model_weights):
            ensemble_pred += pred * weight
        
        ensemble_pred /= sum(model_weights)
        
        # 计算集成指标
        targets = self.y_test.cpu().numpy()
        mse = np.mean((targets - ensemble_pred) ** 2)
        rmse = np.sqrt(mse)
        mae = np.mean(np.abs(targets - ensemble_pred))
        
        logger.info(f"  集成结果 - MSE: {mse:.6f}, RMSE: {rmse:.6f}, MAE: {mae:.6f}")
        
        return {
            'ensemble_predictions': ensemble_pred,
            'mse': float(mse),
            'rmse': float(rmse),
            'mae': float(mae),
        }
        
    def run_full_training(self):
        """运行完整的多模型训练"""
        logger.info("\n" + "=" * 60)
        logger.info("🚀 开始PyTorch GPU训练流程")
        logger.info("=" * 60)
        
        # 导入模型
        from .pytorch_lstm import create_pytorch_models
        
        # 创建模型
        models, device = create_pytorch_models(device_info=False)
        models = {k: v.to(self.device) for k, v in models.items()}  
        
        logger.info(f"💻 模型已在 {device} 上创建")
        for name, model in models.items():
            num_params = sum(p.numel() for p in model.parameters())
            logger.info(f"  {name}: {num_params:,} 参数")
        
        # 训练所有模型
        results = {}
        training_start = datetime.now()
        
        for model_name, model in models.items():
            model_start = datetime.now()
            
            result = self.train_single_model(model, model_name)
            results[model_name] = result
            
            model_end = datetime.now()
            logger.info(f"\n✅ {model_name} 训练耗时: {(model_end - model_start).seconds}秒")
            
        training_end = datetime.now()
        total_time = (training_end - training_start).seconds
        
        # 集成预测
        logger.info(f"\n🎉 个体模型训练完成! (总耗时: {total_time}秒)")
        
        ensemble_results = self.create_ensemble_predictions(models)
        results['Ensemble'] = {
            'model_name': 'Ensemble',
            'test_results': ensemble_results,
            'model_path': None,
            'epochs_trained': 0,
            'total_params': 0,
        }
        
        # 保存训练摘要
        summary = {
            'training_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'training_device': str(self.device),
            'total_training_time_seconds': total_time,
            'training_config': {
                'epochs': self.epochs,
                'batch_size': self.batch_size,
                'learning_rate': self.learning_rate,
                'early_stopping_patience': self.early_stopping_patience,
            },
            'models_trained': list(results.keys()),
            'results': results
        }
        
        summary_path = os.path.join(self.output_path, 'training_summary.json')
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
            
        logger.info(f"📄 训练摘要保存到: {summary_path}")
        
        # 打印最终结果
        logger.info("\n" + "=" * 60)
        logger.info("🎯 训练完成! 最终结果:")
        logger.info("=" * 60)
        
        for model_name, result in results.items():
            if model_name == 'Ensemble':
                print(f"  {model_name:12} - RMSE: {result['test_results']['rmse']:.4f} | MAE: {result['test_results']['mae']:.4f} (Ensemble)")
            else:
                print(f"  {model_name:12} - RMSE: {result['test_results']['rmse']:.4f} | MAE: {result['test_results']['mae']:.4f} | Epochs: {result['epochs_trained']}")
        
        logger.info(f"\n🎉 总训练时间: {total_time//60}分{total_time%60}秒")
        logger.info("=" * 60)
        
        return results

def create_outputs_directory():
    """创建输出目录"""
    output_dir = "outputs"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logger.info(f"📁 创建输出目录: {output_dir}")
    return output_dir

if __name__ == "__main__":
    """独立运行训练"""
    logger.info("🎯 独立运行PyTorch GPU训练")
    
    # 创建输出目录
    output_dir = create_outputs_directory()
    
    # 初始化训练器
    trainer = PyTorchGPUTrainer(
        data_path="processed",
        output_path=output_dir,
        epochs=50,
        batch_size=32,
        learning_rate=1e-3
    )
    
    # 运行训练
    results = trainer.run_full_training()
    
    print(f"\n🚀 训练完成! 结果保存在: {output_dir}/")
    print(f"📊 可以使用 visualization.ipynb 分析结果")