"""Read-only production-weight checks for causal, one-hour load replay."""
import numpy as np
import pandas as pd
import pytest

from models.tensorflow_load import tf_split_models as M
from realtime_api.tf_split_service import TFSplitService
from realtime_api.tf_realtime_feature_provider import (
    LOAD_FUTURE_COLS, LOAD_PAST_COLS, TFRealtimeFeatureProvider,
)


@pytest.fixture(scope="module")
def service():
    result = TFSplitService()
    result.load_models()
    return result


@pytest.fixture
def inputs(service):
    frame = service._frame
    pos = int(frame.index[frame.ts_local == service._origin][0])
    return frame.iloc[pos - 167:pos + 1].copy(), frame.iloc[pos + 1:pos + 25].copy()


def test_first_step_shares_loaded_layers_and_weight_objects(service):
    original, one = service._load_model, service._load_first_step_model
    for name in ("past_norm", "encoder_bi_gru", "encoder_gru", "future_norm",
                 "future_projection", "decoder_input", "decoder_gru", "decoder_dense", "load"):
        assert one.get_layer(name) is original.get_layer(name)
    assert one.count_params() == original.count_params()
    assert {id(weight) for weight in one.weights} == {id(weight) for weight in original.weights}
    assert one.input_shape == [(None, 168, len(M.LOAD_PAST_COLS)), (None, 1, len(M.FUTURE_COLS))]
    assert one.output_shape == (None, 1, 1)
    assert original.input_shape[1][1] == 24


def test_actual_weights_first_step_matches_full_output_and_ignores_later_future(service, inputs):
    past, future = inputs
    lp = service._load_sp.transform(past[M.LOAD_PAST_COLS]).astype("float32")[None]
    ff = service._load_sf.transform(future[M.FUTURE_COLS]).astype("float32")[None]
    full = service._load_model.predict([lp, ff], verbose=0)
    one = service._load_first_step_model.predict([lp, ff[:, :1]], verbose=0)
    changed = ff.copy()
    changed[:, 1:] += np.random.default_rng(42).normal(0, 10, changed[:, 1:].shape).astype("float32")
    perturbed = service._load_model.predict([lp, changed], verbose=0)
    assert np.isfinite(one).all()
    np.testing.assert_allclose(one[:, 0], full[:, 0], rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(perturbed[:, 0], full[:, 0], rtol=1e-5, atol=1e-6)
    assert np.max(np.abs(perturbed[:, 1:] - full[:, 1:])) > 1e-4
    public_one = service.predict_load_first_step_features(past, future.iloc[:1])
    public_full = service.predict_task_features("load", past, future)
    assert len(public_one["hourly"]) == 1
    assert public_one["hourly"][0]["timestamp"] == public_full["hourly"][0]["timestamp"]
    assert public_one["hourly"][0]["load_forecast_mw"] == pytest.approx(
        public_full["hourly"][0]["load_forecast_mw"], abs=0.1)
    print(f"first-step raw max delta={np.max(np.abs(one[:, 0] - full[:, 0])):.9g}; "
          f"MW={public_one['hourly'][0]['load_forecast_mw']} vs {public_full['hourly'][0]['load_forecast_mw']}")


@pytest.mark.parametrize("case", ["past_feature", "future_feature", "nan", "inf",
                                   "past_time", "duplicate", "off_hour", "target_gap", "zero", "two"])
def test_first_step_rejects_missing_invalid_or_misaligned_inputs_before_inference(service, inputs, monkeypatch, case):
    past, full_future = inputs
    future = full_future.iloc[:1].copy()
    if case == "past_feature":
        past = past.drop(columns=["RT_Demand"])
    elif case == "future_feature":
        future = future.drop(columns=["DA_Demand"])
    elif case in ("nan", "inf"):
        future.loc[:, "DA_LMP"] = np.nan if case == "nan" else np.inf
    elif case == "past_time":
        past = past.drop(columns=["ts_local"])
    elif case == "duplicate":
        past.iloc[-1, past.columns.get_loc("ts_local")] = past.iloc[-2].ts_local
    elif case == "off_hour":
        future.loc[:, "ts_local"] += pd.Timedelta(minutes=30)
    elif case == "target_gap":
        future.loc[:, "ts_local"] += pd.Timedelta(hours=1)
    elif case == "zero":
        future = future.iloc[:0]
    else:
        future = full_future.iloc[:2]
    monkeypatch.setattr(service._load_first_step_model, "predict", lambda *a, **k: pytest.fail("invalid input reached inference"))
    with pytest.raises(ValueError):
        service.predict_load_first_step_features(past, future)


@pytest.mark.parametrize("target", ["2026-03-08 03:00", "2026-11-01 02:00"])
def test_first_step_rejects_dst_ambiguous_or_nonexistent_intervals(service, inputs, monkeypatch, target):
    past, full_future = inputs
    future = full_future.iloc[:1].copy()
    target = pd.Timestamp(target)
    past.loc[:, "ts_local"] = pd.date_range(target - pd.Timedelta(hours=168), periods=168, freq="h")
    future.loc[:, "ts_local"] = target
    monkeypatch.setattr(service._load_first_step_model, "predict", lambda *a, **k: pytest.fail("DST input reached inference"))
    with pytest.raises(ValueError, match="夏令时"):
        service.predict_load_first_step_features(past, future)


@pytest.mark.parametrize("output", [np.ones((1, 24, 1)), np.full((1, 1, 1), np.nan)])
def test_first_step_rejects_invalid_model_output(service, inputs, monkeypatch, output):
    past, future = inputs
    monkeypatch.setattr(service._load_first_step_model, "predict", lambda *a, **k: output)
    with pytest.raises(ValueError, match="输出形状异常或包含非有限值"):
        service.predict_load_first_step_features(past, future.iloc[:1])


def test_single_hour_replay_does_not_require_unpublished_remaining_23_hours():
    provider = TFRealtimeFeatureProvider()
    target = pd.Timestamp("2026-10-01 05:00")
    index = pd.date_range(target - pd.Timedelta(hours=200), target + pd.Timedelta(hours=23), freq="h")
    market = pd.DataFrame({"ts_local": index, **{name: 1. for name in set(LOAD_PAST_COLS + LOAD_FUTURE_COLS)}})
    market.loc[market.ts_local > target, "DA_Demand"] = np.nan
    one = provider._build_load_backtest_windows(market, target, hours=1, future_hours=1)
    assert len(one) == 1 and len(one[0]["future"]) == 1
    assert one[0]["future"][0]["ts_local"] == target
    assert pd.Timestamp(one[0]["past"][-1]["ts_local"]) == target - pd.Timedelta(hours=1)
    assert provider._build_load_backtest_windows(market, target, hours=1, skip_incomplete=True) == []
    market.loc[market.ts_local == target, "DA_Demand"] = np.nan
    with pytest.raises(ValueError, match="不完整"):
        provider._build_load_backtest_windows(market, target, hours=1, future_hours=1)


@pytest.mark.parametrize("target", ["2026-03-08 03:00", "2026-11-01 02:00"])
def test_single_hour_provider_rejects_dst_before_model_execution(target):
    provider = TFRealtimeFeatureProvider()
    target = pd.Timestamp(target)
    index = pd.date_range(target - pd.Timedelta(hours=200), target, freq="h")
    market = pd.DataFrame({"ts_local": index, **{name: 1. for name in set(LOAD_PAST_COLS + LOAD_FUTURE_COLS)}})
    with pytest.raises(ValueError, match="夏令时"):
        provider._build_load_backtest_windows(market, target, hours=1, future_hours=1)
