"""Focused checks for offline interval calibration and reference metrics."""
from pathlib import Path
import importlib.util

import numpy as np
import pytest

SPEC = importlib.util.spec_from_file_location("candidate_evaluation", Path(__file__).parents[1] / "evaluate_prediction_candidates.py")
EVALUATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVALUATION)


def quantiles(n):
    return np.broadcast_to([-1.0, 0.0, 1.0], (n, 24, 3)).copy()


def test_calibration_can_widen_narrow_intervals_and_preserve_signed_median():
    actual = np.full((200, 24), 5.0)
    q = quantiles(200) - 3
    offset = EVALUATION.fit_offsets(actual, q, by_lead=False)
    assert offset["all"] > 1
    widened = EVALUATION.apply_offsets(q, offset)
    assert np.array_equal(widened[..., 1], q[..., 1])
    assert np.all(widened[..., 0] <= widened[..., 1])
    assert np.all(widened[..., 1] <= widened[..., 2])
    assert EVALUATION.interval_metrics(actual, widened)["coverage"] == 1


def test_chronological_validation_slices_do_not_share_target_hours():
    origins = np.arange(1000, 1240)
    fit, selection = EVALUATION.validation_slices(origins)
    assert max(origins[fit]) + 24 < min(origins[selection]) + 1
    assert not np.any(fit & selection)
    assert np.sum(~(fit | selection)) == 23


def test_candidate_rejected_when_later_validation_improvement_is_absent():
    actual = np.full((240, 24), 5.0)
    actual[180:] = 0
    result = EVALUATION.select_calibration(actual, quantiles(240), np.arange(240))
    assert result["selected_candidate"] is None
    assert result["selected_offsets_USD_MWh"] is None
    assert not any(c["eligible_on_validation"] for c in result["candidates"])


def test_candidate_selected_by_held_out_validation_without_test_input():
    result = EVALUATION.select_calibration(np.full((240, 24), 2.0), quantiles(240), np.arange(240))
    assert result["selected_candidate"] is not None
    assert result["candidates"][0]["selection_metrics"]["interval_score"] < result["raw_selection"]["interval_score"]


def test_empty_diagnostic_group_is_missing_rather_than_zero_accuracy():
    result = EVALUATION.regression_metrics(np.ones((2, 24)), np.zeros((2, 24)), np.zeros((2, 24), dtype=bool))
    assert result["points"] == 0
    assert result["MAE"] is None


def test_invalid_outputs_are_not_silently_counted_as_predictions():
    with pytest.raises(ValueError, match="Finite aligned"):
        EVALUATION.interval_metrics(np.ones((1, 24)), np.full((1, 24, 3), np.nan))
    with pytest.raises(ValueError, match="ordered"):
        EVALUATION.interval_metrics(np.ones((1, 24)), np.broadcast_to([2, 1, 0], (1, 24, 3)))

