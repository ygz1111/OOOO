"""Random-tensor mathematical smoke only. This is NOT a CAISO training result."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import tensorflow as tf

try:
    from .models import MODEL_NAMES, build_model, configure_tensorflow
except ImportError:
    from models import MODEL_NAMES, build_model, configure_tensorflow

ROOT = Path(__file__).resolve().parents[1]


def smoke(output: Path) -> dict:
    output = output.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError("Smoke assets must remain inside the independent experiment")
    output.mkdir(parents=True, exist_ok=False)
    for name in ("models", "results", "scalers"):
        (output / name).mkdir()
    hardware = configure_tensorflow(42)
    past_features, future_features = 20, 18
    rng = np.random.default_rng(42)
    past = rng.normal(size=(2, 96, past_features)).astype(np.float32)
    future = rng.normal(size=(2, 24, future_features)).astype(np.float32)
    target = rng.normal(size=(2, 24, 1)).astype(np.float32)
    feature_config = {"past_features": [f"smoke_past_{index}" for index in range(past_features)],
                      "future_features": [f"smoke_future_{index}" for index in range(future_features)],
                      "past_hours": 96, "horizon_hours": 24,
                      "purpose": "RANDOM TENSOR MATHEMATICAL SMOKE; not official data or a trained final model"}
    (output / "feature_config.json").write_text(json.dumps(feature_config, indent=2), encoding="utf-8")
    for name, count in (("past", past_features), ("future", future_features), ("target", 1)):
        (output / "scalers" / f"{name}_scaler.json").write_text(json.dumps({
            "kind": "standard", "mean": [0] * count, "scale": [1] * count,
            "fitted_partition": "train", "purpose": "Identity smoke fixture; NOT a data-fitted production scaler"}), encoding="utf-8")
    report = {"purpose": "Random tensors: shape/finite gradients/save-load only; NO formal training metrics", "hardware": hardware, "models": {}}
    for name in MODEL_NAMES:
        tf.keras.backend.clear_session()
        model = build_model(name, past_features, future_features)
        with tf.GradientTape() as tape:
            prediction = model({"past": past, "future": future}, training=True)
            loss = tf.reduce_mean(tf.square(prediction - target))
        gradients = tape.gradient(loss, model.trainable_variables)
        if prediction.shape != (2, 24, 1) or not np.isfinite(prediction.numpy()).all():
            raise ValueError(f"{name}: invalid output shape/values")
        if any(gradient is None or not bool(tf.reduce_all(tf.math.is_finite(gradient))) for gradient in gradients):
            raise ValueError(f"{name}: disconnected or nonfinite gradients")
        model.optimizer.apply_gradients(zip(gradients, model.trainable_variables))
        expected = model({"past": past, "future": future}, training=False).numpy()
        destination = output / "models" / f"{name}.keras"
        model.save(destination)
        reference = output / "results" / f"{name}_reference.npz"
        np.savez(reference, past=past, future=future, expected=expected)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "reload_check.py"),
                        "--run-dir", str(output), "--model-path", str(destination),
                        "--reference-path", str(reference), "--output", str(output / "results" / f"{name}_reload.json")], check=True)
        report["models"][name] = {"parameters": model.count_params(), "shape": list(expected.shape),
                                  "finite_gradients": True, "new_process_reload": "PASS"}
    (output / "SMOKE_ONLY.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "smoke" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    print(json.dumps(smoke(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
