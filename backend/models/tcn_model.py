"""
TCN (Temporal Convolutional Network) 负荷预测模型
基于膨胀因果卷积，适合长序列时序建模
"""

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers, models, regularizers
import numpy as np


class CausalConv1D(layers.Conv1D):
    """
    因果卷积层：卷积核只看过去，不看未来
    通过 padding 实现
    """
    def __init__(self, filters, kernel_size, strides=1, dilation_rate=1, 
                 kernel_regularizer=None, name=None, **kwargs):
        super().__init__(
            filters=filters,
            kernel_size=kernel_size,
            strides=strides,
            dilation_rate=dilation_rate,
            padding="causal",  # 因果卷积
            kernel_initializer="he_normal",
            kernel_regularizer=kernel_regularizer,
            name=name,
            **kwargs
        )


class TemporalBlock(layers.Layer):
    """TCN 的残差块"""
    def __init__(self, filters, kernel_size, dilation, dropout=0.2, l2_reg=1e-5, **kwargs):
        super().__init__(**kwargs)
        self.dropout = dropout
        self.dilation = dilation
        self.filters = filters

        # 两个卷积层
        self.conv1 = CausalConv1D(
            filters=filters,
            kernel_size=kernel_size,
            dilation_rate=dilation,
            kernel_regularizer=regularizers.l2(l2_reg),
        )
        self.conv2 = CausalConv1D(
            filters=filters,
            kernel_size=kernel_size,
            dilation_rate=dilation,
            kernel_regularizer=regularizers.l2(l2_reg),
        )

        # 层归一化
        self.layernorm1 = layers.LayerNormalization(epsilon=1e-6)
        self.layernorm2 = layers.LayerNormalization(epsilon=1e-6)

        # Dropout
        self.dropout1 = layers.Dropout(dropout)
        self.dropout2 = layers.Dropout(dropout)

        # 如果输入输出维度不同，使用 1x1 卷积调整
        self.downsample = None  # 动态设置

    def build(self, input_shape):
        if input_shape[-1] != self.filters:
            self.downsample = layers.Dense(self.filters)

    def call(self, x, training=False):
        # 第一个卷积 + LN + ReLU + Dropout
        out = self.conv1(x)
        out = self.layernorm1(out)
        out = tf.nn.relu(out)
        out = self.dropout1(out, training=training)

        # 第二个卷积 + LN + Dropout
        out = self.conv2(out)
        out = self.layernorm2(out)
        out = self.dropout2(out, training=training)

        # 残差连接
        res = x if self.downsample is None else self.downsample(x)
        return out + res


def build_tcn_model(input_shape, output_dim, config):
    """
    构建 TCN 预测模型

    Args:
        input_shape: (lookback, n_features)
        output_dim: horizon
        config: TCN_CONFIG 配置字典

    Returns:
        keras.Model: TCN 模型
    """
    nb_filters = config.get("nb_filters", [64, 128, 64])
    kernel_size = config.get("kernel_size", 3)
    dilations = config.get("dilations", [1, 2, 4])
    dropout = config.get("dropout", 0.2)
    l2_reg = config.get("l2_reg", 1e-5)

    inputs = layers.Input(shape=input_shape, name="input")

    # 特征投影
    x = layers.Dense(nb_filters[0], name="projection")(inputs)

    # TCN 层堆叠
    for i, (num_filters, dilation) in enumerate(zip(nb_filters, dilations)):
        x = TemporalBlock(
            filters=num_filters,
            kernel_size=kernel_size,
            dilation=dilation,
            dropout=dropout,
            l2_reg=l2_reg,
            name=f"temporal_block_{i}"
        )(x)

    # 全局池化
    x = layers.GlobalAveragePooling1D(name="global_pool")(x)

    # 全连接层
    x = layers.Dense(
        128,
        activation="relu",
        kernel_regularizer=regularizers.l2(l2_reg),
        name="dense_1"
    )
    x = layers.Dropout(dropout, name="dropout_1")(x)

    # 输出层
    outputs = layers.Dense(output_dim, name="output")

    model = models.Model(inputs=inputs, outputs=outputs, name="TCN_Load_Forecaster")

    return model


class TCNModel:
    """TCN 模型封装类"""

    def __init__(self, input_shape, output_dim, config, name="tcn"):
        self.name = name
        self.input_shape = input_shape
        self.output_dim = output_dim
        self.config = config
        self.model = None
        self.history = None

    def build(self):
        """构建模型"""
        self.model = build_tcn_model(self.input_shape, self.output_dim, self.config)
        self.model.summary()
        return self.model

    def compile(self, learning_rate=1e-3):
        """编译模型"""
        self.model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
            loss=keras.losses.Huber(),
            metrics=[
                keras.metrics.MeanAbsoluteError(name="mae"),
                keras.metrics.RootMeanSquaredError(name="rmse"),
            ]
        )
        return self.model

    def get_callbacks(self, patience=10, min_lr=1e-6, checkpoint_path=None):
        """获取训练回调函数"""
        callbacks_list = [
            callbacks.EarlyStopping(
                monitor="val_loss",
                patience=patience,
                restore_best_weights=True,
                verbose=1,
                mode="min",
            ),
            callbacks.ReduceLROnPlateau(
                monitor="val_loss",
                factor=0.5,
                patience=5,
                min_lr=min_lr,
                verbose=1,
                mode="min",
            ),
        ]

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
        """训练模型"""
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
        """预测"""
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
    config = {"nb_filters": [64, 128, 64], "kernel_size": 3, "dilations": [1, 2, 4], 
              "dropout": 0.2, "l2_reg": 1e-5}
    model_obj = TCNModel(
        input_shape=(168, 38),
        output_dim=24,
        config=config
    )
    model_obj.build()
    model_obj.compile()

    total_params = model_obj.model.count_params()
    print(f"\n模型总参数量: {total_params:,}")
    print(f"模型大小约: {total_params * 4 / 1024 / 1024:.2f} MB (float32)")