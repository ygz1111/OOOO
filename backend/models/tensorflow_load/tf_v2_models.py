# -*- coding: utf-8 -*-
"""
TF v2 模型定义 (负荷 RT_Demand + 电价 RT_LMP 分位数, 168h -> 24h)
================================================================

从 MMXX 训练工程原样移植: MMXX/smart-grid/scripts/train_tf.py
  * encoder: GRU(192, dropout=0.15) over 168h history (带 Masking(0.0))
  * decoder: RepeatVector(24) + 拼接未来 24h 已知特征 -> Dense128/Dropout/Dense96
  * 双头: load (B,24,1) MAE | price (B,24,3) = p10/p50/p90 pinball
  * 权重文件为 save_weights_only 的 *.weights.h5, 推理必须先按本模块重建图
    再 model.load_weights(...)

注意: metrics.json 里的 "encoder":"GRU160" 是训练脚本硬编码的过时标签,
真实结构为 GRU(192) (已用训练日志参数量 159,524 与 h5 张量形状双重验证)。

作者: 毕业设计项目 (接入 MMXX 训练产物, 不修改训练代码)
"""

from __future__ import annotations

import tensorflow as tf

LOOKBACK = 168   # 历史窗口 (小时)
HORIZON = 24     # 预测步长 (小时)

# 过去 168h 输入列 (顺序不能变, 与训练一致)
PAST_COLS = [
    "RT_Demand", "DA_Demand", "RT_LMP", "DA_LMP", "Dry_Bulb", "Dew_Point",
    "hdd65", "cdd65", "temp_mem",
    "clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos",
    "is_holiday", "is_dst",
]

# 未来 24h 输入列 (已知特征: DA 出清曲线/天气预报/日历 + rt_yest)
FUT_COLS = [
    "DA_Demand", "DA_LMP", "Dry_Bulb", "Dew_Point", "hdd65", "cdd65",
    "clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos",
    "is_holiday", "is_dst", "rt_yest",
]

# price 输出三通道 = p10/p50/p90
TAUS = (0.1, 0.5, 0.9)


def build_model(n_past: int = None, n_fut: int = None) -> tf.keras.Model:
    """重建 train_tf.py build_model() 的图 (GRU192 双头, Keras3 布局)"""
    n_past = n_past or len(PAST_COLS)
    n_fut = n_fut or len(FUT_COLS)
    past = tf.keras.Input(shape=(LOOKBACK, n_past), name="in_past")
    fut = tf.keras.Input(shape=(HORIZON, n_fut), name="in_fut")
    x = tf.keras.layers.Masking(mask_value=0.0)(past)
    x = tf.keras.layers.GRU(192, return_sequences=False, dropout=0.15,
                            recurrent_dropout=0.0, name="encoder")(x)
    ctx = tf.keras.layers.RepeatVector(HORIZON, name="ctx_tile")(x)
    dec = tf.keras.layers.Concatenate(axis=-1)([ctx, fut])
    dec = tf.keras.layers.Dense(128, activation="swish", name="dec_d1")(dec)
    dec = tf.keras.layers.Dropout(0.15)(dec)
    dec = tf.keras.layers.Dense(96, activation="swish", name="dec_d2")(dec)
    load = tf.keras.layers.TimeDistributed(
        tf.keras.layers.Dense(1, name="load_head"), name="load_td")(dec)   # (B,24,1)
    price_q = tf.keras.layers.TimeDistributed(
        tf.keras.layers.Dense(3, name="price_head"), name="price_td")(dec)  # (B,24,3)
    model = tf.keras.Model(inputs=[past, fut], outputs={"load": load, "price": price_q})
    return model


def load_trained_model(weights_path: str) -> tf.keras.Model:
    """重建图并载入训练权重 (save_weights_only 的 h5)"""
    model = build_model(len(PAST_COLS), len(FUT_COLS))
    model.load_weights(weights_path)
    return model


if __name__ == "__main__":
    m = load_trained_model(
        r"D:\GitHub\OOOOOO\backend\models\tf_assets\tf_v2\tf_v2_best.weights.h5")
    m.summary()
    print("params:", m.count_params())
