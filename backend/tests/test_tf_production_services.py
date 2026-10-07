"""生产 TensorFlow 模型的资产、Shape 与严格输入契约测试。"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from realtime_api.tf_load_price_service import TFLoadPriceService
from realtime_api.tf_pv_service import TFPVService
from realtime_api.tf_split_service import TFSplitService


BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def load_service():
    service = TFLoadPriceService()
    service.load_models()
    return service


@pytest.fixture(scope="module")
def pv_service():
    service = TFPVService()
    service.load_models()
    return service


@pytest.fixture(scope="module")
def split_service():
    service = TFSplitService()
    service.load_models()
    return service


def test_tf_v2_live_feature_contract(load_service):
    frame = pd.read_parquet(BACKEND / "models/tf_assets/tf_v2/ca_tail.parquet")
    origin = pd.Timestamp("2026-04-30 00:00:00")
    pos = int(frame.index[frame["ts_local"] == origin][0])
    result = load_service.predict_features(
        frame.iloc[pos - 167:pos + 1],
        frame.iloc[pos + 1:pos + 25],
    )
    assert result["data_source"] == "live_features"
    assert len(result["hourly"]) == 24
    assert all(item["load_forecast_mw"] > 0 for item in result["hourly"])


def test_tf_v2_rejects_incomplete_window(load_service):
    frame = pd.read_parquet(BACKEND / "models/tf_assets/tf_v2/ca_tail.parquet")
    with pytest.raises(ValueError, match="时间戳无法解析或数量不正确|行数必须为 168"):
        load_service.predict_features(frame.iloc[:10], frame.iloc[168:192])


def test_tf_split_exposes_anchor_actual_load(split_service):
    frame = split_service._frame
    origin = split_service._origin
    pos = int(frame.index[frame["ts_local"] == origin][0])
    past = frame.iloc[pos - 167:pos + 1]
    future = frame.iloc[pos + 1:pos + 25]

    result = split_service.predict_features(past, future)

    assert result["anchor_actual_load_mw"] == pytest.approx(
        float(past["RT_Demand"].iloc[-1]), abs=0.1
    )
    assert len(result["anchor_history_actual"]) == 24
    assert result["anchor_history_actual"][-1]["target_time"] == str(origin)


def test_split_independent_tasks_match_joint_outputs(split_service, monkeypatch):
    frame = split_service._frame
    pos = int(frame.index[frame.ts_local == split_service._origin][0])
    past, future = frame.iloc[pos - 167:pos + 1], frame.iloc[pos + 1:pos + 25]
    joint = split_service.predict_features(past, future)
    load = split_service.predict_task_features("load", past, future)
    price = split_service.predict_task_features("price", past, future)
    assert [r["load_forecast_mw"] for r in load["hourly"]] == [r["load_forecast_mw"] for r in joint["hourly"]]
    assert [r["price_p50"] for r in price["hourly"]] == [r["price_p50"] for r in joint["hourly"]]
    def fail(*args, **kwargs):
        raise RuntimeError("price model failure")
    monkeypatch.setattr(split_service._price_model, "predict", fail)
    assert len(split_service.predict_task_features("load", past, future)["hourly"]) == 24


def test_pv_live_feature_contract(pv_service):
    frame = pd.read_parquet(BACKEND / "models/tf_assets/pv_v1/pv_tail.parquet")
    origin = pd.Timestamp("2026-04-29 23:00:00")
    pos = int(frame.index[frame["ts_start"] == origin][0])
    result = pv_service.predict_features(
        frame.iloc[pos - 95:pos + 1],
        frame.iloc[pos + 1:pos + 25],
    )
    assert result["data_source"] == "live_features"
    assert len(result["hourly_pv_mw"]) == 24
    assert all(0 <= value <= 1 for value in result["hourly_pu"])
    assert len(result["hourly_capacity_mw"]) == 24
    assert result["capacity_basis"].startswith("ISO-NE 2026 CELT")
    future = frame.iloc[pos + 1:pos + 25].reset_index(drop=True)
    for index, (ghi, sun_up) in enumerate(zip(future["ghi_mean"], future["sun_up"])):
        if float(ghi) <= 1.0 or float(sun_up) <= 0.5:
            assert result["hourly_pv_mw"][index] == 0.0


def test_pv_daylight_mask_requires_geometry_and_irradiance(pv_service, monkeypatch):
    """修正后的太阳几何与辐照度必须同时确认白昼。"""
    frame = pd.read_parquet(BACKEND / "models/tf_assets/pv_v1/pv_tail.parquet")
    origin = pd.Timestamp("2026-04-29 23:00:00")
    pos = int(frame.index[frame["ts_start"] == origin][0])
    past = frame.iloc[pos - 95:pos + 1].copy()
    future = frame.iloc[pos + 1:pos + 25].copy()
    future["sun_up"] = 0
    future["ghi_mean"] = 0.0
    future.iloc[12, future.columns.get_loc("ghi_mean")] = 500.0
    future.iloc[12, future.columns.get_loc("sun_up")] = 1

    class PositiveModel:
        @staticmethod
        def predict(_inputs, verbose=0):
            return np.ones((1, 24, 1), dtype="float32")

    monkeypatch.setattr(pv_service, "_model", PositiveModel())
    result = pv_service.predict_features(past, future)

    assert result["hourly_pv_mw"][12] > 0.0
    assert all(
        value == 0.0
        for index, value in enumerate(result["hourly_pv_mw"])
        if index != 12
    )


def test_pv_rejects_missing_training_feature(pv_service):
    frame = pd.read_parquet(BACKEND / "models/tf_assets/pv_v1/pv_tail.parquet")
    past = frame.iloc[:96].drop(columns=["pv_n_ISONE"])
    with pytest.raises(ValueError, match="pv_n_ISONE"):
        pv_service.predict_features(past, frame.iloc[96:120])


def test_pv_mw_decode_uses_each_future_timestamp_capacity(pv_service, monkeypatch):
    frame = pd.read_parquet(BACKEND / "models/tf_assets/pv_v1/pv_tail.parquet")
    origin = pd.Timestamp("2026-04-29 23:00:00")
    pos = int(frame.index[frame["ts_start"] == origin][0])
    past = frame.iloc[pos - 95:pos + 1].copy()
    future = frame.iloc[pos + 1:pos + 25].copy()
    future["sun_up"] = 1
    future["ghi_mean"] = 500.0

    class ConstantModel:
        @staticmethod
        def predict(_inputs, verbose=0):
            return np.zeros((1, 24, 1), dtype="float32")

    monkeypatch.setattr(pv_service, "_model", ConstantModel())
    result = pv_service.predict_features(past, future)

    assert result["hourly_capacity_mw"][-1] > result["hourly_capacity_mw"][0]
    decoded_pu = result["hourly_pu"][0]
    assert result["hourly_pv_mw"][0] == pytest.approx(
        decoded_pu * result["hourly_capacity_mw"][0], abs=0.2
    )
