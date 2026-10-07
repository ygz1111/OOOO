# -*- coding: utf-8 -*-
"""TensorFlow/Keras 四模型负荷预测实验实现。

输入: (batch, 168, 38)  归一化特征序列
输出: (batch, 24)       归一化未来 24 小时负荷

模型: EnhancedLSTM / SpatialTransformer / DeepTCN / BiGRU

实现方式: Functional API（静态计算图）。原因: Keras 3 对子类模型的
.keras 全量序列化存在缺陷（深层嵌套自定义层时重载丢失权重），
Functional 模型是序列化最稳定的路径。

本文件不接入当前 `tf_split_v1` 生产预测链，仅保留 TensorFlow 实验用途。
"""
import tensorflow as tf
from tensorflow.keras import layers

from keras.saving import register_keras_serializable

from models.tensorflow_load.tf_layers import (
    PositionalEncodingLayer,
    TransformerEncoderBlock,
    GRUAttentionLayer,
    TCNResidualBlock,
)

LOOKBACK = 168
INPUT_DIM = 38
OUTPUT_DIM = 24
DROPOUT = 0.3
L2_REG = 1e-4


@register_keras_serializable(package="TFSmartGrid")
def _last_timestep(t):
    """取序列最后时刻 [B,T,F] → [B,F]。"""
    return t[:, -1, :]


@register_keras_serializable(package="TFSmartGrid")
def _scale_01(t):
    """残差缩放 ×0.1。"""
    return t * 0.1


@register_keras_serializable(package="TFSmartGrid")
def _expand_channel_weights(w):
    """[B, D] → [B, 1, D]。"""
    return w[:, None, :]


@register_keras_serializable(package="TFSmartGrid")
def _time_mean(t):
    """时间维均值。"""
    return tf.reduce_mean(t, axis=1)


# ============================================================================
# 模型1: EnhancedLSTM
# LSTM(38→128,3层,层间drop) → LN(128) → Drop → LSTM(128→64,2层)
#               → LN(64) → MHA(64,4头) + 残差 → 末时刻 → FC(64→64→32→24)
#               旁路残差 Linear(38→24)×0.1
# ============================================================================
def build_enhanced_lstm(input_size=INPUT_DIM, hidden_size=128, num_layers=3,
                        output_size=OUTPUT_DIM, dropout=DROPOUT, l2_reg=None,
                        name="TFEnhancedLSTM"):
    x = layers.Input(shape=(LOOKBACK, input_size), name="input")

    # 第一段 LSTM（层间显式 Dropout）
    h = x
    for i in range(num_layers):
        h = layers.LSTM(hidden_size, return_sequences=True)(h)
        if i < num_layers - 1:
            h = layers.Dropout(dropout)(h)
    h = layers.LayerNormalization(axis=-1, epsilon=1e-5)(h)
    h = layers.Dropout(dropout)(h)

    # 第二段 LSTM（128→64, num_layers-1 层）
    half = hidden_size // 2
    for i in range(num_layers - 1):
        h = layers.LSTM(half, return_sequences=True)(h)
        if i < num_layers - 2:
            h = layers.Dropout(dropout)(h)
    h = layers.LayerNormalization(axis=-1, epsilon=1e-5)(h)

    # 多头自注意力（embed_dim=64, heads=4 → key_dim=16）
    attn = layers.MultiHeadAttention(num_heads=4, key_dim=half // 4,
                                     dropout=dropout)(h, h, h)
    combined = layers.Add()([h, attn])

    final = layers.Lambda(_last_timestep, name="last_timestep")(combined)

    out = layers.Dense(64)(final)
    out = layers.ReLU()(out)
    out = layers.Dropout(dropout)(out)
    out = layers.Dense(32, activation="tanh")(out)
    out = layers.Dropout(dropout)(out)
    lstm_output = layers.Dense(output_size)(out)

    # 残差: 原始输入最后时刻 → Dense(input→output) ×0.1
    residual_in = layers.Lambda(_last_timestep, name="residual_in")(x)
    residual = layers.Lambda(_scale_01)(layers.Dense(output_size)(residual_in))

    output = layers.Add(name="output")([lstm_output, residual])
    return tf.keras.Model(x, output, name=name)


# ============================================================================
# 模型2: SpatialTransformer
# 嵌入(38→128→128+LN) → 可学习位置编码(200×128) → Drop
#               → 4×Encoder(128,8头,FFN512,Post-LN) → 通道注意力
#               → 时间/特征双路融合(256→128) → 输出(128→128→64→24)
# ============================================================================
def build_spatial_transformer(input_size=INPUT_DIM, d_model=128, nhead=8,
                              num_layers=4, d_ff=512, output_size=OUTPUT_DIM,
                              dropout=DROPOUT, l2_reg=None,
                              name="TFSpatialTransformer"):
    x = layers.Input(shape=(LOOKBACK, input_size), name="input")

    # 输入嵌入（Linear→ReLU→Linear→LayerNorm）
    h = layers.Dense(d_model)(x)
    h = layers.ReLU()(h)
    h = layers.Dense(d_model)(h)
    h = layers.LayerNormalization(axis=-1, epsilon=1e-5)(h)

    # 可学习位置编码 + Dropout
    h = PositionalEncodingLayer(max_len=200, d_model=d_model)(h)
    h = layers.Dropout(dropout)(h)

    # Transformer 编码器 ×num_layers（Post-LN 语义封装在层内）
    for _ in range(num_layers):
        h = TransformerEncoderBlock(d_model=d_model, nhead=nhead, d_ff=d_ff,
                                    dropout=dropout)(h)

    # 通道注意力（先时间均值 → 权重 → 乘回时间步）
    ch_mean = layers.Lambda(_time_mean, name="time_mean")(h)
    ch = layers.Dense(d_model // 4)(ch_mean)
    ch = layers.ReLU()(ch)
    ch = layers.Dense(d_model)(ch)
    ch = layers.Activation("sigmoid")(ch)
    feature_attended = layers.Multiply()([h, layers.Lambda(_expand_channel_weights)(ch)])

    time_features = layers.Lambda(_last_timestep, name="time_feature")(h)
    feature_features = layers.Lambda(_time_mean, name="feature_feature")(feature_attended)
    fused = layers.Concatenate(axis=-1)([time_features, feature_features])

    # 融合层
    out = layers.Dense(d_model)(fused)
    out = layers.ReLU()(out)
    out = layers.Dropout(dropout)(out)

    # 输出投影
    out = layers.Dense(128)(out)
    out = layers.ReLU()(out)
    out = layers.Dropout(dropout)(out)
    out = layers.Dense(64)(out)
    out = layers.ReLU()(out)
    output = layers.Dense(output_size, name="output")(out)
    return tf.keras.Model(x, output, name=name)


# ============================================================================
# 模型3: DeepTCN
# Conv1D(38→64,k1,ReLU) → 3×TCN残差块[64→128→64→32] dilation 1/2/4
#               → Sigmoid 门控 → AdaptiveAvgPool → FC(32→128→64→24)
# ============================================================================
def build_deep_tcn(input_size=INPUT_DIM, num_channels=(64, 128, 64, 32),
                   kernel_size=3, output_size=OUTPUT_DIM, dropout=DROPOUT,
                   l2_reg=None, name="TFDeepTCN"):
    x = layers.Input(shape=(LOOKBACK, input_size), name="input")

    h = layers.Conv1D(num_channels[0], 1, use_bias=True)(x)
    h = layers.ReLU()(h)

    for i in range(len(num_channels) - 1):
        h = TCNResidualBlock(
            input_dim=num_channels[i], output_dim=num_channels[i + 1],
            kernel_size=kernel_size, dilation=2 ** i, dropout=dropout,
        )(h)

    gate = layers.Conv1D(num_channels[-1], 1, use_bias=True)(h)
    h = layers.Multiply()([h, layers.Activation("sigmoid")(gate)])
    h = layers.GlobalAveragePooling1D()(h)

    out = layers.Dense(128)(h)
    out = layers.ReLU()(out)
    out = layers.Dropout(dropout)(out)
    out = layers.Dense(64)(out)
    out = layers.ReLU()(out)
    output = layers.Dense(output_size, name="output")(out)
    return tf.keras.Model(x, output, name=name)


# ============================================================================
# 模型4: BiGRU
# GRU(38→128,3层,双向) → LN → Drop → GRU(256→128,2层,双向) → LN
#               → 自注意力(256→128→1) → FC(256→128→128→64→24)
# ============================================================================
def build_bigru(input_size=INPUT_DIM, hidden_size=128, num_layers=3,
                output_size=OUTPUT_DIM, dropout=DROPOUT, l2_reg=None,
                name="TFBiGRU"):
    x = layers.Input(shape=(LOOKBACK, input_size), name="input")

    # 第一段：3 层双向 GRU（层间 dropout）
    h = x
    for i in range(num_layers):
        h = layers.Bidirectional(layers.GRU(hidden_size, return_sequences=True))(h)
        if i < num_layers - 1:
            h = layers.Dropout(dropout)(h)
    h = layers.LayerNormalization(axis=-1, epsilon=1e-5)(h)
    h = layers.Dropout(dropout)(h)

    # 第二段：2 层双向 GRU（输入 256）
    for i in range(num_layers - 1):
        h = layers.Bidirectional(layers.GRU(hidden_size, return_sequences=True))(h)
        if i < num_layers - 2:
            h = layers.Dropout(dropout)(h)
    h = layers.LayerNormalization(axis=-1, epsilon=1e-5)(h)

    # 自注意力（hidden*2=256）
    attended = GRUAttentionLayer(hidden_size=hidden_size * 2)(h)
    attended = layers.Dropout(dropout)(attended)

    # 特征聚合
    out = layers.Dense(hidden_size)(attended)
    out = layers.ReLU()(out)
    out = layers.Dropout(dropout)(out)

    # 输出投影
    out = layers.Dense(128)(out)
    out = layers.ReLU()(out)
    out = layers.Dropout(dropout)(out)
    out = layers.Dense(64)(out)
    out = layers.ReLU()(out)
    output = layers.Dense(output_size, name="output")(out)
    return tf.keras.Model(x, output, name=name)


# ============================================================================
# TensorFlow 四模型工厂
# ============================================================================
def create_tf_four_models():
    return {
        "EnhancedLSTM": build_enhanced_lstm(
            input_size=INPUT_DIM, hidden_size=128, num_layers=3,
            output_size=OUTPUT_DIM, dropout=0.3, l2_reg=L2_REG),
        "SpatialTransformer": build_spatial_transformer(
            input_size=INPUT_DIM, d_model=128, nhead=8, num_layers=4,
            d_ff=512, output_size=OUTPUT_DIM, dropout=0.3, l2_reg=L2_REG),
        "DeepTCN": build_deep_tcn(
            input_size=INPUT_DIM, num_channels=[64, 128, 64, 32], kernel_size=3,
            output_size=OUTPUT_DIM, dropout=0.3, l2_reg=L2_REG),
        "BiGRU": build_bigru(
            input_size=INPUT_DIM, hidden_size=128, num_layers=3,
            output_size=OUTPUT_DIM, dropout=0.3, l2_reg=L2_REG),
    }


if __name__ == "__main__":
    for name, model in create_tf_four_models().items():
        n_params = sum(w.numpy().size for w in model.trainable_weights)
        print(f"{name}: {n_params:,} 可训练参数")
