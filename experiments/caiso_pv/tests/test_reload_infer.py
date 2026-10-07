"""Saved-scaler/reload checks on mathematical fixtures; never official training."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import tensorflow as tf

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from infer import _transform, predict  # noqa: E402
from models import build_model  # noqa: E402
from reload_check import check  # noqa: E402


class SavedAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = SCRIPTS.parent / "results" / "test_tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=scratch)
        cls.asset_dir = Path(cls.temporary.name)
        for directory in ("models", "results", "scalers"):
            (cls.asset_dir / directory).mkdir()
        features = {"past_features": ["solar_actual_mw", "temperature"], "future_features": ["temperature", "cloud"]}
        (cls.asset_dir / "feature_config.json").write_text(json.dumps(features), encoding="utf-8")
        cls.scalers = {
            "past": {"mean": [100, 5], "scale": [10, 2], "feature_names": features["past_features"]},
            "future": {"mean": [50, 5], "scale": [5, 3], "feature_names": features["future_features"]},
            "target": {"mean": [40], "scale": [20], "feature_names": ["solar_actual_mw"]},
        }
        for name, scaler in cls.scalers.items():
            scaler.update(kind="standard", fitted_partition="train")
            (cls.asset_dir / "scalers" / f"{name}_scaler.json").write_text(json.dumps(scaler), encoding="utf-8")
        rng = np.random.default_rng(42)
        cls.past = rng.normal(size=(2, 96, 2)).astype(np.float32)
        cls.future = rng.normal(size=(2, 24, 2)).astype(np.float32)
        cls.past_raw = cls.past.astype(float) * [10, 2] + [100, 5]
        cls.future_raw = cls.future.astype(float) * [5, 3] + [50, 5]
        model = build_model("gru", 2, 2)
        layer = model.get_layer("solar_standardized")
        kernel, bias = layer.get_weights()
        layer.set_weights([np.zeros_like(kernel), np.full_like(bias, -3)])
        model.save(cls.asset_dir / "models" / "final.keras")
        cls.expected = model({"past": cls.past, "future": cls.future}, training=False).numpy()
        cls.reference = cls.asset_dir / "results" / "reload_reference.npz"
        np.savez(cls.reference, past=cls.past, future=cls.future, expected=cls.expected,
                 past_raw=cls.past_raw, future_raw=cls.future_raw, expected_mw=cls.expected * 20 + 40)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_raw_features_saved_scalers_and_signed_mw_match_in_new_process(self):
        process = subprocess.run([sys.executable, str(SCRIPTS / "reload_check.py"), "--run-dir", str(self.asset_dir)],
                                 capture_output=True, text=True, check=True)
        result = json.loads((self.asset_dir / "reload_check.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "PASS")
        self.assertIn("raw Test features", result["verification_basis"])
        self.assertEqual(result["max_absolute_difference_mw"], 0)
        self.assertIn('"new_process": true', process.stdout)
        np.testing.assert_array_equal(predict(self.asset_dir, self.past_raw, self.future_raw), np.full((2, 24, 1), -20))

    def test_raw_feature_scaler_mismatch_cannot_pass_reload(self):
        bad = self.asset_dir / "results" / "bad_reference.npz"
        np.savez(bad, past=self.past, future=self.future, expected=self.expected,
                 past_raw=self.past_raw + 1, future_raw=self.future_raw, expected_mw=self.expected * 20 + 40)
        with self.assertRaises(AssertionError):
            check(self.asset_dir, reference_path=bad)

    def test_infinite_scaler_is_rejected_before_inference(self):
        scaler = {**self.scalers["past"], "scale": [float("inf"), 2]}
        with self.assertRaises(ValueError):
            _transform(self.past_raw, scaler)

    def test_mw_absolute_tolerance_tracks_saved_target_units_at_zero_mw(self):
        # Center mathematical output at 0 MW, so relative tolerance cannot hide a unit error.
        scaler_path = self.asset_dir / "scalers" / "target_scaler.json"
        original = scaler_path.read_text(encoding="utf-8")
        scaler_path.write_text(json.dumps({**self.scalers["target"], "mean": [60]}), encoding="utf-8")
        reference = self.asset_dir / "results" / "tolerance_reference.npz"
        try:
            for difference_mw, passes in ((0.00015, True), (0.00030, False)):
                np.savez(reference, past=self.past, future=self.future, expected=self.expected,
                         past_raw=self.past_raw, future_raw=self.future_raw,
                         expected_mw=np.full_like(self.expected, difference_mw))
                if passes:
                    result = check(self.asset_dir, reference_path=reference)
                    self.assertEqual(result["rtol"], 1e-4)
                    self.assertEqual(result["atol"], result["atol_scaled"])
                    self.assertEqual(result["atol_scaled"], 1e-5)
                    self.assertAlmostEqual(result["atol_mw"], 0.0002)
                else:
                    with self.assertRaises(AssertionError):
                        check(self.asset_dir, reference_path=reference)
        finally:
            scaler_path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
