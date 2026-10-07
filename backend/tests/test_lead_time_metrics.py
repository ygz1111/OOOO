"""Stored online forecasts: horizons, genuine labels, duplicates and DST."""
from datetime import datetime, timedelta

import pytest

from realtime_api.services.lead_time_metrics import build_lead_time_metrics, latest_snapshot_per_target
from realtime_api.routers import analytics


def row(target, generated, forecast=110, actual=100, source="iso_ne+open_meteo:zonal_he_v2+input_quality_complete", row_id=1):
    return {"id": row_id, "target_timestamp": target, "prediction_timestamp": generated,
            "load_forecast_mw": forecast, "actual_load_mw": actual, "data_source": source}


def test_lead_boundaries_keep_subhour_first_step_and_exact_limits():
    target = datetime(2026, 10, 1, 12)
    rows = [row(target + timedelta(days=i), target + timedelta(days=i) - timedelta(seconds=seconds))
            for i, seconds in enumerate((55 * 60, 6 * 3600, 6 * 3600 + 1, 12 * 3600, 12 * 3600 + 1, 24 * 3600))]
    result = build_lead_time_metrics(rows)
    assert [group["count"] for group in result["lead_time_groups"]] == [2, 2, 2]
    assert [group["mae"] for group in result["lead_time_groups"]] == [10, 10, 10]


def test_group_dedupes_earliest_snapshot_and_quality_is_not_assumed_for_legacy_rows():
    target = datetime(2026, 10, 1, 12)
    rows = [
        row(target, target - timedelta(hours=6), 120, row_id=3),
        row(target, target - timedelta(hours=6), 130, row_id=4),
        row(target, target - timedelta(hours=1), 101, source="iso_ne+open_meteo:zonal_he_v2+estimated_inputs", row_id=5),
        row(target, target - timedelta(hours=12), 140, source="iso_ne+open_meteo:zonal_he_v2", row_id=6),
        row(target, target - timedelta(hours=24), 150, source="iso_ne+open_meteo:zonal_he_v2+estimated_inputs", row_id=7),
    ]
    groups = build_lead_time_metrics(rows)["lead_time_groups"]
    assert [group["count"] for group in groups] == [1, 1, 1]
    assert [group["mae"] for group in groups] == [20, 40, 50]
    assert [part["count"] for part in groups[0]["input_quality"]] == [1, 0, 0]
    assert [part["count"] for part in groups[1]["input_quality"]] == [0, 0, 1]
    assert [part["count"] for part in groups[2]["input_quality"]] == [0, 1, 0]
    assert latest_snapshot_per_target(rows)[0]["load_forecast_mw"] == 101


def test_cache_read_time_does_not_replace_original_generation_time():
    target = datetime(2026, 10, 1, 12)
    cached = row(target, target - timedelta(hours=10), source="iso_ne+open_meteo:zonal_he_v2+estimated_inputs")
    cached.update(cache_hit=True, created_at=target - timedelta(minutes=30))
    groups = build_lead_time_metrics([cached])["lead_time_groups"]
    assert [group["count"] for group in groups] == [0, 1, 0]


def test_cross_month_and_latest_timestamp_id_tie_match_existing_overall_selection():
    target = datetime(2026, 10, 1, 0)
    rows = [row(target, datetime(2026, 9, 30, 23, 55), 103, row_id=2),
            row(target, datetime(2026, 9, 30, 23, 55), 102, row_id=3)]
    assert latest_snapshot_per_target(rows)[0]["load_forecast_mw"] == 102
    groups = build_lead_time_metrics(rows)["lead_time_groups"]
    assert groups[0]["count"] == 1 and groups[0]["mae"] == 3


def test_empty_groups_and_zero_actual_mape_stay_unavailable_instead_of_fake_zero():
    result = build_lead_time_metrics([])
    assert all(group["count"] == 0 and group["mae"] is None for group in result["lead_time_groups"])
    target = datetime(2026, 10, 1, 0)
    groups = build_lead_time_metrics([row(target, target - timedelta(minutes=10), actual=0)])["lead_time_groups"]
    assert groups[0]["count"] == 1 and groups[0]["mape"] is None


def test_spring_dst_uses_physical_hours_and_rejects_nonexistent_naive_hour():
    rows = [
        # Seven wall hours are six elapsed hours across spring-forward.
        row(datetime(2026, 3, 8, 8), datetime(2026, 3, 8, 1)),
        row(datetime(2026, 3, 8, 8), datetime(2026, 3, 8, 2, 30)),
    ]
    result = build_lead_time_metrics(rows)
    assert [group["count"] for group in result["lead_time_groups"]] == [1, 0, 0]
    assert result["lead_time_excluded"]["invalid_timestamp"] == 1


def test_fall_dst_rejects_ambiguous_naive_hour_but_accepts_explicit_offsets():
    rows = [
        row(datetime(2026, 11, 1, 8), datetime(2026, 11, 1, 1)),
        # 01:00 EDT to 07:00 EST is seven physical hours, despite six wall hours.
        row("2026-11-01T07:00:00-05:00", "2026-11-01T01:00:00-04:00"),
    ]
    result = build_lead_time_metrics(rows)
    assert [group["count"] for group in result["lead_time_groups"]] == [0, 1, 0]
    assert result["lead_time_excluded"]["ambiguous_timestamp"] == 1


def test_invalid_values_missing_actuals_noncausal_and_outside_horizon_are_not_samples():
    target = datetime(2026, 10, 1, 12)
    valid_generated = target - timedelta(hours=1)
    rows = [row(target, valid_generated, actual=None), row(target, valid_generated, forecast=float("nan")),
            row(target, valid_generated, actual=-10), row(target, target),
            row(target, target - timedelta(hours=24, seconds=1))]
    result = build_lead_time_metrics(rows)
    assert all(group["count"] == 0 and group["mae"] is None for group in result["lead_time_groups"])
    assert result["lead_time_excluded"]["invalid_values"] == 2
    assert result["lead_time_excluded"]["noncausal"] == 1
    assert result["lead_time_excluded"]["outside_24_hours"] == 1


@pytest.mark.asyncio
async def test_accuracy_queries_once_preserves_overall_latest_and_adds_horizon_groups(monkeypatch):
    target = datetime(2026, 10, 1, 12)
    rows = [row(target, target - timedelta(hours=6), 120, row_id=1),
            row(target, target - timedelta(minutes=30), 101, row_id=2)]
    calls = []

    async def fake_records(start_time, end_time, **kwargs):
        calls.append((start_time, end_time, kwargs))
        return rows

    monkeypatch.setattr(analytics, "_get_active_prediction_records", fake_records)
    monkeypatch.setattr(analytics, "eastern_now_hour", lambda: target)
    result = await analytics._compute_accuracy_from_db(hours=24)
    assert len(calls) == 1
    assert calls[0][2] == {"dedupe_target": False}
    assert result["count"] == 1 and result["mae"] == 1
    assert result["metric_scope"] == "latest_snapshot_per_target"
    assert result["lead_time_groups"][0]["count"] == 1
    assert result["lead_time_groups"][0]["mae"] == 20


@pytest.mark.asyncio
async def test_crud_keeps_verified_actual_source_for_all_vintage_query(monkeypatch):
    from realtime_api.crud import core

    captured = {}

    async def fake_execute(sql, params):
        captured["sql"] = sql
        return []

    monkeypatch.setattr(core.db_manager, "execute_sql", fake_execute)
    await core.LoadPredictionsCRUD.get_predictions_by_time_range(datetime(2026, 10, 1), datetime(2026, 10, 2),
                                                                model_type="tf_split_v1", dedupe_target=False)
    assert "a.data_source = 'iso_ne_zonal_he_v2'" in captured["sql"]
    assert "a.region = 'NewEngland_zonal_HE'" in captured["sql"]
    assert "prediction_timestamp < target_timestamp" in captured["sql"]
    assert "ELSE NULL END" in captured["sql"]
