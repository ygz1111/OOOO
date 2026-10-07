"""Production definitions for the independently trained TensorFlow models."""
from __future__ import annotations
import tensorflow as tf

LOOKBACK, HORIZON = 168, 24
LOAD_PAST_COLS = ["RT_Demand","DA_Demand","RT_LMP","DA_LMP","Dry_Bulb","Dew_Point","hdd65","cdd65","temp_mem","clock_hour_sin","clock_hour_cos","dow_sin","dow_cos","month_sin","month_cos","is_holiday","is_dst","rt_lag24","rt_lag168","rt_prev24_mean","rt_prev168_mean"]
FUTURE_COLS = ["DA_Demand","DA_LMP","Dry_Bulb","Dew_Point","hdd65","cdd65","temp_mem","clock_hour_sin","clock_hour_cos","dow_sin","dow_cos","month_sin","month_cos","is_holiday","holiday_shoulder","is_dst","rt_yest"]
PRICE_PAST_COLS = LOAD_PAST_COLS + ["rtlmp_lag1","rtlmp_lag24","rtlmp_lag168","rtlmp_prev24_mean","da_lmp_lag24"]
# Common contract required by the feature provider.  Load selects its own subset.
PAST_COLS = PRICE_PAST_COLS

class OrderedQuantiles(tf.keras.layers.Layer):
    def call(self, raw):
        lower = raw[..., 1:2] - tf.nn.softplus(raw[..., 0:1])
        median = raw[..., 1:2]
        upper = raw[..., 1:2] + tf.nn.softplus(raw[..., 2:3])
        return tf.concat([lower, median, upper], axis=-1)

def build_model(n_past: int, task: str) -> tf.keras.Model:
    past = tf.keras.Input((LOOKBACK, n_past), name="in_past")
    future = tf.keras.Input((HORIZON, len(FUTURE_COLS)), name="in_future")
    x = tf.keras.layers.LayerNormalization(name="past_norm")(past)
    x = tf.keras.layers.Bidirectional(tf.keras.layers.GRU(112, return_sequences=True, dropout=.10), name="encoder_bi_gru")(x)
    x = tf.keras.layers.GRU(144, dropout=.10, name="encoder_gru")(x)
    context = tf.keras.layers.RepeatVector(HORIZON, name="context_repeat")(x)
    f = tf.keras.layers.LayerNormalization(name="future_norm")(future)
    f = tf.keras.layers.Dense(72, activation="swish", name="future_projection")(f)
    x = tf.keras.layers.Concatenate(name="decoder_input")([context, f])
    x = tf.keras.layers.GRU(144, return_sequences=True, dropout=.10, name="decoder_gru")(x)
    x = tf.keras.layers.Dense(96, activation="swish", name="decoder_dense")(x)
    if task == "load":
        output = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(1), name="load")(x)
    elif task == "price":
        output = OrderedQuantiles(name="price")(tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(3), name="price_raw")(x))
    else: raise ValueError(task)
    return tf.keras.Model([past, future], output, name=f"tf_split_{task}")

def load_models(load_weights: str, price_weights: str):
    load = build_model(len(LOAD_PAST_COLS), "load"); load.load_weights(load_weights)
    price = build_model(len(PRICE_PAST_COLS), "price"); price.load_weights(price_weights)
    return load, price


def build_load_first_step_model(loaded_load_model: tf.keras.Model) -> tf.keras.Model:
    """Reuse loaded layers for the causal decoder's first step, without new weights.

    Future normalization/projection operate on each hour independently and the
    decoder is forward-only. Its first output needs one future row; later rows
    cannot affect it. The original 24-hour training/inference graph is untouched.
    """
    decoder = loaded_load_model.get_layer("decoder_gru")
    if decoder.go_backwards or not decoder.return_sequences:
        raise ValueError("Single-step replay requires a forward sequence decoder")
    past = tf.keras.Input((LOOKBACK, len(LOAD_PAST_COLS)), name="first_step_past")
    future = tf.keras.Input((1, len(FUTURE_COLS)), name="first_step_future")
    x = loaded_load_model.get_layer("past_norm")(past)
    x = loaded_load_model.get_layer("encoder_bi_gru")(x)
    x = loaded_load_model.get_layer("encoder_gru")(x)
    context = tf.keras.layers.RepeatVector(1, name="first_step_context_repeat")(x)
    f = loaded_load_model.get_layer("future_norm")(future)
    f = loaded_load_model.get_layer("future_projection")(f)
    x = loaded_load_model.get_layer("decoder_input")([context, f])
    x = decoder(x)
    x = loaded_load_model.get_layer("decoder_dense")(x)
    output = loaded_load_model.get_layer("load")(x)
    return tf.keras.Model([past, future], output, name="tf_split_load_first_step")
