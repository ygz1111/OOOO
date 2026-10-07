"""Leakage/approval guards on miniature metadata fixtures; never fits a model."""
import argparse
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from train import _report, inside_experiment, train, validate_dataset  # noqa: E402
from models import MODEL_NAMES, ModelConfig  # noqa: E402
from evaluate import grouped_metrics, write_json  # noqa: E402


def fixture():
    # Mathematical timestamps and zero tensors only; not CAISO data or a training result.
    base = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    iso = lambda value: datetime.fromtimestamp(value, timezone.utc).isoformat()
    features = {"past_hours": 96, "horizon_hours": 24, "timezone": "America/Los_Angeles",
                "past_features": ["solar_actual_mw", "temperature"], "future_features": ["temperature"],
                "future_weather_kind": "forecast_single_run"}
    split = {"partitions": {}}
    arrays = {}
    for index, name in enumerate(("train", "val", "test")):
        origins = base + (index * 48 + np.arange(2)) * 3600
        targets = origins[:, None] + np.arange(24)[None, :] * 3600
        arrays.update({f"X_past_{name}": np.zeros((2, 96, 2), np.float32),
                       f"X_future_{name}": np.zeros((2, 24, 1), np.float32),
                       f"y_{name}": np.zeros((2, 24, 1), np.float32),
                       f"baseline_{name}": np.zeros((2, 24, 1), np.float32),
                       f"origin_ts_{name}": origins, f"target_ts_{name}": targets,
                       f"forecast_available_upper_bound_ts_{name}": targets - 48 * 3600})
        split["partitions"][name] = {"start_utc": iso(base + (index * 48 - (96 if index == 0 else 0)) * 3600),
                                     "end_exclusive_utc": iso(base + (index + 1) * 48 * 3600), "samples": 2}
    scalers = {}
    for name, columns in (("past", features["past_features"]), ("future", features["future_features"]), ("target", ["solar_actual_mw"])):
        scalers[name] = {"kind": "standard", "fitted_partition": "train", "feature_names": columns,
                         "mean": [0] * len(columns), "scale": [1] * len(columns),
                         "fitted_start": split["partitions"]["train"]["start_utc"],
                         "fitted_end": split["partitions"]["train"]["end_exclusive_utc"]}
    return arrays, features, scalers, split


class TrainingGuardTests(unittest.TestCase):
    def test_complete_chronological_fixture_passes_without_training(self):
        validate_dataset(*fixture())

    def test_all_twenty_four_labels_must_stay_in_partition(self):
        arrays, features, scalers, split = fixture()
        arrays["origin_ts_train"][1] += 46 * 3600
        arrays["target_ts_train"][1] += 46 * 3600
        with self.assertRaisesRegex(ValueError, "half-open partition"):
            validate_dataset(arrays, features, scalers, split)

    def test_forecast_after_origin_is_rejected(self):
        arrays, features, scalers, split = fixture()
        arrays["forecast_available_upper_bound_ts_val"][0, 2] = arrays["origin_ts_val"][0] + 1
        with self.assertRaisesRegex(ValueError, "available at each forecast origin"):
            validate_dataset(arrays, features, scalers, split)

    def test_future_actual_solar_feature_is_rejected(self):
        arrays, features, scalers, split = fixture()
        features["future_features"] = ["solar_actual_mw"]
        with self.assertRaisesRegex(ValueError, "future actual Solar"):
            validate_dataset(arrays, features, scalers, split)

    def test_baseline_cannot_use_a_different_origin_or_scaled_unit(self):
        arrays, features, scalers, split = fixture()
        arrays["baseline_val"][0, 0, 0] = 10
        with self.assertRaisesRegex(ValueError, "previous 24 physical-hour Solar MW"):
            validate_dataset(arrays, features, scalers, split)

    def test_nontrain_scaler_or_validation_fitting_interval_is_rejected(self):
        arrays, features, scalers, split = fixture()
        invalid = copy.deepcopy(scalers)
        invalid["target"]["fitted_partition"] = "val"
        with self.assertRaisesRegex(ValueError, "Train-only"):
            validate_dataset(arrays, features, invalid, split)
        invalid = copy.deepcopy(scalers)
        invalid["future"]["fitted_end"] = split["partitions"]["val"]["end_exclusive_utc"]
        with self.assertRaisesRegex(ValueError, "Train fitting interval"):
            validate_dataset(arrays, features, invalid, split)

    def test_unapproved_data_cannot_create_a_formal_run(self):
        scratch = SCRIPTS.parent / "results" / "test_tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            directory = Path(directory)
            (directory / "data_approval.json").write_text(json.dumps({"status": "pending"}), encoding="utf-8")
            destination = directory / "must_not_exist"
            with self.assertRaisesRegex(ValueError, "confirmed before formal training"):
                train(argparse.Namespace(dataset_dir=directory, run_dir=destination))
            self.assertFalse(destination.exists())

    def test_assets_outside_experiment_or_existing_json_are_rejected(self):
        with self.assertRaises(ValueError):
            inside_experiment(SCRIPTS.parents[3] / "models" / "forbidden")
        scratch = SCRIPTS.parent / "results" / "test_tmp"
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            destination = Path(directory) / "metadata.json"
            write_json(destination, {"fixture": True})
            with self.assertRaises(FileExistsError):
                write_json(destination, {"fixture": False})

    def test_report_uses_canonical_label_and_keeps_online_readiness_separate(self):
        arrays, features, _, split = fixture()
        actual = np.ones((2, 24, 1)) * 10  # Explicit mathematical report fixture, not observations.
        grouped = grouped_metrics(actual, actual, arrays["target_ts_test"], 1, np.zeros((2, 24)))
        for boundary in split["partitions"].values():
            boundary.update(start_local=boundary["start_utc"], end_exclusive_local=boundary["end_exclusive_utc"], target_points=48)
        config = {**ModelConfig().to_dict(), "target_name": "CAISO OASIS Solar Actual Generation",
                  "approved_label_definition": "MATHEMATICAL REPORT FIXTURE ONLY", "selected_model": "gru",
                  "daylight_threshold_mw": 1, "effective_batch_size": 64, "training_seconds": 1,
                  "dataset_sha256": "report-fixture-not-official-data", "max_epochs": 100, "patience": 12,
                  "candidates": {name: {"best_epoch": 1, "parameters": 100000, "training_seconds": 1} for name in MODEL_NAMES}}
        scratch = SCRIPTS.parent / "results" / "test_tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            directory = Path(directory)
            write_json(directory / "training_history.json", {name: {"keras_history": {"loss": [1], "val_loss": [1]}} for name in MODEL_NAMES})
            _report(directory, config, split, features, {"baseline": grouped, "models": {name: grouped for name in MODEL_NAMES}})
            report = (directory / "TRAINING_REPORT.md").read_text(encoding="utf-8")
            self.assertIn("CAISO OASIS Solar Actual Generation", report)
            self.assertIn("MATHEMATICAL REPORT FIXTURE ONLY", report)
            self.assertIn("是否已具备实时接入条件：尚未验证", report)
            self.assertIn("morning_06_10", report)
            self.assertIn("high_change_ge_25pp_per_hour", report)
            self.assertNotIn("太阳能热", report)


if __name__ == "__main__":
    unittest.main()
