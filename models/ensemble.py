"""
集成模型和评估器
集成策略：加权平均 / 简单平均
"""

import numpy as np
from sklearn.metrics import mean_absolute_percentage_error, mean_squared_error, mean_absolute_error, r2_score


class EnsembleModel:
    """集成模型类：加权平均多个模型的预测结果"""

    def __init__(self, models, weights=None, name="ensemble"):
        """
        Args:
            models: 模型列表 [model1, model2, model3]
            weights: 权重列表 [w1, w2, w3]（None 时使用简单平均）
            name: 模型名称
        """
        self.name = name
        self.models = models
        self.weights = weights

        if weights is not None:
            # 归一化权重
            self.weights = np.array(weights) / np.sum(weights)
            assert len(self.weights) == len(models), "权重数量与模型数量不匹配"
        else:
            self.weights = np.ones(len(models)) / len(models)

    def predict(self, X):
        """
        集成预测

        Args:
            X: 输入特征 (n_samples, lookback, n_features)

        Returns:
            numpy.ndarray: 加权平均预测结果 (n_samples, horizon)
        """
        predictions = []
        for model in self.models:
            pred = model.predict(X)
            predictions.append(pred)

        # 加权平均
        weighted_pred = np.zeros_like(predictions[0])
        for i, pred in enumerate(predictions):
            weighted_pred += self.weights[i] * pred

        return weighted_pred

    def save(self, filepath):
        """保存集成模型（保存各子模型）"""
        # 集成模型不单独保存，而是保存子模型
        for i, model in enumerate(self.models):
            model.save(f"{filepath}_model{i}.h5")

    def load(self, filepath):
        """加载集成模型"""
        for i, model in enumerate(self.models):
            model.load(f"{filepath}_model{i}.h5")
        return self.models


class EnsembleModelFactory:
    """集成模型工厂：自动训练多个模型并创建集成"""

    @staticmethod
    def train_all_ensemble(X_train, y_train, X_val, y_val, 
                            lstm_config, transformer_config, tcn_config,
                            training_config, output_dir):
        """
        训练全部模型并返回集成模型

        Args:
            X_train, y_train: 训练数据
            X_val, y_val: 验证数据
            lstm_config: LSTM 配置
            transformer_config: Transformer 配置
            tcn_config: TCN 配置
            training_config: 训练配置
            output_dir: 输出目录

        Returns:
            tuple: (ensemble_model, histories, best_weights)
        """
        from lstm_model import LSTMModel
        from transformer_model import TransformerModel
        from tcn_model import TCNModel

        lookback, n_features = X_train.shape[1:]
        horizon = y_train.shape[1]

        models = []
        histories = {}
        val_losses = []

        # 1. 训练 LSTM
        print("\n" + "=" * 60)
        print("训练 LSTM 模型...")
        print("=" * 60)
        lstm_model = LSTMModel(
            input_shape=(lookback, n_features),
            output_dim=horizon,
            config=lstm_config
        )
        lstm_model.build()
        lstm_model.compile(learning_rate=training_config["learning_rate"])
        lstm_checkpoint = f"{output_dir}/lstm_best.h5"
        histories["lstm"] = lstm_model.train(
            X_train, y_train, X_val, y_val,
            epochs=training_config["epochs"],
            batch_size=training_config["batch_size"],
            checkpoint_path=lstm_checkpoint
        )
        models.append(lstm_model)
        val_losses.append(min(histories["lstm"].history["val_loss"]))

        # 2. 训练 Transformer
        print("\n" + "=" * 60)
        print("训练 Transformer 模型...")
        print("=" * 60)
        transformer_model = TransformerModel(
            input_shape=(lookback, n_features),
            output_dim=horizon,
            config=transformer_config
        )
        transformer_model.build()
        transformer_model.compile(learning_rate=training_config["learning_rate"])
        transformer_checkpoint = f"{output_dir}/transformer_best.h5"
        histories["transformer"] = transformer_model.train(
            X_train, y_train, X_val, y_val,
            epochs=training_config["epochs"],
            batch_size=training_config["batch_size"],
            checkpoint_path=transformer_checkpoint
        )
        models.append(transformer_model)
        val_losses.append(min(histories["transformer"].history["val_loss"]))

        # 3. 训练 TCN
        print("\n" + "=" * 60)
        print("训练 TCN 模型...")
        print("=" * 60)
        tcn_model = TCNModel(
            input_shape=(lookback, n_features),
            output_dim=horizon,
            config=tcn_config
        )
        tcn_model.build()
        tcn_model.compile(learning_rate=training_config["learning_rate"])
        tcn_checkpoint = f"{output_dir}/tcn_best.h5"
        histories["tcn"] = tcn_model.train(
            X_train, y_train, X_val, y_val,
            epochs=training_config["epochs"],
            batch_size=training_config["batch_size"],
            checkpoint_path=tcn_checkpoint
        )
        models.append(tcn_model)
        val_losses.append(min(histories["tcn"].history["val_loss"]))

        # 计算权重（基于验证损失，损失越小权重越大）
        val_losses = np.array(val_losses)
        # 使用负指数，损失越小权重越大
        weights = np.exp(-val_losses)
        weights = weights / np.sum(weights)

        print("\n" + "=" * 60)
        print("集成模型权重")
        print("=" * 60)
        for i, (name, weight) in enumerate(zip(["LSTM", "Transformer", "TCN"], weights)):
            print(f"  {name}: {weight:.4f} (val_loss: {val_losses[i]:.4f})")

        # 创建集成模型
        ensemble = EnsembleModel(models, weights=weights, name="weighted_ensemble")

        return ensemble, histories, weights


class Evaluator:
    """评估器：计算各种评估指标"""

    @staticmethod
    def calculate_metrics(y_true, y_pred):
        """
        计算评估指标

        Args:
            y_true: 真实值 (n_samples, horizon)
            y_pred: 预测值 (n_samples, horizon)

        Returns:
            dict: 指标字典
        """
        # 展平为一维
        y_true_flat = y_true.flatten()
        y_pred_flat = y_pred.flatten()

        mae = mean_absolute_error(y_true_flat, y_pred_flat)
        rmse = np.sqrt(mean_squared_error(y_true_flat, y_pred_flat))
        
        # MAPE：避免除以零，加小常数
        mape = np.mean(np.abs((y_true_flat - y_pred_flat) / (y_true_flat + 1e-6))) * 100

        r2 = r2_score(y_true_flat, y_pred_flat)

        # 最大绝对误差
        max_ae = np.max(np.abs(y_true_flat - y_pred_flat))

        return {
            "MAE": mae,
            "RMSE": rmse,
            "MAPE": mape,
            "R2": r2,
            "MaxAE": max_ae,
        }

    @staticmethod
    def calculate_hourly_metrics(y_true, y_pred):
        """
        计算每个预测步长的指标

        Args:
            y_true: (n_samples, horizon)
            y_pred: (n_samples, horizon)

        Returns:
            list: 每小时的指标
        """
        n_hours = y_true.shape[1]
        hourly_metrics = []

        for i in range(n_hours):
            hourly_true = y_true[:, i]
            hourly_pred = y_pred[:, i]
            metrics = Evaluator.calculate_metrics(hourly_true, hourly_pred)
            metrics["Hour"] = i + 1  # 第几小时
            hourly_metrics.append(metrics)

        return hourly_metrics

    @staticmethod
    def calculate_peak_metrics(y_true, y_pred, scaler, percentile=95):
        """
        计算峰值时段的预测精度

        Args:
            y_true: 真实值
            y_pred: 预测值
            scaler: 目标Scaler（反归一化）
            percentile: 峰值百分位

        Returns:
            dict: 峰值指标
        """
        # 反归一化
        y_true_orig = scaler.inverse_transform(y_true)
        y_pred_orig = scaler.inverse_transform(y_pred)

        # 找到峰值（真实值）
        peak_threshold = np.percentile(y_true_orig.flatten(), percentile)
        peak_mask = y_true_orig.flatten() >= peak_threshold

        if peak_mask.sum() == 0:
            return {"peak_count": 0, "peak_mape": 0, "peak_mape": 0}

        peak_true = y_true_orig.flatten()[peak_mask]
        peak_pred = y_pred_orig.flatten()[peak_mask]

        peak_mape = np.mean(np.abs((peak_true - peak_pred) / peak_true)) * 100
        peak_mae = np.mean(np.abs(peak_true - peak_pred))

        return {
            "peak_threshold": peak_threshold,
            "peak_count": peak_mask.sum(),
            "peak_mape": peak_mape,
            "peak_mae": peak_mae,
        }

    @staticmethod
    def print_evaluation_report(metrics, model_name):
        """打印评估报告"""
        print("\n" + "=" * 60)
        print(f"{model_name} - 评估报告")
        print("=" * 60)
        print(f"  MAE:   {metrics['MAE']:.2f} MW")
        print(f"  RMSE:  {metrics['RMSE']:.2f} MW")
        print(f"  MAPE:  {metrics['MAPE']:.2f}%")
        print(f"  R²:    {metrics['R2']:.4f}")
        print(f"  MaxAE: {metrics['MaxAE']:.2f} MW")
        print("=" * 60)