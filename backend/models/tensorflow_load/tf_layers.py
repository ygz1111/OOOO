# -*- coding: utf-8 -*-
"""TensorFlow/Keras 四模型实验所需的自定义层。

实现约定：
  - LayerNormalization 按最后一个特征维度归一化。
  - BatchNormalization 使用 epsilon=1e-5、momentum=0.9。
  - MultiHeadAttention 的残差连接由调用处完成。
  - TransformerEncoderBlock 使用 Post-LN 顺序。
  - Dropout 只在训练时生效。
"""
import math

import tensorflow as tf
from tensorflow.keras import layers
from keras.saving import register_keras_serializable


@register_keras_serializable(package="TFSmartGrid")
class PositionalEncodingLayer(layers.Layer):
    """可学习时间位置编码（复刻 SpatialTemporalTransformer._create_positional_encoding）。

    使用 add_weight 创建可学习参数，以 sin/cos 常量初始化。
    """

    def __init__(self, max_len: int = 200, d_model: int = 128, **kwargs):
        super().__init__(**kwargs)
        self.max_len = max_len
        self.d_model = d_model

    def build(self, input_shape):
        # 正弦/余弦初始化矩阵 (1, max_len, d_model)
        pe = tf.zeros((self.max_len, self.d_model), dtype=tf.float32)
        position = tf.cast(tf.range(self.max_len, dtype=tf.float32), tf.float32)[:, None]
        div_term = tf.exp(
            tf.cast(tf.range(0, self.d_model, 2), tf.float32)
            * (-math.log(10000.0) / self.d_model)
        )
        pe_sin = tf.sin(position * div_term)
        pe_cos = tf.cos(position * div_term)
        # 对应 numpy 的 pe[:, 0::2] = sin; pe[:, 1::2] = cos
        pe_flat = tf.concat(
            [tf.expand_dims(pe_sin, -1), tf.expand_dims(pe_cos, -1)], axis=-1
        )  # (max_len, d_model/2, 2)
        pe = tf.reshape(pe_flat, (self.max_len, self.d_model))
        self.time_pos_encoding = self.add_weight(
            name="time_pos_encoding",
            shape=(1, self.max_len, self.d_model),
            initializer=tf.constant_initializer(pe.numpy()),
            trainable=True,
        )
        super().build(input_shape)

    def call(self, x, training=None):
        seq_len = tf.shape(x)[1]
        return x + self.time_pos_encoding[:, :seq_len, :]

    def get_config(self):
        cfg = super().get_config()
        cfg.update({"max_len": self.max_len, "d_model": self.d_model})
        return cfg


@register_keras_serializable(package="TFSmartGrid")
class TransformerEncoderBlock(layers.Layer):
    """单层 Post-LN Transformer Encoder。

    前向顺序：
      x2 = self_attn(x, x, x)[0]              # scale=1/sqrt(key_dim)
      x  = x + dropout1(x2)                   # dropout 在残差相加之前
      x  = norm1(x)
      x2 = linear2(dropout(relu(linear1(x))))
      x  = x + dropout2(x2)
      x  = norm2(x)
    """

    def __init__(self, d_model: int = 128, nhead: int = 8, d_ff: int = 512,
                 dropout: float = 0.3, **kwargs):
        super().__init__(**kwargs)
        self.d_model = d_model
        self.nhead = nhead
        self.d_ff = d_ff
        self.dropout_rate = dropout

        self.self_attn = layers.MultiHeadAttention(
            num_heads=nhead, key_dim=d_model // nhead, dropout=dropout
        )  # 输出经投影层，残差连接由下方显式完成
        self.dropout1 = layers.Dropout(dropout)
        self.norm1 = layers.LayerNormalization(axis=-1, epsilon=1e-5)
        self.linear1 = layers.Dense(d_ff)
        self.activation = layers.ReLU()
        self.dropout_mid = layers.Dropout(dropout)
        self.linear2 = layers.Dense(d_model)
        self.dropout2 = layers.Dropout(dropout)
        self.norm2 = layers.LayerNormalization(axis=-1, epsilon=1e-5)

    def call(self, x, training=None):
        attn_out = self.self_attn(x, x, x, training=training)
        x = x + self.dropout1(attn_out, training=training)
        x = self.norm1(x)
        ffn = self.linear2(
            self.dropout_mid(self.activation(self.linear1(x)), training=training)
        )
        x = x + self.dropout2(ffn, training=training)
        x = self.norm2(x)
        return x

    def get_config(self):
        cfg = super().get_config()
        cfg.update({"d_model": self.d_model, "nhead": self.nhead,
                    "d_ff": self.d_ff, "dropout": self.dropout_rate})
        return cfg


@register_keras_serializable(package="TFSmartGrid")
class GRUAttentionLayer(layers.Layer):
    """BiGRU 自注意力（复刻 AttentionLayer，hidden_size=256 时输入特征为 256）。

    Dense(hidden→hidden//2, Tanh) → Dense(hidden//2→1, use_bias=False)
             → softmax(dim=1 时间维) → 加权求和 → [B, hidden]
    """

    def __init__(self, hidden_size: int = 256, **kwargs):
        super().__init__(**kwargs)
        self.hidden_size = hidden_size
        self.dense1 = layers.Dense(hidden_size // 2)
        self.dense2 = layers.Dense(1, use_bias=False)

    def call(self, x, training=None):
        scores = self.dense2(tf.nn.tanh(self.dense1(x)))  # [B, T, 1]
        weights = tf.nn.softmax(scores, axis=1)            # 时间维 softmax
        weighted = tf.reduce_sum(x * weights, axis=1)      # [B, hidden]
        return weighted

    def get_config(self):
        cfg = super().get_config()
        cfg.update({"hidden_size": self.hidden_size})
        return cfg


@register_keras_serializable(package="TFSmartGrid")
class TCNResidualBlock(layers.Layer):
    """TCN 残差块（复刻 DeepTCN.TCNResidualBlock）。

    padding = (kernel-1)*dilation//2（对称前后补零，保持长度）
             conv1 → BN1 → ReLU → Dropout → conv2 → BN2 → Dropout
             → (+1x1 下采样) → 残差相加 → ReLU
    """

    def __init__(self, input_dim: int, output_dim: int, kernel_size: int = 3,
                 dilation: int = 1, dropout: float = 0.3, **kwargs):
        super().__init__(**kwargs)
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.kernel_size = kernel_size
        self.dilation = dilation
        self.dropout_rate = dropout

        pad = (kernel_size - 1) * dilation // 2
        self.pad1 = layers.ZeroPadding1D(padding=pad)
        self.conv1 = layers.Conv1D(output_dim, kernel_size,
                                   dilation_rate=dilation, use_bias=True)
        self.bn1 = layers.BatchNormalization(axis=-1, momentum=0.9, epsilon=1e-5)
        self.dropout1 = layers.Dropout(dropout)

        self.pad2 = layers.ZeroPadding1D(padding=pad)
        self.conv2 = layers.Conv1D(output_dim, kernel_size,
                                   dilation_rate=dilation, use_bias=True)
        self.bn2 = layers.BatchNormalization(axis=-1, momentum=0.9, epsilon=1e-5)
        self.dropout2 = layers.Dropout(dropout)

        if input_dim != output_dim:
            self.downsample = layers.Conv1D(output_dim, 1, use_bias=True)
        else:
            self.downsample = None

    def call(self, x, training=None):
        residual = x
        out = self.dropout1(self.bn1(tf.nn.relu(self.conv1(self.pad1(x))), training=training),
                            training=training)
        out = self.dropout2(self.bn2(self.conv2(self.pad2(out)), training=training),
                            training=training)
        if self.downsample is not None:
            residual = self.downsample(residual)
        return tf.nn.relu(out + residual)

    def get_config(self):
        cfg = super().get_config()
        cfg.update({"input_dim": self.input_dim, "output_dim": self.output_dim,
                    "kernel_size": self.kernel_size, "dilation": self.dilation,
                    "dropout": self.dropout_rate})
        return cfg
