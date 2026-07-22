"""
LSTM 负荷预测模型
长短期记忆网络，适合捕捉时间序列的中长期依赖
"""

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers, models, regularizers, callbacks
import numpy as np


def build_lstm_model(input_shape, output_dim, config):
    """
    构建 LSTM 预测模型

    Args:
        input_shape: (lookback, n_features)
        output_dim: horizon (预测步长)
        config: LSTM_CONFIG 配置字典

    Returns:
        keras.Model: LSTM 模型
    """
    units = config.get("units", [128, 64])
    dropout = config.get("dropout", 0.2)
    l2_reg = config.get("l2_reg", 1e-5)

    model = models.Sequential([
        # 输入层
        layers.Input(shape=input_shape, name="input"),

        # 第一层 LSTM
        layers.Bidirectional(
            layers.LSTM(
                units[0],
                return_sequences=True,
                kernel_regularizer=regularizers.l2(l2_reg),
                recurrent_regularizer=regularizers.l2(l2_reg),
            ),
            name="lstm_1"
        ),
        layers.Dropout(dropout, name="dropout_1"),

        # 第二层 LSTM
        layers.Bidirectional(
            layers.LSTM(
                units[1],
                return_sequences=False,
                kernel_regularizer=regularizers.l2(l2_reg),
                recurrent_regularizer=regularizers.l2(l2_reg),
            ),
            name="lstm_2"
        ),
        layers.Dropout(dropout, name="dropout_2"),

        # 全连接层
        layers.Dense(
            128,
            activation="relu",
            kernel_regularizer=regularizers.l2(l2_reg),
            name="dense_1"
        ),
        layers.Dropout(dropout, name="dropout_3"),

        # 输出层
        layers.Dense(output_dim, name="output")
    ], name="LSTM_Load_Forecaster")

    return model


class LSTMModel:
    """LSTM 模型封装类，提供训练和预测接口"""

    def __init__(self, input_shape, output_dim, config, name="lstm"):
        """
        Args:
            input_shape: (lookback, n_features)
            output_dim: horizon
            config: 模型配置
            name: 模型名称
        """
        self.name = name
        self.input_shape = input_shape
        self.output_dim = output_dim
        self.config = config
        self.model = None
        self.history = None

    def build(self):
        """构建模型"""
        self.model = build_lstm_model(self.input_shape, self.output_dim, self.config)
        self.model.summary()
        return self.model

    def compile(self, learning_rate=1e-3):
        """编译模型"""
        self.model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
            loss=keras.losses.Huber(),  # 对异常值鲁棒
            metrics=[
                keras.metrics.MeanAbsoluteError(name="mae"),
                keras.metrics.RootMeanSquaredError(name="rmse"),
            ]
        )
        return self.model

    def get_callbacks(self, patience=10, min_lr=1e-6, checkpoint_path=None):
        """
        获取训练回调函数

        Args:
            patience: 早停耐心值
            min_lr: 最小学习率
            checkpoint_path: 模型保存路径

        Returns:
            list: 回调函数列表
        """
        callbacks_list = [
            # 早停
            callbacks.EarlyStopping(
                monitor="val_loss",
                patience=patience,
                restore_best_weights=True,
                verbose=1,
                mode="min",
            ),
            # 学习率调度
            callbacks.ReduceLROnPlateau(
                monitor="val_loss",
                factor=0.5,
                patience=5,
                min_lr=min_lr,
                verbose=1,
                mode="min",
            ),
        ]

        # 模型检查点（如果提供了保存路径）
        if checkpoint_path:
            callbacks_list.append(
                callbacks.ModelCheckpoint(
                    filepath=checkpoint_path,
                    monitor="val_loss",
                    save_best_only=True,
                    save_weights_only=True,
                    verbose=1,
                    mode="min",
                )
            )

        return callbacks_list

    def train(self, X_train, y_train, X_val, y_val, 
              epochs=100, batch_size=64, checkpoint_path=None):
        """
        训练模型

        Args:
            X_train: 训练集特征 (n_samples, lookback, n_features)
            y_train: 训练集目标 (n_samples, horizon)
            X_val: 验证集特征
            y_val: 验证集目标
            epochs: 训练轮数
            batch_size: 批大小
            checkpoint_path: 模型保存路径

        Returns:
            History: 训练历史
        """
        callbacks_list = self.get_callbacks(
            patience=self.config.get("patience", 10),
            min_lr=self.config.get("min_lr", 1e-6),
            checkpoint_path=checkpoint_path
        )

        self.history = self.model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=epochs,
            batch_size=batch_size,
            callbacks=callbacks_list,
            shuffle=True,
            verbose=1,
        )

        return self.history

    def predict(self, X):
        """
        预测

        Args:
            X: 输入特征 (n_samples, lookback, n_features)

        Returns:
            numpy.ndarray: 预测结果 (n_samples, horizon)
        """
        return self.model.predict(X)

    def save(self, filepath):
        """保存模型"""
        self.model.save(filepath)
        print(f"[保存] 模型已保存到: {filepath}")

    def load(self, filepath):
        """加载模型"""
        self.model = keras.models.load_model(filepath)
        print(f"[加载] 模型已从 {filepath} 加载")
        return self.model


# ============================================================================
# 测试代码
# ============================================================================
if __name__ == "__main__":
    # 测试模型构建
    config = {"units": [128, 64], "dropout": 0.2, "l2_reg": 1e-5}
    model_obj = LSTMModel(
        input_shape=(168, 38),
        output_dim=24,
        config=config
    )
    model_obj.build()
    model_obj.compile()

    # 输出参数量
    total_params = model_obj.model.count_params()
    print(f"\n模型总参数量: {total_params:,}")
    print(f"模型大小约: {total_params * 4 / 1024 / 1024:.2f} MB (float32)")