import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dataset import build_dataset, calendar_split_info, save_dataset, select_future_window, validate_labels
from features import FeatureTable
from weather_data import TIMEZONE


def fixtures():
    start = pd.Timestamp("2024-10-17", tz=TIMEZONE).tz_convert("UTC")
    end = pd.Timestamp("2024-11-07", tz=TIMEZONE).tz_convert("UTC")
    axis = pd.date_range(start, end, freq="h", inclusive="left")
    labels = pd.DataFrame({"timestamp": axis, "interval_end_utc": axis+pd.Timedelta(hours=1),
        "solar_actual_mw": np.arange(len(axis), dtype=float), "source_kind": "actual",
        "source_id": "caiso_oasis_solar_actual", "unit": "MW",
        "sample_count": 1, "source_resolution_minutes": 60, "is_complete": True})
    weather = pd.DataFrame({"interval_start_utc": axis, "shortwave_radiation__mean": np.arange(len(axis),dtype=float),
        "cloud_cover__mean": 30.0, "complete_weather": True, "source_kind": "historical_reanalysis",
        "model": "era5", "batch_id": "history", "availability_upper_bound_utc": pd.NaT, "availability_basis": "retrospective"})
    future = weather.copy()
    future["source_kind"] = "forecast_fixed_lead_day2"
    future["model"] = "gfs_global"
    future["batch_id"] = "previous_day2"
    future["availability_upper_bound_utc"] = axis-pd.Timedelta(hours=41)
    future["availability_basis"] = "fixed_48h_offset_plus_assumed_6h_release_delay"
    names = ("shortwave_radiation__mean", "cloud_cover__mean")
    return labels, FeatureTable(weather,names), FeatureTable(future,names)


def build(labels, history, future):
    return build_dataset(labels, history, future, weather_kind="forecast_fixed_lead_day2", validation_days=2, test_days=3)


def test_shapes_utc24_hours_partition_containment_and_raw_lag_baseline():
    labels, history, future = fixtures()
    arrays, config, splits = build(labels,history,future)
    observed = labels.set_index("timestamp").solar_actual_mw
    for name in ("train","val","test"):
        assert arrays[f"X_past_{name}"].shape[1:] == (96,3)
        assert arrays[f"X_future_{name}"].shape[1:] == (24,2)
        assert arrays[f"y_{name}"].shape[1:] == (24,1)
        assert arrays[f"X_past_{name}"].dtype == np.float32
        target = arrays[f"target_ts_{name}"]
        assert (np.diff(target,axis=1)==3600).all()
        assert (target[:,0] == arrays[f"origin_ts_{name}"]).all()
        boundary = splits["partitions"][name]
        assert target.min() >= pd.Timestamp(boundary["start_utc"]).timestamp()
        assert target.max()+3600 <= pd.Timestamp(boundary["end_exclusive_utc"]).timestamp()
        assert (arrays[f"forecast_available_upper_bound_ts_{name}"] <= arrays[f"origin_ts_{name}"][:,None]).all()
        lag_axis = pd.to_datetime(target[0]-86400,unit="s",utc=True)
        np.testing.assert_equal(arrays[f"baseline_{name}"][0,:,0], observed.reindex(lag_axis).to_numpy())
    assert config["future_weather_kind"] == "forecast_fixed_lead_day2"
    assert config["solar_label_availability_verified"] is False
    assert all(s["fitted_partition"] == "train" for s in config["scalers"].values())


def test_scalers_do_not_fit_validation_or_test_values():
    labels, history, future = fixtures()
    _, old, splits = build(labels,history,future)
    boundary = pd.Timestamp(splits["partitions"]["val"]["start_utc"])
    labels.loc[labels.timestamp >= boundary, "solar_actual_mw"] += 1_000_000
    history.frame.loc[history.frame.interval_start_utc >= boundary, "shortwave_radiation__mean"] += 1_000_000
    future.frame.loc[future.frame.interval_start_utc >= boundary, "shortwave_radiation__mean"] += 1_000_000
    _, new, _ = build(labels,history,future)
    assert old["scalers"] == new["scalers"]


def test_missing_hour_rejects_overlapping_windows_instead_of_jumping_or_filling_zero():
    labels, history, future = fixtures()
    arrays, _, _ = build(labels,history,future)
    gap = labels.timestamp.iloc[150]
    labels = labels.drop(index=150)
    reduced, _, splits = build(labels,history,future)
    assert len(reduced["y_train"]) < len(arrays["y_train"])
    origins = reduced["origin_ts_train"]
    assert not ((origins-96*3600 <= gap.timestamp()) & (origins+24*3600 > gap.timestamp())).any()
    assert splits["partitions"]["train"]["rejected_windows"]["missing_labels_or_history"] > 0


def test_future_observed_weather_mixed_kinds_and_unavailable_forecasts_are_rejected():
    labels, history, future = fixtures()
    for kind in ("historical_reanalysis", "historical_analysis"):
        future.frame["source_kind"] = kind
        with pytest.raises(ValueError, match="prohibited"):
            build(labels,history,future)
    future.frame["source_kind"] = "forecast_fixed_lead_day2"
    future.frame.loc[future.frame.index[0],"source_kind"] = "forecast_single_run"
    with pytest.raises(ValueError,match="prohibited"):
        build(labels,history,future)
    future.frame["source_kind"] = "forecast_fixed_lead_day2"
    future.frame["availability_upper_bound_utc"] = future.frame.interval_start_utc+pd.Timedelta(hours=1)
    with pytest.raises(ValueError,match="No admissible train"):
        build(labels,history,future)


def test_single_run_requires_all24_hours_from_one_available_batch():
    _, _, future = fixtures()
    future.frame["source_kind"] = "forecast_single_run"
    times = pd.DatetimeIndex(future.frame.interval_start_utc.iloc[100:124])
    future.frame["availability_upper_bound_utc"] = times[0]-pd.Timedelta(hours=1)
    future.frame["batch_id"] = "runA"
    future.frame.loc[future.frame.index[112:124], "batch_id"] = "runB"
    assert select_future_window(future,times,times[0],"forecast_single_run") is None
    future.frame["batch_id"] = "runA"
    assert len(select_future_window(future,times,times[0],"forecast_single_run")) == 24


def test_dst_complete_local_date_counts_and_hourly_complete_sample_count1_is_valid():
    labels, _, _ = fixtures()
    valid = validate_labels(labels)
    assert valid.eligible.all()
    local = valid.index.tz_convert(TIMEZONE)
    assert (local.date == pd.Timestamp("2024-11-03").date()).sum() == 25
    info = calendar_split_info(valid,validation_days=2,test_days=3)
    test = info["partitions"]["test"]
    assert test["start_local"].startswith("2024-11-04T00:00:00-08:00")
    assert test["end_exclusive_local"].startswith("2024-11-07T00:00:00-08:00")
    labels["sample_count"] = 3  # Parser qualification takes priority over an assumed 12-point count.
    assert validate_labels(labels).eligible.all()


def test_spring23_hour_day_is_complete_and_24physicalhour_windows_are_retained():
    labels, history, future = fixtures()
    axis = pd.date_range(pd.Timestamp("2024-03-01",tz=TIMEZONE).tz_convert("UTC"),
                         pd.Timestamp("2024-03-22",tz=TIMEZONE).tz_convert("UTC"),freq="h",inclusive="left")
    labels=labels.iloc[:len(axis)].copy();labels["timestamp"]=axis;labels["interval_end_utc"]=axis+pd.Timedelta(hours=1)
    history.frame=history.frame.iloc[:len(axis)].copy();history.frame["interval_start_utc"]=axis
    future.frame=future.frame.iloc[:len(axis)].copy();future.frame["interval_start_utc"]=axis
    future.frame["availability_upper_bound_utc"]=axis-pd.Timedelta(hours=41)
    valid=validate_labels(labels)
    assert (valid.index.tz_convert(TIMEZONE).date==pd.Timestamp("2024-03-10").date()).sum()==23
    arrays,config,_=build(labels,history,future)
    assert (np.diff(arrays["target_ts_train"],axis=1)==3600).all()
    assert config["effective_admitted_origins"]["train"]["first_origin_utc"]!=config["requested_label_axis_start_utc"]


def test_future_solar_cannot_be_added_as_a_feature():
    labels, history, future=fixtures()
    history.frame["solar_actual_mw"]=1.0;future.frame["solar_actual_mw"]=1.0
    history.feature_names+=("solar_actual_mw",);future.feature_names+=("solar_actual_mw",)
    with pytest.raises(ValueError,match="future Solar is prohibited"):
        build(labels,history,future)


def test_dataset_writer_refuses_outside_experiment_and_existing_artifacts(tmp_path):
    with pytest.raises(ValueError,match="inside"):
        save_dataset({}, {"scalers": {}}, {}, tmp_path)


def test_official_label_sources_cannot_be_mixed_and_negative_valid_measurements_are_preserved():
    labels, _, _ = fixtures()
    labels.loc[0, "solar_actual_mw"] = -2.0
    validated = validate_labels(labels)
    assert validated.solar_actual_mw.iloc[0] == -2.0
    assert validated.eligible.iloc[0]
    labels.loc[0, "source_id"] = "caiso_outlook_solar_actual"
    with pytest.raises(ValueError, match="never mix"):
        validate_labels(labels)


def test_joint_source_edges_anchor_calendar_splits_without_dropping_internal_missing_hours():
    labels, history, future = fixtures()
    first = pd.Timestamp("2024-10-19", tz=TIMEZONE).tz_convert("UTC")
    history_end = pd.Timestamp("2024-11-05", tz=TIMEZONE).tz_convert("UTC")
    future_end = pd.Timestamp("2024-11-06", tz=TIMEZONE).tz_convert("UTC")
    history.frame.loc[(history.frame.interval_start_utc < first) | (history.frame.interval_start_utc >= history_end), "complete_weather"] = False
    future.frame.loc[(future.frame.interval_start_utc < first) | (future.frame.interval_start_utc >= future_end), "complete_weather"] = False
    # A single internal missing hour must reject its overlapping windows,
    # while the calendar partitions continue across that day and month.
    gap = pd.Timestamp("2024-11-03T09:00:00Z")  # Repeated LA 01:00 hour, fold=1.
    future.frame.loc[future.frame.interval_start_utc.eq(gap), "complete_weather"] = False
    arrays, config, splits = build(labels, history, future)
    assert splits["first_complete_local_date"] == "2024-10-19"
    assert splits["latest_complete_local_date"] == "2024-11-04"
    assert splits["source_axis_start_utc"] == first.isoformat()
    assert splits["source_axis_end_exclusive_utc"] == history_end.isoformat()
    assert splits["partitions"]["train"]["start_utc"] == first.isoformat()
    assert config["requested_label_axis_start_utc"] == labels.timestamp.min().isoformat()
    assert config["requested_label_axis_end_exclusive_utc"] != config["actual_source_axis_end_exclusive_utc"]
    assert config["scalers"]["past_scaler"]["fitted_start"] == splits["partitions"]["train"]["start_utc"]
    test_times = arrays["target_ts_test"]
    assert not (test_times == int(gap.timestamp())).any()
    assert (np.diff(test_times, axis=1) == 3600).all()
    # The 3 local test dates contain 73 physical hours across fall-back.
    test = splits["partitions"]["test"]
    assert pd.Timestamp(test["end_exclusive_utc"]) - pd.Timestamp(test["start_utc"]) == pd.Timedelta(hours=73)
    assert test["rejected_windows"]["missing_available_forecast"] > 0
