"""
Transformer 负荷预测模型
基于多头注意力机制，捕捉全局时序依赖
"""

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers, models, regularizers
import numpy as np


class TransformerEncoder(layers.Layer):
    """Transformer 编码器层"""
    def __init__(self, d_model, n_heads, d_ff, dropout=0.1, l2_reg=1e-5, **kwargs):
        super().__init__(**kwargs)
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_ff = d_ff
        self.dropout = dropout

        # 多头注意力
        self.mha = layers.MultiHeadAttention(
            num_heads=n_heads,
            key_dim=d_model // n_heads,
            dropout=dropout
        )

        # 层归一化
        self.layernorm1 = layers.LayerNormalization(epsilon=1e-6)
        self.layernorm2 = layers.LayerNormalization(epsilon=1e-6)

        # 前馈网络
        self.ffn = keras.Sequential([
            layers.Dense(d_ff, activation="relu", kernel_regularizer=regularizers.l2(l2_reg)),
            layers.Dropout(dropout),
            layers.Dense(d_model, kernel_regularizer=regularizers.l2(l2_reg)),
        ])

        self.dropout1 = layers.Dropout(dropout)
        self.dropout2 = layers.Dropout(dropout)

    def call(self, x, training=False, mask=None):
        # 多头注意力
        attn_output = self.mha(x, x, attention_mask=mask, training=training)
        attn_output = self.dropout1(attn_output, training=training)
        out1 = self.layernorm1(x + attn_output)

        # 前馈网络
        ffn_output = self.ffn(out1)
        ffn_output = self.dropout2(ffn_output, training=training)
        out2 = self.layernorm2(out1 + ffn_output)

        return out2


def build_transformer_model(input_shape, output_dim, config):
    """
    构建 Transformer 预测模型

    Args:
        input_shape: (lookback, n_features)
        output_dim: horizon
        config: Transformer_CONFIG 配置字典

    Returns:
        keras.Model: Transformer 模型
    """
    d_model = config.get("d_model", 128)
    n_heads = config.get("n_heads", 4)
    n_layers = config.get("n_layers", 2)
    d_ff = config.get("d_ff", 256)
    dropout = config.get("dropout", 0.2)
    l2_reg = config.get("l2_reg", 1e-5)

    inputs = layers.Input(shape=input_shape, name="input")

    # 特征投影层：将 n_features 映射到 d_model
    x = layers.Dense(d_model, name="projection")(inputs)
    x = layers.Dropout(dropout, name="input_dropout")(x)

    # 位置编码（使用可学习的位置嵌入）
    # 对于输入序列长度为 lookback，我们使用可学习的位置编码
    seq_len = input_shape[0]
    pos_encoding = layers.Embedding(
        input_dim=seq_len,
        output_dim=d_model,
        name="pos_encoding"
    )(tf.range(seq_len))
    x = x + pos_encoding
    x = layers.LayerNormalization(epsilon=1e-6, name="ln_after_pos")(x)

    # Transformer 编码器层堆叠
    for i in range(n_layers):
        x = TransformerEncoder(
            d_model=d_model,
            n_heads=n_heads,
            d_ff=d_ff,
            dropout=dropout,
            l2_reg=l2_reg,
            name=f"encoder_{i}"
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

    model = models.Model(inputs=inputs, outputs=outputs, name="Transformer_Load_Forecaster")

    return model


class TransformerModel:
    """Transformer 模型封装类"""

    def __init__(self, input_shape, output_dim, config, name="transformer"):
        self.name = name
        self.input_shape = input_shape
        self.output_dim = output_dim
        self.config = config
        self.model = None
        self.history = None

    def build(self):
        """构建模型"""
        self.model = build_transformer_model(self.input_shape, self.output_dim, self.config)
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
    config = {"d_model": 128, "n_heads": 4, "n_layers": 2, "d_ff": 256, "dropout": 0.2, "l2_reg": 1e-5}
    model_obj = TransformerModel(
        input_shape=(168, 38),
        output_dim=24,
        config=config
    )
    model_obj.build()
    model_obj.compile()

    total_params = model_obj.model.count_params()
    print(f"\n模型总参数量: {total_params:,}")
    print(f"模型大小约: {total_params * 4 / 1024 / 1024:.2f} MB (float32)")