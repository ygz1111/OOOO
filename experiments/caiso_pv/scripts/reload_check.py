"""Load a .keras model and its feature/scaler assets in a separate process."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import tensorflow as tf

try:
    from .evaluate import inverse_target
except ImportError:
    from evaluate import inverse_target


def check(run_dir: Path, model_path: Path | None = None, reference_path: Path | None = None,
          *, rtol: float = 1e-4, atol: float = 1e-5) -> dict:
    for device in tf.config.list_physical_devices("GPU"):
        if not tf.config.experimental.get_memory_growth(device):
            tf.config.experimental.set_memory_growth(device, True)
    model_path = model_path or run_dir / "models" / "final.keras"
    reference_path = reference_path or run_dir / "results" / "reload_reference.npz"
    features = json.loads((run_dir / "feature_config.json").read_text(encoding="utf-8"))
    scalers = {}
    smoke_only = "SMOKE" in features.get("purpose", "").upper()
    for name in ("past", "future", "target"):
        scaler = json.loads((run_dir / "scalers" / f"{name}_scaler.json").read_text(encoding="utf-8"))
        mean, scale = np.asarray(scaler["mean"], float), np.asarray(scaler["scale"], float)
        columns = ["solar_actual_mw"] if name == "target" else features[f"{name}_features"]
        if (scaler.get("kind") != "standard" or scaler.get("fitted_partition") != "train"
                or mean.shape != (len(columns),) or scale.shape != mean.shape
                or not np.isfinite(mean).all() or not np.isfinite(scale).all() or not np.all(scale > 0)
                or (not smoke_only and scaler.get("feature_names") != columns)):
            raise ValueError(f"Invalid or non-Train {name} scaler")
        scalers[name] = scaler
    with np.load(reference_path, allow_pickle=False) as reference:
        past, future, expected = reference["past"], reference["future"], reference["expected"]
        if not smoke_only:
            if not {"past_raw", "future_raw", "expected_mw"}.issubset(reference.files):
                raise ValueError("Formal reload requires raw Test features and signed expected MW to exercise saved scalers")
            for kind, standardized in (("past", past), ("future", future)):
                transformed = ((reference[f"{kind}_raw"] - np.asarray(scalers[kind]["mean"]))
                               / np.asarray(scalers[kind]["scale"])).astype(np.float32)
                np.testing.assert_allclose(transformed, standardized, rtol=rtol, atol=atol)
                if kind == "past":
                    past = transformed
                else:
                    future = transformed
            expected_mw = reference["expected_mw"]
    if past.shape[1:] != (96, len(features["past_features"])) or future.shape[1:] != (24, len(features["future_features"])):
        raise ValueError("Reload input shapes do not match Feature Config")
    model = tf.keras.models.load_model(model_path, compile=False)
    predicted = model({"past": past, "future": future}, training=False).numpy()
    if predicted.shape != (len(past), 24, 1) or not np.isfinite(predicted).all():
        raise ValueError("Reload prediction shape or finiteness verification failed")
    np.testing.assert_allclose(predicted, expected, rtol=rtol, atol=atol)
    mw_difference = None
    atol_mw = float(atol * scalers["target"]["scale"][0])
    if not smoke_only:
        predicted_mw = inverse_target(predicted, scalers["target"])
        np.testing.assert_allclose(predicted_mw, expected_mw, rtol=rtol, atol=atol_mw)
        mw_difference = float(np.max(np.abs(predicted_mw - expected_mw)))
    return {"status": "PASS", "new_process": True, "model_path": str(model_path.resolve()),
            "target_name": "CAISO OASIS Solar Actual Generation",
            "verification_basis": "scaled random-tensor smoke" if smoke_only else "raw Test features -> saved Train scalers -> model -> signed MW",
            "shape": list(predicted.shape), "max_absolute_difference_scaled": float(np.max(np.abs(predicted - expected))),
            "max_absolute_difference_mw": mw_difference,
            "rtol": rtol, "atol": atol, "atol_scaled": atol, "atol_mw": atol_mw,
            "tensorflow": tf.__version__}


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
