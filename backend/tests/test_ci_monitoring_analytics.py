"""Regression cases for paired observed errors and temporal aggregation."""

import numpy as np
import pytest

from realtime_api.prediction_analytics import PredictionComparator, get_prediction_analytics, prediction_analytics


def row(hour=0, prediction=100, actual=100, model="load"):
    result = {"target_timestamp": f"2026-10-01T{hour:02d}:00:00-04:00", "load_forecast_mw": prediction, "model_type": model}
    if actual is not None:
        result["actual_load_mw"] = actual
    return result


def test_comparison_keeps_actual_pairs_when_middle_hour_is_missing():
    result = PredictionComparator().compare_models([
        row(0, 110, 100), row(1, 9999, None), row(2, 180, 200),
        row(0, 100, 100, "candidate"), row(2, 200, 200, "candidate"),
        row(0, 0, 0, "zero"), row(1, 0, 0, "zero"),
        {"load_forecast_mw": 12},
    ])
    load = result["model_comparison"]["load"]
    assert load["count"] == 2
    assert load["mae"] == 15
    assert load["rmse"] == pytest.approx(np.sqrt(250))
    assert load["mape"] == 10
    assert load["r2"] == pytest.approx(0.9)
    assert result["best_model"] == "candidate"
    assert result["model_comparison"]["zero"]["mape"] == 0
    assert result["model_comparison"]["zero"]["r2"] == 0
    assert result["model_comparison"]["unknown"]["pred_mean"] == 12
    assert result["models_count"] == 4


def test_comparison_with_no_observations_does_not_invent_best_model():
    comparator = PredictionComparator()
    assert "error" in comparator.compare_models([])
    result = comparator.compare_models([row(actual=None), row(prediction=200, actual=None)])
    assert result["best_model"] is None
    assert result["best_mape"] is None
    assert "mae" not in result["model_comparison"]["load"]
    assert result["model_comparison"]["load"]["pred_min"] == 100
    assert result["model_comparison"]["load"]["pred_max"] == 200


@pytest.mark.parametrize("window,key", [("hourly", "0"), ("daily", "2026-10-01"), ("weekly", "3")])
def test_temporal_windows_preserve_valid_observed_rows(window, key):
    rows = [row(0, 110, 100), row(0, 180, 200), row(0, 9999, None), {"load_forecast_mw": 1}, {"target_timestamp": "not a date"}]
    result = PredictionComparator().analyze_temporal_trends(rows, window)
    assert result["total_records"] == 3
    period = result["temporal_analysis"][key]
    assert period["count"] == 2
    assert period["mae"] == 15
    assert period["mape"] == 10
    assert period["pred_mean"] == 145
    assert result["time_range"]["start"] == "2026-10-01T00:00:00-04:00"


def test_temporal_errors_and_forecast_only_statistics():
    comparator = PredictionComparator()
    assert "error" in comparator.analyze_temporal_trends([])
    assert "error" in comparator.analyze_temporal_trends([{"target_timestamp": "bad"}, {}])
    assert "error" in comparator.analyze_temporal_trends([row()], "monthly")
    forecast_only = comparator.analyze_temporal_trends([row(actual=None), row(prediction=200, actual=None)])
    stats = forecast_only["temporal_analysis"]["2026-10-01"]
    assert (stats["count"], stats["pred_min"], stats["pred_max"]) == (2, 100, 200)
    zero = comparator.analyze_temporal_trends([row(prediction=10, actual=0), row(1, 20, 0)])
    assert zero["temporal_analysis"]["2026-10-01"]["mape"] == 0


def test_distribution_uses_forecast_minus_observation_and_masks_zero_actual():
    comparator = PredictionComparator()
    assert "error" in comparator.analyze_error_distribution([row(actual=None)])
    result = comparator.analyze_error_distribution([row(0, 110, 100), row(1, 180, 200), row(2, 5, 0), row(3, 999, None)])
    errors = result["error_distribution"]
    assert errors["count"] == 3
    assert errors["min"] == -20
    assert errors["max"] == 10
    assert errors["mean"] == pytest.approx(-5 / 3)
    assert errors["mae"] == pytest.approx(35 / 3)
    percentage = result["percentage_error_distribution"]
    assert percentage["count"] == 2
    assert percentage["mean"] == 0
    assert percentage["mape"] == 10
    assert len(result["histogram"]["counts"]) == 20
    assert len(result["histogram"]["edges"]) == 21
    assert result["histogram"]["range"][0] < result["histogram"]["range"][1]
    zero = comparator.analyze_error_distribution([row(actual=0, prediction=5)])
    assert zero["percentage_error_distribution"] == {}


def test_load_patterns_exclude_unobserved_rows_and_identify_peak_valley():
    rows = [row(hour, 100, actual) for hour, actual in enumerate([10, 20, 30, 40, 50, 60, 70, 80])]
    rows += [{"target_timestamp": "bad", "actual_load_mw": 99}, {}, row(8, 999, None)]
    result = PredictionComparator().analyze_load_patterns(rows)
    assert result["peak_hours"] == [6, 7]
    assert result["valley_hours"] == [0, 1]
    daily = result["daily_patterns"]["2026-10-01"]
    assert (daily["count"], daily["peak"], daily["valley"]) == (8, 80, 10)
    assert daily["peak_valley_ratio"] == 8
    assert result["analysis_summary"]["total_hours_analyzed"] == 8
    zero = PredictionComparator().analyze_load_patterns([row(actual=0)])
    assert zero["daily_patterns"]["2026-10-01"]["peak_valley_ratio"] == 1
    assert PredictionComparator().analyze_load_patterns([])["peak_hours"] == []


@pytest.mark.parametrize("error,label", [(2, "优秀"), (4, "良好"), (7, "一般"), (11, "需改进")])
def test_comprehensive_report_classifies_real_percentage_error(error, label):
    result = PredictionComparator().generate_comprehensive_report([row(0, 100 + error, 100), row(1, 100 + error, 100)])
    assert result["summary"]["total_predictions"] == 2
    findings = result["summary"]["key_findings"]
    assert any(label in finding for finding in findings)
    assert any("load" in finding for finding in findings)
    assert any("高峰" in finding for finding in findings)
    assert result["error_analysis"]["percentage_error_distribution"]["mape"] == pytest.approx(error)


def test_empty_report_is_explicit_and_singleton_is_reused():
    result = PredictionComparator().generate_comprehensive_report([])
    assert result["summary"]["total_predictions"] == 0
    assert "error" in result["model_comparison"]
    assert get_prediction_analytics() is prediction_analytics
