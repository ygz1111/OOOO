"""Load a .keras model and its feature/scaler assets in a separate process."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import tensorflow as tf


def check(run_dir: Path, model_path: Path | None = None, reference_path: Path | None = None,
          *, rtol: float = 1e-4, atol: float = 1e-5) -> dict:
    model_path = model_path or run_dir / "models" / "final.keras"
    reference_path = reference_path or run_dir / "results" / "reload_reference.npz"
    features = json.loads((run_dir / "feature_config.json").read_text(encoding="utf-8"))
    for name in ("past", "future", "target"):
        scaler = json.loads((run_dir / "scalers" / f"{name}_scaler.json").read_text(encoding="utf-8"))
        if scaler.get("fitted_partition") != "train" or not np.isfinite(scaler["mean"]).all() or not np.all(np.asarray(scaler["scale"]) > 0):
            raise ValueError(f"Invalid or non-Train {name} scaler")
    with np.load(reference_path, allow_pickle=False) as reference:
        past, future, expected = reference["past"], reference["future"], reference["expected"]
    if past.shape[1:] != (96, len(features["past_features"])) or future.shape[1:] != (24, len(features["future_features"])):
        raise ValueError("Reload input shapes do not match Feature Config")
    model = tf.keras.models.load_model(model_path, compile=False)
    predicted = model({"past": past, "future": future}, training=False).numpy()
    if predicted.shape != (len(past), 24, 1) or not np.isfinite(predicted).all():
        raise ValueError("Reload prediction shape or finiteness verification failed")
    np.testing.assert_allclose(predicted, expected, rtol=rtol, atol=atol)
    return {"status": "PASS", "new_process": True, "model_path": str(model_path.resolve()),
            "shape": list(predicted.shape), "max_absolute_difference_scaled": float(np.max(np.abs(predicted - expected))),
            "rtol": rtol, "atol": atol, "tensorflow": tf.__version__}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--reference-path", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check(args.run_dir, args.model_path, args.reference_path)
    output = args.output or args.run_dir / "reload_check.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
