"""
智能电网负荷预测 - 模型定义模块
定义 LSTM / Transformer / TCN 三种深度学习模型

所有模型统一接口:
  - 输入: (batch, lookback=168, n_features=38)
  - 输出: (batch, horizon=24)
"""

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers, Model, optimizers, callbacks


# ============================================================================
# 模型1: LSTM + Attention (主力模型)
# ============================================================================

def build_lstm_model(lookback=168, n_features=38, horizon=24,
                     lstm_units=[128, 64], dense_units=64,
                     dropout_rate=0.2, learning_rate=1e-3):
    """
    LSTM + Multi-Head Attention 模型

    架构:
      Input (168, 38)
        -> LSTM(128, return_sequences=True)
        -> LayerNorm
        -> Dropout(0.2)
        -> LSTM(64, return_sequences=True)
        -> MultiHeadAttention(4 heads)
        -> GlobalAveragePooling1D
        -> Dense(64, relu)
        -> Dropout(0.2)
        -> Dense(24)

    Args:
        lookback: 回看窗口大小
        n_features: 输入特征数
        horizon: 预测步长
        lstm_units: LSTM 层单元数列表
        dense_units: 全连接层单元数
        dropout_rate: Dropout 比率
        learning_rate: 学习率

    Returns:
        keras.Model
    """
    inp = layers.Input(shape=(lookback, n_features), name="input")

    # LSTM 第一层
    x = layers.LSTM(lstm_units[0], return_sequences=True, name="lstm_1")(inp)
    x = layers.LayerNormalization(name="ln_1")(x)
    x = layers.Dropout(dropout_rate, name="dropout_1")(x)

    # LSTM 第二层
    x = layers.LSTM(lstm_units[1], return_sequences=True, name="lstm_2")(x)
    x = layers.LayerNormalization(name="ln_2")(x)

    # Multi-Head Attention (自注意力)
    x_att = layers.MultiHeadAttention(
        num_heads=4, key_dim=32, name="multi_head_attention"
    )(x, x)
    x = layers.Add(name="residual_add")([x, x_att])  # 残差连接
    x = layers.LayerNormalization(name="ln_3")(x)

    # 全局池化 + 全连接
    x = layers.GlobalAveragePooling1D(name="global_avg_pool")(x)
    x = layers.Dense(dense_units, activation="relu", name="dense_1")(x)
    x = layers.Dropout(dropout_rate, name="dropout_2")(x)

    # 输出层
    out = layers.Dense(horizon, name="output")(x)

    model = Model(inp, out, name="LSTM_Attention")

    # Huber Loss 对异常值更鲁棒
    model.compile(
        optimizer=optimizers.Adam(learning_rate=learning_rate),
        loss=keras.losses.Huber(),
        metrics=["mae", "mse"]
    )

    return model


# ============================================================================
# 模型2: Transformer Encoder
# ============================================================================

def transformer_encoder_block(x, head_dim, num_heads, ff_dim, dropout_rate=0.2):
    """Transformer Encoder Block"""
    # Self-Attention
    attn_output = layers.MultiHeadAttention(
        num_heads=num_heads, key_dim=head_dim
    )(x, x)
    x = layers.Add()([x, attn_output])
    x = layers.LayerNormalization()(x)

    # Feed-Forward
    ff = layers.Dense(ff_dim, activation="relu")(x)
    ff = layers.Dense(x.shape[-1])(ff)
    x = layers.Add()([x, ff])
    x = layers.LayerNormalization()(x)

    return x


def build_transformer_model(lookback=168, n_features=38, horizon=24,
                            num_blocks=2, head_dim=32, num_heads=4,
                            ff_dim=128, dropout_rate=0.2, learning_rate=1e-3):
    """
    Transformer Encoder 模型

    架构:
      Input (168, 38)
        -> 位置编码
        -> Transformer Block x 2
        -> GlobalAveragePooling1D
        -> Dense(64, relu)
        -> Dropout(0.2)
        -> Dense(24)
    """
    inp = layers.Input(shape=(lookback, n_features), name="input")

    # 投影到模型维度
    x = layers.Dense(64, name="projection")(inp)

    # 位置编码 (可学习的)
    pos_encoding = tf.Variable(
        tf.random.normal([1, lookback, 64], stddev=0.02),
        trainable=True, name="pos_encoding"
    )
    x = x + pos_encoding

    # Transformer Blocks
    for i in range(num_blocks):
        x = transformer_encoder_block(
            x, head_dim=head_dim, num_heads=num_heads,
            ff_dim=ff_dim, dropout_rate=dropout_rate
        )

    # 池化 + 全连接
    x = layers.GlobalAveragePooling1D(name="global_avg_pool")(x)
    x = layers.Dense(64, activation="relu", name="dense_1")(x)
    x = layers.Dropout(dropout_rate, name="dropout_final")(x)

    out = layers.Dense(horizon, name="output")(x)

    model = Model(inp, out, name="Transformer")

    model.compile(
        optimizer=optimizers.Adam(learning_rate=learning_rate),
        loss=keras.losses.Huber(),
        metrics=["mae", "mse"]
    )

    return model


# ============================================================================
# 模型3: TCN (Temporal Convolutional Network)
# ============================================================================

def residual_tcn_block(x, filters, kernel_size, dilation_rate, dropout_rate=0.2):
    """
    TCN 残差块 (因果膨胀卷积)

    特点:
      - 因果卷积: 只看过去数据，不看未来
      - 膨胀卷积: 感受野指数增长
      - 残差连接: 梯度稳定
    """
    prev_x = x

    # 两个因果膨胀卷积层 (类似 ResNet 的双卷积结构)
    for i in range(2):
        # 因果卷积: padding='causal' 确保只看过去
        x = layers.Conv1D(
            filters=filters,
            kernel_size=kernel_size,
            dilation_rate=dilation_rate,
            padding='causal',
            name=f"conv1d_{dilation_rate}_{i}"
        )(x)
        x = layers.BatchNormalization(name=f"bn_{dilation_rate}_{i}")(x)
        x = layers.Activation('relu', name=f"relu_{dilation_rate}_{i}")(x)
        x = layers.Dropout(dropout_rate, name=f"tcn_dropout_{dilation_rate}_{i}")(x)

    # 残差连接 (如果通道数不匹配，用 1x1 卷积对齐)
    if prev_x.shape[-1] != filters:
        prev_x = layers.Conv1D(filters, 1, padding='same', name=f"residual_proj_{dilation_rate}")(prev_x)

    x = layers.Add()([prev_x, x])
    x = layers.Activation('relu')(x)

    return x


def build_tcn_model(lookback=168, n_features=38, horizon=24,
                    filters=64, kernel_size=3, dropout_rate=0.2,
                    learning_rate=1e-3):
    """
    TCN (时间卷积网络) 模型

    架构:
      Input (168, 38)
        -> TCN Block (dilation=1)  感受野=3
        -> TCN Block (dilation=2)  感受野=7
        -> TCN Block (dilation=4)  感受野=15
        -> TCN Block (dilation=8)  感受野=31
        -> TCN Block (dilation=16) 感受野=63
        -> TCN Block (dilation=32) 感受野=127  (覆盖168)
        -> GlobalAveragePooling1D
        -> Dense(64, relu)
        -> Dropout(0.2)
        -> Dense(24)

    膨胀系数 1,2,4,8,16,32 的感受野:
      每个block贡献 kernel_size-1 = 2 的感受野
      总感受野 = 1 + 2*(1+2+4+8+16+32) = 127
      加上最后一个block: ~127+2 = 129, 加上 kernel_size=3 → 接近168
    """
    inp = layers.Input(shape=(lookback, n_features), name="input")

    # 初始投影
    x = layers.Conv1D(filters, 1, padding='same', name="input_proj")(inp)

    # TCN 残差块 (膨胀系数指数增长)
    dilations = [1, 2, 4, 8, 16, 32]
    for d in dilations:
        x = residual_tcn_block(x, filters=filters, kernel_size=kernel_size,
                               dilation_rate=d, dropout_rate=dropout_rate)

    # 池化 + 全连接
    x = layers.GlobalAveragePooling1D(name="global_avg_pool")(x)
    x = layers.Dense(64, activation="relu", name="dense_1")(x)
    x = layers.Dropout(dropout_rate, name="dropout_final")(x)

    out = layers.Dense(horizon, name="output")(x)

    model = Model(inp, out, name="TCN")

    model.compile(
        optimizer=optimizers.Adam(learning_rate=learning_rate),
        loss=keras.losses.Huber(),
        metrics=["mae", "mse"]
    )

    return model


# ============================================================================
# 回调函数
# ============================================================================

def get_callbacks(model_name, save_dir="results"):
    """
    获取训练回调函数集合

    包含:
      1. EarlyStopping: 早停 (patience=10)
      2. ReduceLROnPlateau: 学习率衰减
      3. ModelCheckpoint: 保存最佳模型权重
      4. CSVLogger: 记录训练日志到CSV
    """
    import os
    os.makedirs(save_dir, exist_ok=True)

    callbacks_list = [
        # 早停: 验证损失 10 个 epoch 不下降则停止
        keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=10,
            restore_best_weights=True,
            verbose=1
        ),
        # 学习率衰减: 验证损失 5 个 epoch 不下降则 lr *= 0.5
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=5,
            min_lr=1e-6,
            verbose=1
        ),
        # 保存最佳模型权重
        keras.callbacks.ModelCheckpoint(
            filepath=os.path.join(save_dir, f"{model_name}_best.weights.h5"),
            monitor="val_loss",
            save_best_only=True,
            save_weights_only=True,
            verbose=1
        ),
        # 训练日志保存为 CSV
        keras.callbacks.CSVLogger(
            os.path.join(save_dir, f"{model_name}_training_log.csv"),
            append=False
        ),
    ]

    return callbacks_list


# ============================================================================
# 测试函数
# ============================================================================

if __name__ == "__main__":
    # 测试模型构建
    print("测试模型构建...")

    models = {
        "LSTM_Attention": build_lstm_model(),
        "Transformer": build_transformer_model(),
        "TCN": build_tcn_model(),
    }

    for name, model in models.items():
        print(f"\n{'='*50}")
        print(f"模型: {name}")
        print(f"{'='*50}")
        model.summary()
