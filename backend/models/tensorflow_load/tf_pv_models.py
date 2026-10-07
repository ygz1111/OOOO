# -*- coding: utf-8 -*-
"""
TF pv_v1 模型定义 (光伏出力 p.u., 96h -> 24h)
==============================================

从 MMXX 训练工程原样移植: MMXX/smart-grid/scripts/train_pv.py
  * encoder: GRU(128, dropout=0.15) over 96h history
  * decoder: RepeatVector(24) + 拼接未来 24h 已知特征 -> Dense96/Dropout/Dense64
  * 单输出 (B,24,1): 归一化 pv_n_ISONE (0..1, ISO-NE BTM 光伏合计), MAE loss
  * 权重文件为 save_weights_only 的 *.weights.h5, 推理必须先重建图再 load_weights

作者: 毕业设计项目 (接入 MMXX 训练产物, 不修改训练代码)
"""

from __future__ import annotations

import tensorflow as tf

LOOKBACK = 96    # 历史窗口 (小时)
HORIZON = 24     # 预测步长 (小时)

# 过去 96h 输入列 (顺序不能变, 与训练一致)
PAST_COLS = [
    "ghi_mean", "cloud_mean", "temp_mean", "coszen", "sun_up",
    "pv_n_ISONE", "db_ca", "dp_ca",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
]

# 未来 24h 输入列 (ERA5 预报/太阳几何/日历, 训练时"预报=实际")
FUT_COLS = [
    "ghi_mean", "cloud_mean", "temp_mean", "coszen", "sun_up",
    "hour_sin", "hour_cos",
]

# 8 个 ISO-NE 区域 (温度取均值得到 temp_mean)
ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]


def build_model(n_past: int = None, n_fut: int = None) -> tf.keras.Model:
    """重建 train_pv.py build_model() 的图 (GRU128, Keras3 布局)"""
    n_past = n_past or len(PAST_COLS)
    n_fut = n_fut or len(FUT_COLS)
    past = tf.keras.Input(shape=(LOOKBACK, n_past), name="in_past")
    fut = tf.keras.Input(shape=(HORIZON, n_fut), name="in_fut")
    x = tf.keras.layers.GRU(128, return_sequences=False, dropout=0.15, name="enc")(past)
    ctx = tf.keras.layers.RepeatVector(HORIZON)(x)
    d = tf.keras.layers.Concatenate()([ctx, fut])
    d = tf.keras.layers.Dense(96, activation="swish")(d)
    d = tf.keras.layers.Dropout(0.15)(d)
    d = tf.keras.layers.Dense(64, activation="swish")(d)
    out = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(1, name="pv"))(d)
    return tf.keras.Model(inputs=[past, fut], outputs=out)


def load_trained_model(weights_path: str) -> tf.keras.Model:
    """重建图并载入训练权重 (save_weights_only 的 h5)"""
    model = build_model(len(PAST_COLS), len(FUT_COLS))
    model.load_weights(weights_path)
    return model


if __name__ == "__main__":
    m = load_trained_model(
        r"D:\GitHub\OOOOOO\backend\models\tf_assets\pv_v1\pv_v1_best.weights.h5")
    m.summary()
    print("params:", m.count_params())
