"""Offline source-contract regression tests; no project DB/cache/network."""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "caiso_data.py"
spec = importlib.util.spec_from_file_location("caiso_source_contract", MODULE_PATH)
data = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(data)


def oasis_payload(day, *, omit=None, invalid=None, duplicate=None, market="ACTUAL"):
    columns = ["OPR_DT", "RENEWABLE_TYPE", "MARKET_RUN_ID", "XML_DATA_ITEM", "TRADING_HUB", "MW", "INTERVALSTARTTIME_GMT", "INTERVALENDTIME_GMT"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    start, end = data.day_bounds(day)
    index = 0
    while start < end:
        for hub in data.HUBS:
            if omit == (index, hub):
                continue
            record = {"OPR_DT": day.isoformat(), "RENEWABLE_TYPE": "Solar", "MARKET_RUN_ID": market, "XML_DATA_ITEM": "RENEW_FCST_ACT_MW" if market == "ACTUAL" else "RENEW_FCST_DA_MW", "TRADING_HUB": hub, "MW": "-1.12345" if invalid != (index, hub) else "NaN", "INTERVALSTARTTIME_GMT": data.iso_utc(start), "INTERVALENDTIME_GMT": data.iso_utc(start + timedelta(hours=1))}
            writer.writerow(record)
            if duplicate == (index, hub):
                writer.writerow(record)
        start += timedelta(hours=1)
        index += 1
    # Wind does not qualify as a solar observation.
    writer.writerow({"OPR_DT": day.isoformat(), "RENEWABLE_TYPE": "Wind", "MARKET_RUN_ID": "ACTUAL", "XML_DATA_ITEM": "RENEW_FCST_ACT_MW", "TRADING_HUB": "NP15", "MW": "999999", "INTERVALSTARTTIME_GMT": data.iso_utc(data.day_bounds(day)[0]), "INTERVALENDTIME_GMT": data.iso_utc(data.day_bounds(day)[0] + timedelta(hours=1))})
    return out.getvalue().encode()


def outlook_payload(day, *, omit=None, invalid=None):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Time", "Solar", "Wind"])
    for minute in range(24 * 60):
        if minute % 5:
            continue
        clock = f"{minute // 60:02}:{minute % 60:02}"
        if clock == omit:
            continue
        value = "-2.5" if clock != invalid else ""
        naive = datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute)
        aware = naive.replace(tzinfo=data.LA)
        if aware.astimezone(data.UTC).astimezone(data.LA).replace(tzinfo=None) != naive:
            value = ""  # Match official spring chart placeholders.
        writer.writerow([clock, value, "100000"])
    return out.getvalue().encode()


@pytest.mark.parametrize("day,count", [(date(2024, 1, 1), 24), (date(2024, 3, 10), 23), (date(2023, 11, 5), 25)])
def test_oasis_physical_grid_and_negative_actual(day, count):
    rows, quality = data.normalize_oasis(oasis_payload(day), day, {})
    assert len(rows) == quality["complete_hours"] == count
    assert quality["source_complete"]
    assert all(row["solar_actual_mw"] == -3.37035 for row in rows)
    assert all(row["source_kind"] == "actual" and row["hub_count"] == 3 for row in rows)
    starts = [data._utc_timestamp(row["timestamp"]) for row in rows]
    assert all(b - a == timedelta(hours=1) for a, b in zip(starts, starts[1:]))
    if count == 25:
        one = [row for row in rows if "T01:00:" in row["local_timestamp"]]
        assert len(one) == 2 and one[0]["local_fold"] == 0 and one[1]["local_fold"] == 1
        assert one[0]["timestamp"] != one[1]["timestamp"]


def test_oasis_forecast_is_rejected():
    day = date(2024, 1, 1)
    with pytest.raises(data.SourceError, match="Forecast is not an Actual"):
        data.normalize_oasis(oasis_payload(day, market="DAM"), day, {})


@pytest.mark.parametrize("problem,reason", [("omit", "missing_hub"), ("invalid", "nonfinite_numeric_value"), ("duplicate", "duplicate_hub_record")])
def test_oasis_partial_hour_never_uses_partial_hub_sum(problem, reason):
    day = date(2024, 1, 1)
    rows, quality = data.normalize_oasis(oasis_payload(day, **{problem: (5, "SP15")}), day, {})
    assert len(rows) == 24 and quality["complete_hours"] == 23
    assert rows[5]["solar_actual_mw"] is None and not rows[5]["is_complete"]
    assert reason in rows[5]["quality_reason"]


def test_oasis_utc_timezone_must_be_explicit():
    day = date(2024, 1, 1)
    raw = oasis_payload(day).replace(b"2024-01-01T08:00:00Z", b"2024-01-01T08:00:00")
    rows, quality = data.normalize_oasis(raw, day, {})
    assert not rows[0]["is_complete"]
    assert any(issue["reason"] == "interval_timezone_missing" for issue in quality["record_issues"])


def test_oasis_xml_no_data_preserves_full_missing_grid():
    day = date(2023, 11, 5)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("report.xml", "<ERR_CODE>1000</ERR_CODE><ERR_DESC>No data returned for the specified selection</ERR_DESC>")
    rows, quality = data.normalize(out.getvalue(), day, "oasis", {})
    assert len(rows) == 25 and quality["complete_hours"] == 0
    assert all(row["quality_reason"] == "official_no_data" for row in rows)


def test_outlook_regular_day_mean_and_negative_values_retained():
    day = date(2024, 1, 1)
    rows, quality = data.normalize_outlook(outlook_payload(day), day, {})
    assert quality["source_complete"]
    assert all(row["solar_actual_mw"] == -2.5 and row["sample_count"] == 12 for row in rows)
    assert all("analysis_convention" in row["interval_semantics"] for row in rows)


def test_outlook_spring_nonexistent_placeholders_not_fake_hour():
    day = date(2024, 3, 10)
    rows, quality = data.normalize_outlook(outlook_payload(day), day, {})
    assert len(rows) == 23 and quality["source_complete"]
    assert quality["nonexistent_spring_clock_placeholders"] == 12
    assert not any("T02:" in row["local_timestamp"] for row in rows)


def test_outlook_nonexistent_spring_value_rejected_as_timezone_conflict():
    day = date(2024, 3, 10)
    raw = outlook_payload(day).replace(b"02:00,,100000", b"02:00,123,100000")
    with pytest.raises(data.SourceError, match="timezone contract inconsistent"):
        data.normalize_outlook(raw, day, {})


def test_outlook_fall_both_folds_explicitly_ambiguous():
    day = date(2023, 11, 5)
    rows, quality = data.normalize_outlook(outlook_payload(day), day, {})
    assert len(rows) == 25 and quality["complete_hours"] == 23
    one = [row for row in rows if "T01:" in row["local_timestamp"]]
    assert len(one) == 2
    assert all(row["solar_actual_mw"] is None and row["quality_reason"] == "ambiguous_local_hour_no_utc_offset" for row in one)


@pytest.mark.parametrize("kind,reason", [("omit", "missing_five_minute_point"), ("invalid", "missing_or_invalid_numeric_value")])
def test_outlook_missing_points_do_not_use_eleven_point_mean(kind, reason):
    day = date(2024, 1, 1)
    rows, quality = data.normalize_outlook(outlook_payload(day, **{kind: "12:05"}), day, {})
    assert rows[12]["solar_actual_mw"] is None and rows[12]["sample_count"] == 11
    assert reason == rows[12]["quality_reason"] and quality["complete_hours"] == 23


class Response:
    def __init__(self, raw, url="https://example.invalid", status=200):
        self.content, self.url, self.status_code = raw, url, status
        self.headers = {"Content-Type": "text/csv"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), 0

    def get(self, url, timeout):
        self.calls += 1
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        result.url = url
        return result


def test_complete_cache_resume_no_network_and_preserves_provenance(tmp_path):
    day = date(2024, 1, 1)
    session = Session([Response(oasis_payload(day))])
    path = data.fetch_day("oasis", day, cache_root=tmp_path, session=session)
    before = (path / "source.json").read_bytes()
    assert data.fetch_day("oasis", day, cache_root=tmp_path, session=session) == path
    assert session.calls == 1 and (path / "source.json").read_bytes() == before
    assert json.loads(before)["quality"]["source_complete"]


def test_incomplete_capture_retried_without_overwrite(tmp_path):
    day = date(2024, 1, 1)
    session = Session([Response(oasis_payload(day, omit=(4, "SP15"))), Response(oasis_payload(day))])
    first = data.fetch_day("oasis", day, cache_root=tmp_path, session=session)
    original = (first / "source.json").read_bytes()
    second = data.fetch_day("oasis", day, cache_root=tmp_path, session=session)
    assert first != second and session.calls == 2
    assert (first / "source.json").read_bytes() == original
    assert json.loads((second / "source.json").read_bytes())["quality"]["source_complete"]


def test_corrupt_cache_refused_not_overwritten(tmp_path):
    day = date(2024, 1, 1)
    session = Session([Response(oasis_payload(day))])
    path = data.fetch_day("oasis", day, cache_root=tmp_path, session=session)
    (path / "raw.csv").write_bytes(b"corruption")
    with pytest.raises(data.SourceError, match="hash mismatch"):
        data.fetch_day("oasis", day, cache_root=tmp_path, session=session)
    assert session.calls == 1


def test_bounded_rate_limit_retry(tmp_path):
    day = date(2024, 1, 1)
    session = Session([Response(b"", status=429), Response(oasis_payload(day))])
    delays = []
    path = data.fetch_day("oasis", day, cache_root=tmp_path, session=session, sleep=delays.append)
    assert path.exists() and session.calls == 2 and delays == [5]


def test_external_failure_leaves_no_valid_capture_then_recovers(tmp_path):
    day = date(2024, 1, 1)
    session = Session([RuntimeError("SSL failure"), Response(oasis_payload(day))])
    with pytest.raises(RuntimeError, match="SSL failure"):
        data.fetch_day("oasis", day, cache_root=tmp_path, session=session)
    assert not list(tmp_path.rglob("capture-*"))
    assert data.fetch_day("oasis", day, cache_root=tmp_path, session=session).exists()


def test_latest_date_rolls_in_la_not_host_timezone():
    assert data.latest_complete_date(datetime(2026, 10, 4, 6, 59, tzinfo=timezone.utc)) == date(2026, 10, 2)
    assert data.latest_complete_date(datetime(2026, 10, 4, 7, 0, tzinfo=timezone.utc)) == date(2026, 10, 3)


def test_source_url_uses_25_hour_day_utc_bounds():
    url = data.source_url("oasis", date(2023, 11, 5))
    assert "20231105T07%3A00-0000" in url and "20231106T08%3A00-0000" in url
    assert "market_run_id=ACTUAL" in url


def test_pacing_applies_only_to_actual_http_calls(monkeypatch):
    session = Session([Response(b"one"), Response(b"two")])
    clock = iter([1, 2, 7])
    waits = []
    monkeypatch.setattr(data.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(data.time, "sleep", waits.append)
    paced = data._PacedSession(session)
    paced.get("https://oasis.caiso.com/oasisapi/SingleZip", timeout=10)
    paced.get("https://oasis.caiso.com/oasisapi/SingleZip", timeout=10)
    assert waits == [5] and session.calls == 2


def test_no_bulk_without_human_sample_confirmation(capsys):
    with pytest.raises(SystemExit, match="2"):
        data.main(["download", "--source", "oasis"])
    assert "confirmation is required" in capsys.readouterr().err


def test_hourly_output_never_overwritten(tmp_path):
    rows, _ = data.normalize_oasis(oasis_payload(date(2024, 1, 1)), date(2024, 1, 1), {})
    path = tmp_path / "hourly.csv"
    data.write_hourly(path, rows)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        data.write_hourly(path, rows)
    assert path.read_bytes() == original


def range_payload(start, end, *, missing_day=None):
    blocks = []
    while start <= end:
        if start != missing_day:
            blocks.append(oasis_payload(start).decode())
        start += timedelta(days=1)
    if not blocks:
        return b""
    return (blocks[0] + "".join(block.split("\n", 1)[1] for block in blocks[1:])).encode()


def test_oasis_block_28_days_crosses_month_and_spring_once_with_complete_daily_outputs(tmp_path):
    start, end = date(2024, 2, 20), date(2024, 3, 18)
    session = Session([Response(range_payload(start, end))])
    capture = data.fetch_oasis_block(start, end, cache_root=tmp_path, session=session)
    meta = json.loads((capture / "source.json").read_text(encoding="utf-8"))
    assert meta["quality"]["source_complete"] and session.calls == 1
    assert meta["quality"]["expected_physical_hours"] == 28 * 24 - 1
    assert meta["quality_by_date"]["2024-03-10"]["complete_hours"] == 23
    assert len(list((capture / "daily").glob("*.csv"))) == 28
    assert len(list(capture.rglob("raw.csv"))) == 1
    assert data.fetch_oasis_block(start, end, cache_root=tmp_path, session=session) == capture
    assert session.calls == 1


def test_oasis_block_missing_whole_date_is_explicit_and_retry_preserves_first_capture(tmp_path):
    start, end = date(2023, 11, 4), date(2023, 11, 6)
    session = Session([Response(range_payload(start, end, missing_day=date(2023, 11, 5))), Response(range_payload(start, end))])
    first = data.fetch_oasis_block(start, end, cache_root=tmp_path, session=session)
    meta = json.loads((first / "source.json").read_text(encoding="utf-8"))
    assert meta["quality"]["incomplete_dates"] == ["2023-11-05"]
    missing = list(csv.DictReader((first / "daily" / "2023-11-05.hourly.csv").open(encoding="utf-8")))
    assert len(missing) == 25 and all(row["solar_actual_mw"] == "" for row in missing)
    second = data.fetch_oasis_block(start, end, cache_root=tmp_path, session=session)
    assert first != second and json.loads((second / "source.json").read_text(encoding="utf-8"))["quality"]["source_complete"]
    assert (first / "source.json").exists()


def test_31_calendar_days_crossing_fall_must_not_exceed_physical_api_range():
    with pytest.raises(ValueError, match="31 physical UTC days"):
        data.oasis_range_url(date(2023, 11, 1), date(2023, 12, 1))
    chunks = data._date_chunks(date(2023, 11, 1), date(2023, 12, 1), 31)
    assert chunks == [(date(2023, 11, 1), date(2023, 11, 30)), (date(2023, 12, 1), date(2023, 12, 1))]
    assert all(data.day_bounds(end)[1] - data.day_bounds(start)[0] <= timedelta(days=31) for start, end in chunks)


def test_bulk_flag_cannot_replace_human_recorded_authorization(tmp_path):
    authorization = tmp_path / "authorization.json"
    authorization.write_text(json.dumps({"status": "awaiting_label_choice", "bulk_download_authorized": False, "label_confirmation": None, "official_label": "CAISO OASIS Solar ACTUAL, NP15+SP15+ZP26"}))
    with pytest.raises(data.SourceError, match="not approved"):
        data.authorize_bulk("oasis", authorization)
    authorization.write_text(json.dumps({"status": "approved", "bulk_download_authorized": True, "label_confirmation": {"answer": "confirmed real sample"}, "official_label": "CAISO OASIS Solar ACTUAL, NP15+SP15+ZP26"}))
    data.authorize_bulk("oasis", authorization)
    with pytest.raises(data.SourceError, match="not approved"):
        data.authorize_bulk("outlook", authorization)


def test_cli_refuses_outputs_outside_independent_experiment(tmp_path, capsys, monkeypatch):
    # A workspace-local pytest basetemp can itself be inside the real experiment.
    # Give the guard an explicit isolated root so the forbidden path remains
    # outside it regardless of pytest's location, and prohibit network fallback.
    monkeypatch.setattr(data, "ROOT", tmp_path / "allowed_experiment")

    def no_network(*args, **kwargs):
        pytest.fail("The output-scope guard must run before acquisition")

    monkeypatch.setattr(data, "fetch_day", no_network)
    monkeypatch.setattr(data, "fetch_oasis_block", no_network)
    with pytest.raises(SystemExit, match="2"):
        data.main(["probe", "--cache-root", str(tmp_path)])
    assert "must remain inside experiments/caiso_pv" in capsys.readouterr().err


def test_assemble_revalidates_raw_not_modified_derived_csv_and_keeps_dst(tmp_path):
    start, end = date(2023, 11, 4), date(2023, 11, 6)
    capture = data.fetch_oasis_block(start, end, cache_root=tmp_path / "raw", session=Session([Response(range_payload(start, end))]))
    (capture / "hourly.csv").write_text("wrong cached derived output")
    csv_path, audit_path = data.assemble_labels(start, end, cache_root=tmp_path / "raw", output_dir=tmp_path / "processed")
    with csv_path.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert len(rows) == 73 and audit["complete_hours"] == 73
    assert audit["raw_source_revalidated"] and audit["negative_complete_hourly_totals"] == 73
    assert len({row["timestamp"] for row in rows}) == 73
    assert rows[0]["source_name"] == data.TARGET_NAME
    assert audit["dst_days"]["2023-11-05"]["physical_hours"] == 25


def test_assemble_missing_hub_and_uncaptured_day_remain_explicit(tmp_path):
    start = date(2024, 1, 1)
    data.fetch_day("oasis", start, cache_root=tmp_path / "raw", session=Session([Response(oasis_payload(start, omit=(5, "SP15")))]))
    csv_path, audit_path = data.assemble_labels(start, date(2024, 1, 2), cache_root=tmp_path / "raw", output_dir=tmp_path / "processed")
    with csv_path.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert len(rows) == 48 and audit["complete_hours"] == 23 and audit["missing_hours_count"] == 25
    assert rows[5]["solar_actual_mw"] == "" and "missing_hub:SP15" == rows[5]["quality_reason"]
    assert all(row["quality_reason"] == "not_captured" for row in rows[24:])


def test_assemble_selects_latest_complete_same_source_and_preserves_capture_time(tmp_path):
    start, end = date(2024, 1, 1), date(2024, 1, 2)
    data.fetch_oasis_block(start, end, cache_root=tmp_path / "raw", session=Session([Response(range_payload(start, end))]))
    day_capture = data.fetch_day("oasis", start, cache_root=tmp_path / "raw", session=Session([Response(oasis_payload(start).replace(b"-1.12345", b"2.0"))]))
    latest_meta = json.loads((day_capture / "source.json").read_text(encoding="utf-8"))
    csv_path, audit_path = data.assemble_labels(start, end, cache_root=tmp_path / "raw", output_dir=tmp_path / "processed")
    with csv_path.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert len(rows) == 48 and audit["overlapping_capture_rows"] == 24
    assert all(float(row["solar_actual_mw"]) == 6 for row in rows[:24])
    assert all(row["collected_at_utc"] == latest_meta["collected_at_utc"] and row["raw_sha256"] == latest_meta["sha256"] for row in rows[:24])
    assert all(float(row["solar_actual_mw"]) == -3.37035 for row in rows[24:])


def test_assemble_refuses_tampered_original_raw(tmp_path):
    day = date(2024, 1, 1)
    capture = data.fetch_day("oasis", day, cache_root=tmp_path / "raw", session=Session([Response(oasis_payload(day))]))
    (capture / "raw.csv").write_bytes(b"corrupt original")
    with pytest.raises(data.SourceError, match="Raw cache hash mismatch"):
        data.assemble_labels(day, day, cache_root=tmp_path / "raw", output_dir=tmp_path / "processed")
    assert not list((tmp_path / "processed").glob("labels_*"))
