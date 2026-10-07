"""Small mathematical checks; values are explicit fixtures, not CAISO observations."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from evaluate import daylight_threshold, export_predictions, grouped_metrics, inverse_target, metrics  # noqa: E402


class EvaluationTests(unittest.TestCase):
    def test_signed_night_values_remain_in_all_day_metrics(self):
        result = metrics(np.array([-5, 0, 10, 100]), np.array([-4, 1, 11, 90]), 20)
        self.assertEqual(result["count"], 4)
        self.assertAlmostEqual(result["mae_mw"], 3.25)
        self.assertEqual(result["daylight_count"], 1)
        self.assertAlmostEqual(result["mape_daylight_pct"], 10)

    def test_daylight_threshold_uses_only_provided_train_positive_values(self):
        threshold = daylight_threshold(np.array([-5, 0, 100, 10000]))
        self.assertAlmostEqual(threshold, 99.01)
        with self.assertRaises(ValueError):
            daylight_threshold(np.array([-5, 0]))

    def test_no_daylight_or_constant_actual_does_not_report_fake_mape_or_r2(self):
        result = metrics(np.array([-1, -1]), np.array([-1, -2]), 1)
        self.assertIsNone(result["mape_daylight_pct"])
        self.assertIsNone(result["r2"])
        self.assertEqual(result["daylight_count"], 0)

    def test_target_inverse_preserves_negative_values_and_rejects_nontrain_scaler(self):
        scaler = {"mean": [0], "scale": [10], "fitted_partition": "train"}
        np.testing.assert_array_equal(inverse_target(np.array([-3]), scaler), [-30])
        scaler["fitted_partition"] = "test"
        with self.assertRaises(ValueError):
            inverse_target(np.array([-3]), scaler)

    def test_horizons_baseline_and_weather_use_identical_index(self):
        target_ts = np.array([1793516400 + np.arange(24) * 3600, 1793602800 + np.arange(24) * 3600])
        actual = np.ones((2, 24, 1)) * 100
        predicted = actual.copy()
        predicted[:, 12, :] += 5
        result = grouped_metrics(actual, predicted, target_ts, 1, np.tile(np.arange(24) * 4, (2, 1)))
        self.assertEqual(result["overall"]["count"], 48)
        self.assertEqual(len(result["horizons"]), 24)
        self.assertEqual(result["horizons"][12]["mae_mw"], 5)
        self.assertTrue(all(point["count"] == 2 for point in result["horizons"]))
        self.assertEqual(sum(value["count"] for value in result["local_periods"].values()), 48)

    def test_misaligned_prediction_or_weather_is_rejected(self):
        actual = np.zeros((2, 24, 1))
        with self.assertRaises(ValueError):
            grouped_metrics(actual, actual[:1], np.zeros((2, 24)), 1)
        with self.assertRaises(ValueError):
            grouped_metrics(actual, actual, np.zeros((2, 24)), 1, np.zeros((1, 24)))

    def test_csv_preserves_dst_repeated_hour_offsets_and_horizon(self):
        # November 1, 2026: 01:00 occurs first PDT then PST, one physical hour apart.
        origin = 1793520000  # 2026-11-01 08:00 UTC.
        times = np.array([origin + np.arange(24) * 3600])
        scratch = SCRIPTS.parent / "results" / "test_tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            path = Path(directory) / "predictions.csv"
            export_predictions(path, np.zeros((1, 24, 1)), np.zeros((1, 24, 1)), times, np.array([origin]))
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 24)
            self.assertIn("01:00:00-07:00", rows[0]["timestamp"])
            self.assertIn("01:00:00-08:00", rows[1]["timestamp"])
            self.assertEqual(rows[-1]["forecast_horizon"], "24")
            with self.assertRaises(FileExistsError):
                export_predictions(path, np.zeros((1, 24, 1)), np.zeros((1, 24, 1)), times, np.array([origin]))


if __name__ == "__main__":
    unittest.main()
