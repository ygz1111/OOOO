# -*- coding: utf-8 -*-
"""TensorFlow pv_v2 architecture used by training and production inference."""
from __future__ import annotations

import tensorflow as tf


LOOKBACK = 96
HORIZON = 24
ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]
WEATHER_COLS = (
    [f"ghi_{zone}" for zone in ZONES]
    + [f"cloud_{zone}" for zone in ZONES]
    + ["temp_mean", "dew_mean"]
)
COMMON_COLS = WEATHER_COLS + [
    "coszen", "sun_up", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "doy_sin", "doy_cos", "trend_days",
]
PAST_COLS = COMMON_COLS + ["pv_mw_ISONE"]
FUT_COLS = COMMON_COLS


def _residual_tcn(x, filters: int, dilation: int, name: str):
    residual = x
    if int(x.shape[-1]) != filters:
        residual = tf.keras.layers.Conv1D(filters, 1, name=f"{name}_projection")(residual)
    y = tf.keras.layers.Conv1D(
        filters, 3, padding="causal", dilation_rate=dilation,
        activation="swish", name=f"{name}_conv1",
    )(x)
    y = tf.keras.layers.SpatialDropout1D(0.10, name=f"{name}_dropout")(y)
    y = tf.keras.layers.Conv1D(
        filters, 3, padding="causal", dilation_rate=dilation,
        name=f"{name}_conv2",
    )(y)
    return tf.keras.layers.LayerNormalization(name=f"{name}_norm")(residual + y)


def build_model() -> tf.keras.Model:
    past = tf.keras.Input((LOOKBACK, len(PAST_COLS)), name="past_features")
    future = tf.keras.Input((HORIZON, len(FUT_COLS)), name="future_features")
    encoded = _residual_tcn(past, 64, 1, "tcn1")
    encoded = _residual_tcn(encoded, 64, 2, "tcn2")
    encoded = _residual_tcn(encoded, 64, 4, "tcn3")
    encoded, state = tf.keras.layers.GRU(
        96, return_sequences=True, return_state=True,
        dropout=0.10, name="history_gru",
    )(encoded)
    query = tf.keras.layers.Dense(96, activation="swish", name="future_embedding")(future)
    cross = tf.keras.layers.MultiHeadAttention(
        num_heads=4, key_dim=24, dropout=0.10, name="history_attention",
    )(query=query, value=encoded, key=encoded)
    query = tf.keras.layers.LayerNormalization(name="attention_norm")(query + cross)
    context = tf.keras.layers.RepeatVector(HORIZON, name="repeat_state")(state)
    decoded = tf.keras.layers.Concatenate(name="decoder_inputs")([query, context])
    decoded = tf.keras.layers.GRU(
        96, return_sequences=True, dropout=0.10, name="decoder_gru",
    )(decoded)
    decoded = tf.keras.layers.Dense(64, activation="swish", name="output_dense")(decoded)
    decoded = tf.keras.layers.Dropout(0.10, name="output_dropout")(decoded)
    output = tf.keras.layers.Dense(1, activation="softplus", name="pv_ratio")(decoded)
    return tf.keras.Model([past, future], output, name="pv_v2_tcn_gru_attention")


def load_trained_model(weights_path: str) -> tf.keras.Model:
    model = build_model()
    model.load_weights(weights_path)
    return model


__all__ = ["LOOKBACK", "HORIZON", "ZONES", "PAST_COLS", "FUT_COLS", "build_model", "load_trained_model"]
