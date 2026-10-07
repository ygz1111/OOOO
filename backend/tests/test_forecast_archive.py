"""Integrity/provenance checks for the independent issued-input archive."""
import gzip
from copy import deepcopy

import pandas as pd
import pytest

from realtime_api.services import forecast_archive as archive


@pytest.fixture
def archived_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_DIR", tmp_path / "forecast_inputs")
    monkeypatch.setattr(archive, "model_signature", lambda: "original-assets")
    timestamp = pd.Timestamp("2026-09-30 23:00")
    weather = pd.DataFrame({"timestamp": [timestamp], "temperature_2m": [12.]})
    weather.attrs["forecast_provenance"] = {"received_at": "2026-10-01T03:01:00+00:00",
        "source": "open_meteo_forecast", "model_run": None,
        "run_status": "not_exposed_by_endpoint"}
    tasks = {"load": {"generated_at": "2026-09-30T23:07:00", "origin_hour": str(timestamp),
        "input_status": "estimated_inputs", "past": [{"ts_local": timestamp, "RT_Demand": 12300.}],
        "future": [{"ts_local": timestamp + pd.Timedelta(hours=1), "Dry_Bulb": 65.}],
        "prediction": {"hourly": [{"timestamp": "2026-10-01T00:00:00", "load_forecast_mw": 12400.}]}}}
    return tasks, weather


def test_exact_inputs_survive_later_weather_and_duplicate_saves(archived_inputs):
    tasks, weather = archived_inputs
    original = deepcopy(tasks)
    result = archive.save_forecast_inputs(tasks, weather)
    assert result["status"] == "saved"
    second = archive.save_forecast_inputs(tasks, weather)
    assert result["archive_id"] == second["archive_id"]
    assert len(list(archive.ARCHIVE_DIR.glob("*.json.gz"))) == 1
    tasks["load"]["past"][0]["RT_Demand"] = -1
    weather.loc[0, "temperature_2m"] = 99
    payload = archive.read_forecast_inputs(result["archive_id"], "original-assets")
    assert payload["components"]["load"]["past"][0]["RT_Demand"] == 12300
    assert payload["components"]["load"]["generated_at"] == original["load"]["generated_at"]
    assert payload["weather"]["records"][0]["temperature_2m"] == 12
    assert payload["weather"]["provenance"]["model_run"] is None


def test_changed_assets_tampering_and_untrusted_identifier_are_rejected(archived_inputs):
    result = archive.save_forecast_inputs(*archived_inputs)
    with pytest.raises(ValueError, match="模型资产已改变"):
        archive.read_forecast_inputs(result["archive_id"], "new-assets")
    with pytest.raises(ValueError, match="无效"):
        archive.read_forecast_inputs("../outside")
    path = archive.ARCHIVE_DIR / f"{result['archive_id']}.json.gz"
    path.write_bytes(gzip.compress(b'{}'))
    with pytest.raises(ValueError, match="校验失败"):
        archive.read_forecast_inputs(result["archive_id"])
    assert archive.save_forecast_inputs(*archived_inputs)["status"] == "failed"
    assert gzip.decompress(path.read_bytes()) == b'{}'  # Do not overwrite a damaged archive.


def test_io_failure_is_explicit_and_empty_inputs_create_nothing(archived_inputs, monkeypatch):
    def unavailable(*args):
        raise OSError("test disk failure")
    monkeypatch.setattr(archive, "model_signature", unavailable)
    assert archive.save_forecast_inputs(*archived_inputs)["status"] == "failed"
    assert archive.save_forecast_inputs({}, archived_inputs[1]) == {"status": "not_created"}
    assert not archive.ARCHIVE_DIR.exists()
