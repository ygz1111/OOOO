"""Offline source/interval contracts; no network or production database writes."""
from datetime import datetime, date
from unittest.mock import AsyncMock, Mock

import numpy as np
import pandas as pd
import pytest

from realtime_api.utils.iso_ne_intervals import (
    ACTUAL_REGION, ACTUAL_SOURCE, zonal_hourly,
)


def samples(start="2026-09-22T08:00:00-04:00", count=12):
    return [{"interval_begin_date": ts.isoformat(), "load_zone_id": zone,
             "estimated_load_mw": 1000., "estimated_btm_pv_mw": 50.}
            for ts in pd.date_range(start, periods=count, freq="5min")
            for zone in range(4001, 4009)]


def test_same_interval_load_ends_at_nine_pv_starts_at_eight():
    load, pv = zonal_hourly(samples(), 12, now="2026-09-22 09:40")
    assert load.index.tolist() == [pd.Timestamp("2026-09-22 09:00")]
    assert pv.index.tolist() == [pd.Timestamp("2026-09-22 08:00")]
    assert load.iloc[0]["load"] == 8000
    assert pv.iloc[0]["pv_mw"] == 400
    assert load.iloc[0]["minimum_samples"] == 12


def test_unfinished_hour_never_enters_observations_even_if_feed_has_future_rows():
    assert zonal_hourly(samples(), now="2026-09-22 08:59:59")[0].empty
    assert not zonal_hourly(samples(), now="2026-09-22 09:00")[0].empty


def test_duplicate_records_do_not_make_partial_hour_complete():
    rows = samples(count=8) * 3
    load, _ = zonal_hourly(rows, 8, now="2026-09-22 10:00")
    assert load.iloc[0]["minimum_samples"] == 8
    assert zonal_hourly(rows, 12, now="2026-09-22 10:00")[0].empty


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -10, "not-a-number", None])
def test_bad_load_is_not_a_label_but_does_not_remove_valid_pv(bad):
    rows = samples()
    rows[0]["estimated_load_mw"] = bad
    load, pv = zonal_hourly(rows, 12, now="2026-09-22 10:00")
    assert load.empty
    assert len(pv) == 1
    assert np.isnan(pv.iloc[0]["rt_demand"])


def test_missing_zone_and_off_grid_samples_are_rejected():
    rows = [row for row in samples() if row["load_zone_id"] != 4008]
    assert zonal_hourly(rows, now="2026-09-22 10:00")[0].empty
    rows = samples()
    rows[0]["interval_begin_date"] = "2026-09-22T08:01:00-04:00"
    assert zonal_hourly(rows, 12, now="2026-09-22 10:00")[0].empty


def test_fall_back_hour_is_not_merged_or_mislabeled():
    rows = samples("2026-11-01T01:00:00-04:00") + samples("2026-11-01T01:00:00-05:00")
    assert zonal_hourly(rows, now="2026-11-01 04:00")[0].empty


def test_midnight_hour_end_and_utc_input():
    load, _ = zonal_hourly(samples("2026-09-23T03:00:00Z"), 12, now="2026-09-23T04:00:00Z")
    assert load.index.tolist() == [pd.Timestamp("2026-09-23 00:00")]


def test_sync_uses_same_zonal_endpoint_and_complete_labels(monkeypatch):
    from realtime_api.utils import iso_ne
    response = Mock()
    response.json.return_value = {"wrapper": {"five_min_estimated_zonal_load": samples("2020-01-02T08:00:00-05:00")}}
    get = Mock(return_value=response)
    monkeypatch.setattr(iso_ne.requests, "get", get)
    result = iso_ne.fetch_hourly_actual_load(date(2020, 1, 2), "test", "test")
    assert "fiveminuteestimatedzonalload/day/20200102" in get.call_args.args[0]
    assert result == [(datetime(2020, 1, 2, 9), 8000.)]


@pytest.mark.asyncio
async def test_sync_preserves_old_records_and_never_rewrites_predictions(monkeypatch):
    from realtime_api.utils import iso_ne
    from realtime_api.crud import core
    insert = AsyncMock(return_value=1)
    execute = AsyncMock()
    monkeypatch.setattr(core.db_manager, "initialize", AsyncMock())
    monkeypatch.setattr(core.db_manager, "execute_sql", execute)
    monkeypatch.setattr(core.ActualLoadDataCRUD, "insert_actual_load", insert)
    await iso_ne.persist_actual_load([(datetime(2026, 9, 22, 9), 8000.)])
    assert insert.call_args.kwargs["region"] == ACTUAL_REGION
    assert insert.call_args.kwargs["data_source"] == ACTUAL_SOURCE
    execute.assert_not_called()


@pytest.mark.asyncio
async def test_actual_queries_and_accuracy_cannot_read_legacy_labels(monkeypatch):
    from realtime_api.crud import core
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(core.db_manager, "execute_sql", execute)
    start, end = datetime(2026, 9, 22), datetime(2026, 9, 23)
    await core.ActualLoadDataCRUD.get_actual_load_by_time_range(start, end)
    assert execute.call_args.args[1] == (start, end, ACTUAL_REGION, ACTUAL_SOURCE)
    for dedupe in (False, True):
        await core.LoadPredictionsCRUD.get_predictions_by_time_range(start, end, dedupe_target=dedupe)
        sql = execute.call_args.args[0]
        assert "LOCATE('zonal_he_v2'," in sql
        assert ACTUAL_REGION in sql and ACTUAL_SOURCE in sql
        assert "ELSE NULL END AS actual_load_mw" in sql


@pytest.mark.asyncio
async def test_real_selects_pair_only_versioned_forecasts_and_actuals(monkeypatch):
    """Execute the generated SELECTs, not just string assertions (in-memory DB)."""
    import sqlite3
    from realtime_api.crud import core
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.create_function("LOCATE", 2, lambda needle, value: (value or "").find(needle) + 1)
    db.executescript("""
        CREATE TABLE load_predictions (
            id INTEGER, prediction_id TEXT, prediction_timestamp TEXT, target_timestamp TEXT,
            load_forecast_mw REAL, pv_estimation_mw REAL, net_load_mw REAL,
            confidence_lower_mw REAL, confidence_upper_mw REAL, model_type TEXT,
            inference_time_ms REAL, cache_hit INTEGER, data_source TEXT, created_at TEXT, actual_load_mw REAL
        );
        CREATE TABLE actual_load_data (
            timestamp TEXT, actual_load_mw REAL, region TEXT, data_source TEXT
        );
    """)
    for hour, source in [(9, "iso_ne+open_meteo:zonal_he_v2"), (10, "iso_ne"), (11, "iso_ne+open_meteo:zonal_he_v2")]:
        target = f"2026-09-22 {hour:02}:00:00"
        db.execute("INSERT INTO load_predictions(id, prediction_timestamp, target_timestamp, actual_load_mw, data_source) VALUES (?,?,?,?,?)",
                   (hour, "2026-09-22 08:00:00", target, 99999., source))
        # Poisoned legacy label, always present but never used.
        db.execute("INSERT INTO actual_load_data VALUES (?,?,?,?)", (target, 77777., "NewEngland", "iso_ne"))
        if hour != 11:
            db.execute("INSERT INTO actual_load_data VALUES (?,?,?,?)", (target, 8000., ACTUAL_REGION, ACTUAL_SOURCE))
    async def execute(sql, params):
        values = tuple(str(value) if isinstance(value, datetime) else value for value in params)
        return [dict(row) for row in db.execute(sql.replace("%s", "?"), values)]
    monkeypatch.setattr(core.db_manager, "execute_sql", execute)
    try:
        for dedupe in (False, True):
            rows = await core.LoadPredictionsCRUD.get_predictions_by_time_range(
                datetime(2026, 9, 22), datetime(2026, 9, 23), dedupe_target=dedupe)
            assert [row["actual_load_mw"] for row in rows] == [8000., None, None]
        latest = await core.LoadPredictionsCRUD.get_latest_predictions(3)
        assert [row["actual_load_mw"] for row in latest] == [None, None, 8000.]
        # Read-only SELECTs cannot modify the archived poison values.
        assert db.execute("SELECT MIN(actual_load_mw) FROM load_predictions").fetchone()[0] == 99999.
    finally:
        db.close()
