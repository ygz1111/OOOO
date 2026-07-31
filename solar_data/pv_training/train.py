# -*- coding: utf-8 -*-
"""
PV 光伏预测 — 训练器 + 评估器 + 集成 + 主入口
完整训练流程: 数据加载 → 模型训练 → 集成 → 评估 → 可视化
支持 GPU/CPU 自动切换, GPU 启用混合精度加速
"""

import os
import sys
import json
import math
import time
import pickle
import logging
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from torch.amp import autocast, GradScaler
from datetime import datetime
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# 添加路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from config import (
    PROCESSED_DIR, MODEL_DIR, OUTPUT_DIR, LOG_DIR,
    MODEL_CONFIGS, TRAINING_CONFIG, METRICS, TORCH_THREADS,
    DEVICE, USE_CUDA, USE_AMP, print_device_info,
)
from models import create_all_models
from data_preparation import step1_preprocess, step2_build_sequences

# 设置 CPU 线程 (GPU 时也限制 CPU 线程用于数据加载)
torch.set_num_threads(TORCH_THREADS)

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(LOG_DIR, "training.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================================
# 训练器
# ============================================================================

class PVTrainer:
    """PV 预测模型训练器 (支持 GPU/CPU)"""
    
    def __init__(self, seq_data, training_config):
        self.config = training_config
        self.device = DEVICE
        
        # 加载数据并移动到设备
        # 注意: 训练数据较大时, GPU 内存可能不够, 使用 DataLoader 按批次加载
        self.X_train = torch.FloatTensor(seq_data["X_train"])
        self.y_train = torch.FloatTensor(seq_data["y_train"])
        self.X_val = torch.FloatTensor(seq_data["X_val"])
        self.y_val = torch.FloatTensor(seq_data["y_val"])
        self.X_test = torch.FloatTensor(seq_data["X_test"])
        self.y_test = torch.FloatTensor(seq_data["y_test"])
        self.y_test_orig = seq_data["y_test_orig"]
        self.test_cities = seq_data["test_cities"]
        
        logger.info(f"训练设备: {self.device}")
        if USE_CUDA:
            logger.info(f"  GPU: {torch.cuda.get_device_name(0)}")
            logger.info(f"  GPU 显存: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB")
        logger.info(f"训练集: {self.X_train.shape}")
        logger.info(f"验证集: {self.X_val.shape}")
        logger.info(f"测试集: {self.X_test.shape}")
        
        # DataLoader (pin_memory 加速 GPU 数据传输)
        self.train_loader = self._make_loader(self.X_train, self.y_train, shuffle=True)
        self.val_loader = self._make_loader(self.X_val, self.y_val, shuffle=False)
        self.test_loader = self._make_loader(self.X_test, self.y_test, shuffle=False)
        
        # 混合精度缩放器 (仅 GPU)
        self.scaler = GradScaler('cuda') if USE_AMP else None
        
        # 训练历史
        self.histories = {}
    
    def _make_loader(self, X, y, shuffle):
        dataset = TensorDataset(X, y)
        num_workers = self.config["num_workers"]
        # Windows 上多进程 DataLoader 容易崩溃, 设为 0
        if sys.platform == "win32" and not USE_CUDA:
            num_workers = 0
        return DataLoader(
            dataset,
            batch_size=self.config["batch_size"],
            shuffle=shuffle,
            num_workers=num_workers,
            drop_last=False,
            pin_memory=self.config["pin_memory"],
            persistent_workers=num_workers > 0,
        )
    
    def _get_criterion(self):
        if self.config["loss"] == "huber":
            return nn.HuberLoss(delta=1.0)
        elif self.config["loss"] == "mse":
            return nn.MSELoss()
        else:
            return nn.SmoothL1Loss()
    
    def _get_optimizer(self, model):
        return torch.optim.Adam(
            model.parameters(),
            lr=self.config["learning_rate"],
            weight_decay=self.config["weight_decay"],
        )
    
    def _get_scheduler(self, optimizer, epochs):
        """余弦退火 + 预热"""
        warmup = self.config["lr_warmup_epochs"]
        lr_min = self.config["lr_min"]
        
        def lr_lambda(epoch):
            if epoch < warmup:
                return (epoch + 1) / warmup
            else:
                progress = (epoch - warmup) / (epochs - warmup)
                return max(0.01, 0.5 * (1 + math.cos(math.pi * progress))) * \
                       (1 - lr_min / self.config["learning_rate"]) + lr_min / self.config["learning_rate"]
        
        return torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)
    
    def train_model(self, model, model_name):
        """训练单个模型"""
        
        logger.info(f"\n{'='*60}")
        logger.info(f"训练 {model_name}")
        logger.info(f"{'='*60}")
        
        model = model.to(self.device)
        optimizer = self._get_optimizer(model)
        criterion = self._get_criterion()
        scheduler = self._get_scheduler(optimizer, self.config["epochs"])
        
        best_val_loss = float("inf")
        best_state = None
        patience_counter = 0
        history = {"train_loss": [], "val_loss": [], "lr": []}
        
        start_time = time.time()
        
        for epoch in range(self.config["epochs"]):
            # === 训练阶段 ===
            model.train()
            train_loss = 0.0
            n_batches = 0
            
            for X_batch, y_batch in self.train_loader:
                # 移动到设备
                X_batch = X_batch.to(self.device, non_blocking=True)
                y_batch = y_batch.to(self.device, non_blocking=True)
                
                optimizer.zero_grad()
                
                if USE_AMP:
                    # 混合精度前向传播
                    with autocast('cuda'):
                        pred = model(X_batch)
                        loss = criterion(pred, y_batch)
                    
                    self.scaler.scale(loss).backward()
                    self.scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                    self.scaler.step(optimizer)
                    self.scaler.update()
                else:
                    # 普通前向传播 (CPU)
                    pred = model(X_batch)
                    loss = criterion(pred, y_batch)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                    optimizer.step()
                
                train_loss += loss.item()
                n_batches += 1
            
            train_loss /= n_batches
            
            # === 验证阶段 ===
            model.eval()
            val_loss = 0.0
            n_val = 0
            with torch.no_grad():
                for X_batch, y_batch in self.val_loader:
                    X_batch = X_batch.to(self.device, non_blocking=True)
                    y_batch = y_batch.to(self.device, non_blocking=True)
                    
                    if USE_AMP:
                        with autocast('cuda'):
                            pred = model(X_batch)
                            loss = criterion(pred, y_batch)
                    else:
                        pred = model(X_batch)
                        loss = criterion(pred, y_batch)
                    
                    val_loss += loss.item()
                    n_val += 1
            
            val_loss /= n_val
            scheduler.step()
            
            # 记录
            history["train_loss"].append(train_loss)
            history["val_loss"].append(val_loss)
            history["lr"].append(optimizer.param_groups[0]["lr"])
            
            # 日志
            if epoch % 5 == 0 or epoch == self.config["epochs"] - 1:
                elapsed = time.time() - start_time
                remaining = elapsed / (epoch + 1) * (self.config["epochs"] - epoch - 1)
                logger.info(f"  Epoch {epoch+1:3d}/{self.config['epochs']} | "
                           f"Train: {train_loss:.6f} | Val: {val_loss:.6f} | "
                           f"LR: {optimizer.param_groups[0]['lr']:.2e} | "
                           f"耗时: {elapsed:.0f}s | 剩余: ~{remaining:.0f}s")
                
                # GPU 显存监控
                if USE_CUDA:
                    mem_alloc = torch.cuda.memory_allocated() / 1024**3
                    mem_cached = torch.cuda.memory_reserved() / 1024**3
                    logger.info(f"    GPU 显存: 已用={mem_alloc:.2f}GB, 缓存={mem_cached:.2f}GB")
            
            # 早停
            if val_loss < best_val_loss - self.config["early_stopping_min_delta"]:
                best_val_loss = val_loss
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1
                
            if patience_counter >= self.config["early_stopping_patience"]:
                logger.info(f"  早停触发 (Epoch {epoch+1}), 最佳 Val Loss: {best_val_loss:.6f}")
                break
        
        elapsed = time.time() - start_time
        logger.info(f"  训练完成: {elapsed:.1f}s ({elapsed/60:.1f}min), 最佳 Val Loss: {best_val_loss:.6f}")
        
        # 恢复最佳模型
        if best_state is not None:
            model.load_state_dict(best_state)
        
        # 保存模型
        model_path = os.path.join(MODEL_DIR, f"{model_name.lower()}_best.pth")
        torch.save({
            "model_state_dict": model.state_dict(),
            "model_name": model_name,
            "best_val_loss": best_val_loss,
            "epochs_trained": epoch + 1,
            "training_time_sec": elapsed,
            "config": MODEL_CONFIGS[model_name],
            "device": str(self.device),
        }, model_path)
        logger.info(f"  模型保存: {model_path}")
        
        self.histories[model_name] = history
        return model, best_val_loss
    
    def predict(self, model, X=None):
        """模型预测"""
        model.eval()
        if X is None:
            loader = self.test_loader
        else:
            loader = self._make_loader(X, torch.zeros(len(X)), shuffle=False)
        
        preds = []
        with torch.no_grad():
            for X_batch, _ in loader:
                X_batch = X_batch.to(self.device, non_blocking=True)
                
                if USE_AMP:
                    with autocast('cuda'):
                        pred = model(X_batch)
                else:
                    pred = model(X_batch)
                
                preds.append(pred.cpu().numpy())
        
        return np.vstack(preds)


# ============================================================================
# 评估器
# ============================================================================

class PVEvaluator:
    """PV 预测评估器"""
    
    @staticmethod
    def calculate_metrics(y_true, y_pred):
        """计算评估指标"""
        y_true_flat = y_true.flatten()
        y_pred_flat = y_pred.flatten()
        
        mae = mean_absolute_error(y_true_flat, y_pred_flat)
        rmse = np.sqrt(mean_squared_error(y_true_flat, y_pred_flat))
        
        # MAPE (避免除零)
        mask = y_true_flat > 0.1  # 忽略夜间 0 值
        if mask.sum() > 0:
            mape = np.mean(np.abs((y_true_flat[mask] - y_pred_flat[mask]) / y_true_flat[mask])) * 100
        else:
            mape = 0
        
        r2 = r2_score(y_true_flat, y_pred_flat)
        max_ae = np.max(np.abs(y_true_flat - y_pred_flat))
        
        return {
            "MAE": float(mae),
            "RMSE": float(rmse),
            "MAPE": float(mape),
            "R2": float(r2),
            "MaxAE": float(max_ae),
        }
    
    @staticmethod
    def calculate_daytime_metrics(y_true, y_pred, ghi_test=None):
        """计算白天/夜间分别指标"""
        # 如果没有 GHI, 用 y_true > 0 近似白天
        if ghi_test is not None:
            daytime_mask = ghi_test > 0
        else:
            daytime_mask = y_true > 0.01
        
        night_mask = ~daytime_mask
        
        result = {}
        if daytime_mask.sum() > 0:
            result["daytime"] = PVEvaluator.calculate_metrics(
                y_true[daytime_mask], y_pred[daytime_mask]
            )
        if night_mask.sum() > 0:
            result["nighttime"] = PVEvaluator.calculate_metrics(
                y_true[night_mask], y_pred[night_mask]
            )
        
        return result
    
    @staticmethod
    def calculate_peak_metrics(y_true, y_pred, percentile=95):
        """峰值时段指标"""
        threshold = np.percentile(y_true, percentile)
        peak_mask = y_true >= threshold
        
        if peak_mask.sum() == 0:
            return {"peak_count": 0}
        
        return {
            "peak_count": int(peak_mask.sum()),
            "peak_mape": float(np.mean(np.abs((y_true[peak_mask] - y_pred[peak_mask]) / y_true[peak_mask])) * 100),
            "peak_mae": float(np.mean(np.abs(y_true[peak_mask] - y_pred[peak_mask]))),
        }
    
    @staticmethod
    def calculate_city_metrics(y_true, y_pred, cities):
        """分城市指标"""
        result = {}
        for city in sorted(set(cities)):
            mask = np.array([c == city for c in cities])
            if mask.sum() > 0:
                result[city] = PVEvaluator.calculate_metrics(y_true[mask], y_pred[mask])
        return result
    
    @staticmethod
    def print_report(metrics, model_name):
        """打印评估报告"""
        print(f"\n{'='*50}")
        print(f"{model_name} 评估报告")
        print(f"{'='*50}")
        print(f"  MAPE:  {metrics['MAPE']:.2f}%")
        print(f"  RMSE:  {metrics['RMSE']:.2f} kW")
        print(f"  MAE:   {metrics['MAE']:.2f} kW")
        print(f"  R²:    {metrics['R2']:.4f}")
        print(f"  MaxAE: {metrics['MaxAE']:.2f} kW")
        print(f"{'='*50}")


# ============================================================================
# 集成
# ============================================================================

class EnsembleModel:
    """加权平均集成"""
    
    def __init__(self, models, weights=None):
        self.models = models
        self.device = DEVICE
        if weights is not None:
            self.weights = np.array(weights) / np.sum(weights)
        else:
            self.weights = np.ones(len(models)) / len(models)
    
    def predict(self, X):
        preds = []
        for model in self.models:
            model.eval()
            with torch.no_grad():
                # 分批处理 (避免 GPU 内存不足)
                batch_size = 512
                pred_list = []
                for i in range(0, len(X), batch_size):
                    X_batch = X[i:i+batch_size].to(self.device, non_blocking=True)
                    if USE_AMP:
                        with autocast('cuda'):
                            pred = model(X_batch)
                    else:
                        pred = model(X_batch)
                    pred_list.append(pred.cpu().numpy())
                preds.append(np.vstack(pred_list))
        
        ensemble = np.zeros_like(preds[0])
        for pred, w in zip(preds, self.weights):
            ensemble += pred * w
        
        return ensemble


# ============================================================================
# 主训练流程
# ============================================================================

def main():
    print("=" * 70)
    print("PV 光伏功率预测 — 模型训练")
    print("=" * 70)
    
    # 打印设备信息
    print("\n[0] 设备信息:")
    print_device_info()
    
    print(f"\n  PyTorch: {torch.__version__}")
    
    # Step 1-2: 数据预处理
    print("\n[1] 数据预处理...")
    df = step1_preprocess()
    seq_data = step2_build_sequences()
    
    # Step 3: 创建模型
    print(f"\n[2] 创建模型 ({'GPU 大模型' if USE_CUDA else 'CPU 轻量模型'})...")
    models = create_all_models(MODEL_CONFIGS)
    
    # Step 4: 训练
    print(f"\n[3] 开始训练 (4模型)...")
    trainer = PVTrainer(seq_data, TRAINING_CONFIG)
    
    trained_models = {}
    val_losses = []
    
    for name in ["LSTM", "BiGRU", "TCN", "Transformer"]:
        model, val_loss = trainer.train_model(models[name], name)
        trained_models[name] = model
        val_losses.append(val_loss)
    
    # Step 5: 集成
    print(f"\n[4] 集成权重优化...")
    val_losses_arr = np.array(val_losses)
    weights = np.exp(-val_losses_arr * 10)  # 损失越小权重越大
    weights = weights / weights.sum()
    
    for name, w, vl in zip(trained_models.keys(), weights, val_losses):
        logger.info(f"  {name}: 权重={w:.4f} (val_loss={vl:.6f})")
    
    ensemble = EnsembleModel(list(trained_models.values()), weights)
    
    # 保存权重
    weights_path = os.path.join(MODEL_DIR, "ensemble_weights.pkl")
    with open(weights_path, "wb") as f:
        pickle.dump({"weights": weights, "model_names": list(trained_models.keys())}, f)
    
    # Step 6: 测试集评估
    print(f"\n[5] 测试集评估...")
    y_test = seq_data["y_test_orig"]  # 原始 kW 值
    test_cities = seq_data["test_cities"]
    
    results = {}
    
    # 加载 scaler
    with open(os.path.join(PROCESSED_DIR, "pv_scalers.pkl"), "rb") as f:
        scalers = pickle.load(f)
    
    for name, model in trained_models.items():
        pred_norm = trainer.predict(model)
        # 反归一化
        pred = scalers["target_scaler"].inverse_transform(pred_norm.reshape(-1, 1)).reshape(pred_norm.shape)
        pred = np.maximum(pred, 0)  # 物理约束: 不为负
        
        metrics = PVEvaluator.calculate_metrics(y_test, pred)
        PVEvaluator.print_report(metrics, name)
        results[name] = {"metrics": metrics, "predictions": pred}
    
    # 集成评估
    ensemble_pred_norm = ensemble.predict(trainer.X_test)
    ensemble_pred = scalers["target_scaler"].inverse_transform(
        ensemble_pred_norm.reshape(-1, 1)
    ).reshape(ensemble_pred_norm.shape)
    ensemble_pred = np.maximum(ensemble_pred, 0)
    
    ensemble_metrics = PVEvaluator.calculate_metrics(y_test, ensemble_pred)
    PVEvaluator.print_report(ensemble_metrics, "Ensemble")
    results["Ensemble"] = {"metrics": ensemble_metrics, "predictions": ensemble_pred}
    
    # 分时段评估
    print(f"\n[6] 分时段评估 (Ensemble)...")
    daytime_metrics = PVEvaluator.calculate_daytime_metrics(y_test, ensemble_pred)
    if "daytime" in daytime_metrics:
        print(f"  白天 MAPE: {daytime_metrics['daytime']['MAPE']:.2f}%")
    if "nighttime" in daytime_metrics:
        print(f"  夜间 MAPE: {daytime_metrics['nighttime']['MAPE']:.2f}%")
    
    # 峰值评估
    peak_metrics = PVEvaluator.calculate_peak_metrics(y_test, ensemble_pred, percentile=95)
    print(f"  峰值 MAPE: {peak_metrics.get('peak_mape', 0):.2f}%")
    
    # 分城市评估
    print(f"\n[7] 分城市评估 (Ensemble)...")
    city_metrics = PVEvaluator.calculate_city_metrics(y_test, ensemble_pred, test_cities)
    for city, m in city_metrics.items():
        print(f"  {city:12s}: MAPE={m['MAPE']:.2f}%, RMSE={m['RMSE']:.2f} kW, R²={m['R2']:.4f}")
    
    # Step 7: 保存结果
    print(f"\n[8] 保存结果...")
    
    # 训练历史
    history_path = os.path.join(OUTPUT_DIR, "training_history.json")
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump({
            "models": {name: h for name, h in trainer.histories.items()},
            "ensemble_weights": {name: float(w) for name, w in zip(trained_models.keys(), weights)},
        }, f, indent=2)
    
    # 评估报告
    report = {
        "training_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "device": str(DEVICE),
        "gpu_name": torch.cuda.get_device_name(0) if USE_CUDA else "N/A",
        "torch_version": torch.__version__,
        "torch_threads": TORCH_THREADS,
        "use_amp": USE_AMP,
        "data_shapes": {
            "train": list(seq_data["X_train"].shape),
            "val": list(seq_data["X_val"].shape),
            "test": list(seq_data["X_test"].shape),
        },
        "training_config": TRAINING_CONFIG,
        "model_configs": MODEL_CONFIGS,
        "results": {
            name: {"metrics": r["metrics"]}
            for name, r in results.items()
        },
        "ensemble_weights": {name: float(w) for name, w in zip(trained_models.keys(), weights)},
        "daytime_metrics": daytime_metrics,
        "peak_metrics": peak_metrics,
        "city_metrics": city_metrics,
    }
    
    report_path = os.path.join(OUTPUT_DIR, "evaluation_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logger.info(f"训练历史: {history_path}")
    logger.info(f"评估报告: {report_path}")
    
    # 最终汇总
    print(f"\n{'='*70}")
    print("训练完成! 最终结果:")
    print(f"{'='*70}")
    print(f"{'模型':>12s} {'MAPE':>8s} {'RMSE':>8s} {'MAE':>8s} {'R²':>6s}")
    for name, r in results.items():
        m = r["metrics"]
        print(f"{name:>12s} {m['MAPE']:8.2f}% {m['RMSE']:8.2f} {m['MAE']:8.2f} {m['R2']:6.4f}")
    
    print(f"\n模型保存: {MODEL_DIR}")
    print(f"结果保存: {OUTPUT_DIR}")
    print(f"日志保存: {LOG_DIR}")
    print(f"{'='*70}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    main()
