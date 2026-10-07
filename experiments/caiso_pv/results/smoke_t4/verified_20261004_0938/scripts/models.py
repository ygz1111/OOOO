"""Independent CAISO models. No production or ISO-NE weights are imported."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import tensorflow as tf

MODEL_NAMES = ("gru", "tcn_gru", "tcn_gru_attention")


@dataclass(frozen=True)
class ModelConfig:
    past_hours: int = 96
    horizon_hours: int = 24
    hidden_units: int = 128
    tcn_filters: int = 96
    tcn_kernel_size: int = 3
    tcn_dilations: tuple[int, ...] = (1, 2, 4, 8)
    dropout: float = 0.15
    l2: float = 1e-5
    learning_rate: float = 1e-3
    attention_heads: int = 4
    loss: str = "huber"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_model(name: str, past_features: int, future_features: int,
                config: ModelConfig | None = None, *, compile_model: bool = True) -> tf.keras.Model:
    if name not in MODEL_NAMES:
        raise ValueError(f"Unknown model {name!r}; choose {MODEL_NAMES}")
    if past_features < 1 or future_features < 1:
        raise ValueError("Feature dimensions must be positive")
    cfg = config or ModelConfig()
    if cfg.past_hours != 96 or cfg.horizon_hours != 24:
        raise ValueError("This first-version experiment requires 96 past and 24 future hours")
    if cfg.hidden_units % cfg.attention_heads:
        raise ValueError("hidden_units must be divisible by attention_heads")
    layers = tf.keras.layers
    regularizer = tf.keras.regularizers.l2(cfg.l2)
    past = layers.Input((cfg.past_hours, past_features), name="past")
    future = layers.Input((cfg.horizon_hours, future_features), name="future")
    encoded = past
    if name != "gru":
        encoded = layers.Conv1D(cfg.tcn_filters, 1, name="tcn_projection")(encoded)
        for index, dilation in enumerate(cfg.tcn_dilations):
            residual = encoded
            for block in range(2):
                encoded = layers.Conv1D(
                    cfg.tcn_filters, cfg.tcn_kernel_size, dilation_rate=dilation,
                    padding="causal", activation="relu", kernel_regularizer=regularizer,
                    name=f"tcn_{index}_conv_{block}",
                )(encoded)
                encoded = layers.LayerNormalization(name=f"tcn_{index}_norm_{block}")(encoded)
                encoded = layers.Dropout(cfg.dropout, name=f"tcn_{index}_drop_{block}")(encoded)
            encoded = layers.Add(name=f"tcn_{index}_residual")([residual, encoded])
    sequence, context = layers.GRU(
        cfg.hidden_units, return_sequences=True, return_state=True, dropout=cfg.dropout,
        kernel_regularizer=regularizer, name="past_encoder",
    )(encoded)
    projected_future = layers.Dense(64, activation="relu", name="future_projection")(future)
    repeated_context = layers.RepeatVector(cfg.horizon_hours, name="repeat_past_context")(context)
    decoder_input = layers.Concatenate(name="known_future_and_past")([projected_future, repeated_context])
    decoded = layers.GRU(
        cfg.hidden_units, return_sequences=True, dropout=cfg.dropout,
        kernel_regularizer=regularizer, name="future_decoder",
    )(decoder_input, initial_state=context)
    if name == "tcn_gru_attention":
        # Each future query can attend only to the 96 observed past hours.
        attended = layers.MultiHeadAttention(
            num_heads=cfg.attention_heads, key_dim=cfg.hidden_units // cfg.attention_heads,
            dropout=cfg.dropout, name="past_cross_attention",
        )(query=decoded, value=sequence, key=sequence)
        decoded = layers.LayerNormalization(name="attention_norm")(
            layers.Add(name="attention_residual")([decoded, attended]))
    decoded = layers.Dense(64, activation="relu", kernel_regularizer=regularizer,
                           name="output_projection")(decoded)
    # Target is standardized; a nonnegative activation would invalidate its scale.
    output = layers.Dense(1, name="solar_standardized")(decoded)
    model = tf.keras.Model({"past": past, "future": future}, output, name=f"caiso_pv_{name}")
    if not 100_000 <= model.count_params() <= 2_000_000:
        raise ValueError(f"Model has {model.count_params():,} parameters; expected 100,000–2,000,000")
    if compile_model:
        loss = tf.keras.losses.Huber() if cfg.loss == "huber" else tf.keras.losses.MeanSquaredError()
        if cfg.loss not in ("huber", "mse"):
            raise ValueError("loss must be huber or mse")
        model.compile(optimizer=tf.keras.optimizers.Adam(cfg.learning_rate, clipnorm=1.0),
                      loss=loss, metrics=[tf.keras.metrics.MeanAbsoluteError(name="mae_scaled")])
    return model


def configure_tensorflow(seed: int = 42) -> dict[str, Any]:
    tf.keras.utils.set_random_seed(seed)
    devices = tf.config.list_physical_devices("GPU")
    for device in devices:
        tf.config.experimental.set_memory_growth(device, True)
    return {"tensorflow": tf.__version__, "gpus": [device.name for device in devices],
            "seed": seed, "cuda_build": tf.test.is_built_with_cuda()}
