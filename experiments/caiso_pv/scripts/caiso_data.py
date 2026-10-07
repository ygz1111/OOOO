"""Independent, immutable CAISO Actual Solar source capture and normalization.

No production modules or credentials are loaded. `probe` captures at most six
days. `download` requires --sample-reviewed and the approved authorization file;
run it only after the human has confirmed the source definition and real sample. OASIS and
Today's Outlook are separate labels and must never be spliced together.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
import uuid
import zipfile
from collections import defaultdict
from datetime import date, datetime, time as day_time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

LA = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc
HUBS = ("NP15", "SP15", "ZP26")
ROOT = Path(__file__).resolve().parents[1]
SCOPE = {
    "oasis": "OASIS SLD_REN_FCST Solar ACTUAL, NP15+SP15+ZP26; EIR/PIRP scope stated in 2017 specification; current expansion not independently verified",
    "outlook": "Today's Outlook telemetry Solar; photovoltaic and solar thermal combined; hybrid solar component included",
}
TARGET_NAME = "CAISO OASIS Solar Actual Generation"
TARGET_NAME_ZH = "CAISO OASIS 区域太阳能实际发电功率"
FIELDS = [
    "timestamp", "interval_end_utc", "local_timestamp", "local_fold",
    "solar_actual_mw", "is_complete", "quality_reason", "sample_count",
    "expected_sample_count", "hub_count", "expected_hub_count",
    "source_kind", "source_id", "unit", "source_resolution_minutes",
    "aggregation", "interval_semantics", "source_url", "collected_at_utc",
    "raw_sha256",
    "source_name", "source_name_zh",
]


class SourceError(ValueError):
    """Payload contradicts the selected official Actual source contract."""


class NoDataError(SourceError):
    """Official source explicitly returned no observations."""


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def day_bounds(operating_date: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(operating_date, day_time(), LA).astimezone(UTC),
        datetime.combine(operating_date + timedelta(days=1), day_time(), LA).astimezone(UTC),
    )


def latest_complete_date(now: datetime | None = None) -> date:
    """Latest elapsed LA calendar day; data completeness is checked separately."""
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("now must have an explicit timezone")
    return value.astimezone(LA).date() - timedelta(days=1)


def source_url(source: str, operating_date: date) -> str:
    if source == "outlook":
        return f"https://www.caiso.com/outlook/history/{operating_date:%Y%m%d}/renewables.csv"
    if source != "oasis":
        raise ValueError("source must be oasis or outlook")
    return oasis_range_url(operating_date, operating_date)


def oasis_range_url(start_date: date, end_date: date) -> str:
    start = day_bounds(start_date)[0]
    end = day_bounds(end_date)[1]
    if end_date < start_date or end - start > timedelta(days=31):
        raise ValueError("OASIS range must contain at most 31 physical UTC days")
    params = {
        "resultformat": 6, "queryname": "SLD_REN_FCST", "version": 1,
        "market_run_id": "ACTUAL",
        "startdatetime": start.strftime("%Y%m%dT%H:%M-0000"),
        "enddatetime": end.strftime("%Y%m%dT%H:%M-0000"),
    }
    return "https://oasis.caiso.com/oasisapi/SingleZip?" + urlencode(params)


def _grid(operating_date: date, source: str, provenance: dict[str, Any]) -> list[dict[str, Any]]:
    start, end = day_bounds(operating_date)
    rows = []
    while start < end:
        local = start.astimezone(LA)
        rows.append({
            "timestamp": iso_utc(start), "interval_end_utc": iso_utc(start + timedelta(hours=1)),
            "local_timestamp": local.isoformat(), "local_fold": local.fold,
            "solar_actual_mw": None, "is_complete": False, "quality_reason": "missing_source_hour",
            "sample_count": 0, "expected_sample_count": 1 if source == "oasis" else 12,
            "hub_count": 0, "expected_hub_count": 3 if source == "oasis" else 0,
            "source_kind": "actual", "source_id": f"caiso_{source}_solar_actual",
            "unit": "MW", "source_resolution_minutes": 60 if source == "oasis" else 5,
            "aggregation": "sum_of_three_distinct_trading_hubs" if source == "oasis" else "arithmetic_mean_of_12_five_minute_values",
            "interval_semantics": "explicit_utc_start_end" if source == "oasis" else "clock_labels_treated_as_interval_start_analysis_convention",
            "source_url": provenance.get("source_url", source_url(source, operating_date)),
            "collected_at_utc": provenance.get("collected_at_utc", ""),
            "raw_sha256": provenance.get("sha256", ""),
            "source_name": TARGET_NAME if source == "oasis" else "CAISO Today's Outlook Solar Telemetry",
            "source_name_zh": TARGET_NAME_ZH if source == "oasis" else "CAISO Today's Outlook 区域太阳能遥测功率",
        })
        start += timedelta(hours=1)
    return rows


def _number(raw: str | None) -> Decimal:
    try:
        value = Decimal((raw or "").strip())
    except InvalidOperation as exc:
        raise SourceError("missing_or_invalid_numeric_value") from exc
    if not value.is_finite():
        raise SourceError("nonfinite_numeric_value")
    return value


def _utc_timestamp(raw: str | None) -> datetime:
    try:
        value = datetime.fromisoformat((raw or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceError("invalid_interval_timestamp") from exc
    if value.tzinfo is None:
        raise SourceError("interval_timezone_missing")
    return value.astimezone(UTC)


def _oasis_csv(raw: bytes) -> str:
    if not raw.startswith(b"PK"):
        return raw.decode("utf-8-sig")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if sum(item.file_size for item in members) > 50 * 1024 * 1024:
            raise SourceError("OASIS payload exceeds bounded capture size")
        csv_members = [item for item in members if item.filename.lower().endswith(".csv")]
        if len(csv_members) == 1:
            return archive.read(csv_members[0]).decode("utf-8-sig")
        for item in members:
            if item.filename.lower().endswith(".xml"):
                text = archive.read(item).decode("utf-8-sig")
                if "No data returned" in text:
                    raise NoDataError("OASIS ERR_CODE 1000: no data returned")
        raise SourceError("OASIS returned no unambiguous CSV report")


def normalize_oasis(raw: bytes, operating_date: date, provenance: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Require Solar + ACTUAL + actual XML item and all three hubs every hour."""
    reader = csv.DictReader(io.StringIO(_oasis_csv(raw)))
    required = {"RENEWABLE_TYPE", "MARKET_RUN_ID", "XML_DATA_ITEM", "MW", "TRADING_HUB", "INTERVALSTARTTIME_GMT", "INTERVALENDTIME_GMT"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise SourceError("OASIS Actual report columns missing")
    hourly = _grid(operating_date, "oasis", provenance)
    grid = {row["timestamp"]: row for row in hourly}
    groups: dict[str, dict[str, Decimal]] = defaultdict(dict)
    errors: dict[str, list[str]] = defaultdict(list)
    issues = []
    raw_count = solar_count = negative_count = 0
    for index, record in enumerate(reader, start=2):
        raw_count += 1
        if record["RENEWABLE_TYPE"] != "Solar":
            continue
        if record["MARKET_RUN_ID"] != "ACTUAL" or record["XML_DATA_ITEM"] != "RENEW_FCST_ACT_MW":
            raise SourceError(f"row {index}: Solar Forecast is not an Actual label")
        hub = record["TRADING_HUB"]
        if hub not in HUBS:
            issues.append({"line": index, "reason": "unexpected_hub_not_aggregated", "hub": hub})
            continue
        solar_count += 1
        timestamp = None
        try:
            start = _utc_timestamp(record["INTERVALSTARTTIME_GMT"])
            timestamp = iso_utc(start)
            end = _utc_timestamp(record["INTERVALENDTIME_GMT"])
            if timestamp not in grid or end - start != timedelta(hours=1):
                raise SourceError("interval_outside_local_day_or_not_one_hour")
            if record.get("OPR_DT") and record["OPR_DT"] != operating_date.isoformat():
                raise SourceError("operating_date_mismatch")
            if hub in groups[timestamp]:
                raise SourceError("duplicate_hub_record")
            value = _number(record["MW"])
            negative_count += int(value < 0)
            groups[timestamp][hub] = value
        except SourceError as exc:
            if timestamp in grid:
                errors[timestamp].append(f"{exc}:{hub}")
            issues.append({"line": index, "reason": str(exc), "hub": hub, "timestamp": timestamp})
    if not solar_count:
        raise NoDataError("No Solar ACTUAL rows for expected trading hubs")
    for row in hourly:
        timestamp = row["timestamp"]
        values = groups[timestamp]
        missing_hubs = sorted(set(HUBS) - set(values))
        reasons = errors[timestamp] + (["missing_hub:" + ",".join(missing_hubs)] if missing_hubs else [])
        row.update(hub_count=len(values), sample_count=1 if not reasons else 0)
        if reasons:
            row["quality_reason"] = ";".join(reasons)
        else:
            row.update(solar_actual_mw=float(sum(values.values(), Decimal(0))), is_complete=True, quality_reason="complete")
    return hourly, _quality(hourly, raw_count, solar_count, negative_count, issues)


def normalize_outlook(raw: bytes, operating_date: date, provenance: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Map local clock slots without inventing either fold of an ambiguous hour.

    The official chart CSV has no UTC offset/fold column. A single 01:xx on a
    fall-back day cannot represent two distinct observations. Both physical
    hours remain explicit missing rows. Spring 02:xx blank placeholders are
    documented separately and are not physical hours.
    """
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not reader.fieldnames or not {"Time", "Solar"}.issubset(reader.fieldnames):
        raise SourceError("Today's Outlook Time/Solar columns missing")
    hourly = _grid(operating_date, "outlook", provenance)
    start, end = day_bounds(operating_date)
    physical_slots: dict[str, list[datetime]] = defaultdict(list)
    while start < end:
        physical_slots[start.astimezone(LA).strftime("%H:%M")].append(start)
        start += timedelta(minutes=5)
    observed: dict[str, list[str]] = defaultdict(list)
    issues = []
    raw_count = negative_count = nonexistent_blanks = 0
    for index, record in enumerate(reader, start=2):
        raw_count += 1
        clock = (record["Time"] or "").strip()
        try:
            parsed = datetime.strptime(clock, "%H:%M")
            if parsed.minute % 5 or parsed.strftime("%H:%M") != clock:
                raise ValueError("not a five-minute clock label")
        except ValueError:
            raise SourceError(f"row {index}: invalid five-minute Time label")
        value = record["Solar"] or ""
        if clock not in physical_slots:
            if value.strip():
                raise SourceError(f"row {index}: nonexistent_local_time_with_value; timezone contract inconsistent")
            else:
                nonexistent_blanks += 1
            continue
        observed[clock].append(value)
        try:
            negative_count += int(_number(value) < 0)
        except SourceError:
            pass
    if not raw_count:
        raise NoDataError("Today's Outlook CSV has no records")
    for row in hourly:
        start = _utc_timestamp(row["timestamp"])
        values = []
        reasons = set()
        for step in range(12):
            clock = (start + timedelta(minutes=5 * step)).astimezone(LA).strftime("%H:%M")
            if len(physical_slots[clock]) > 1:
                reasons.add("ambiguous_local_hour_no_utc_offset")
                continue
            records = observed.get(clock, [])
            if not records:
                reasons.add("missing_five_minute_point")
            elif len(records) != 1:
                reasons.add("duplicate_clock_label")
            else:
                try:
                    values.append(_number(records[0]))
                except SourceError as exc:
                    reasons.add(str(exc))
        row["sample_count"] = len(values)
        if reasons or len(values) != 12:
            row["quality_reason"] = ";".join(sorted(reasons or {"incomplete_hour"}))
        else:
            row.update(solar_actual_mw=float(sum(values, Decimal(0)) / Decimal(12)), is_complete=True, quality_reason="complete")
    report = _quality(hourly, raw_count, raw_count, negative_count, issues)
    report["nonexistent_spring_clock_placeholders"] = nonexistent_blanks
    report["interval_start_convention_requires_source_review"] = True
    return hourly, report


def _quality(rows: list[dict[str, Any]], raw_count: int, solar_count: int, negative_count: int, issues: list[dict[str, Any]]) -> dict[str, Any]:
    complete = [row for row in rows if row["is_complete"]]
    return {
        "expected_physical_hours": len(rows), "complete_hours": len(complete),
        "source_complete": len(complete) == len(rows), "raw_rows": raw_count,
        "solar_rows": solar_count, "negative_source_values": negative_count,
        "negative_complete_hourly_totals": sum(row["solar_actual_mw"] < 0 for row in complete),
        "missing_hours": [{"timestamp": row["timestamp"], "local_timestamp": row["local_timestamp"], "reason": row["quality_reason"]} for row in rows if not row["is_complete"]],
        "record_issues": issues,
    }


def normalize(raw: bytes, operating_date: date, source: str, provenance: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if source not in SCOPE:
        raise ValueError("source must be oasis or outlook")
    try:
        return (normalize_oasis if source == "oasis" else normalize_outlook)(raw, operating_date, provenance)
    except NoDataError as exc:
        rows = _grid(operating_date, source, provenance)
        for row in rows:
            row["quality_reason"] = "official_no_data"
        report = _quality(rows, 0, 0, 0, [{"reason": str(exc)}])
        report["source_error"] = str(exc)
        return rows, report


def write_hourly(path: Path, rows: list[dict[str, Any]]) -> None:
    """Exclusive creation; an existing dataset is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _request(session: Any, url: str, max_attempts: int, sleep: Any) -> Any:
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3")
    for attempt in range(max_attempts):
        response = session.get(url, timeout=(10, 60))
        if response.status_code == 429 or 500 <= response.status_code < 600:
            if attempt + 1 < max_attempts:
                try:
                    retry_seconds = float(response.headers.get("Retry-After", "5"))
                except ValueError:
                    retry_seconds = 5
                sleep(min(60, max(5, retry_seconds, 5 * (attempt + 1))))
                continue
        response.raise_for_status()
        return response
    raise RuntimeError("Request attempts exhausted")


def _cached_capture(directory: Path, url: str, source: str) -> Path | None:
    for capture in sorted(directory.glob("capture-*"), reverse=True):
        meta_path = capture / "source.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        raw_path = capture / meta["raw_filename"]
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != meta["sha256"]:
            raise SourceError(f"Raw cache hash mismatch: {raw_path}")
        if meta.get("source_url") != url or meta.get("source_id") != f"caiso_{source}_solar_actual":
            raise SourceError("Cached source definition/date differs from requested source")
        if meta.get("quality", {}).get("source_complete"):
            return capture
    return None


def _response_meta(response: Any, url: str, source: str) -> dict[str, Any]:
    raw = response.content
    return {
        "source_url": url, "final_url": response.url,
        "collected_at_utc": iso_utc(datetime.now(UTC)), "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw), "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type"),
        "source_timezone": "America/Los_Angeles", "source_kind": "actual",
        "source_id": f"caiso_{source}_solar_actual", "resource": "Solar", "unit": "MW",
        "source_name": TARGET_NAME if source == "oasis" else "CAISO Today's Outlook Solar Telemetry",
        "source_name_zh": TARGET_NAME_ZH if source == "oasis" else "CAISO Today's Outlook 区域太阳能遥测功率",
        "source_resolution_minutes": 60 if source == "oasis" else 5,
        "target_scope": SCOPE[source], "original_publication_time": None,
        "original_publication_time_note": "collection time is not the historical first publication time",
        "raw_filename": "raw.zip" if raw.startswith(b"PK") else "raw.csv",
    }


def _publish_capture(directory: Path, raw: bytes, meta: dict[str, Any], rows: list[dict[str, Any]],
                     daily: dict[date, list[dict[str, Any]]] | None = None) -> Path:
    identity = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    staging = directory / (".pending-" + identity)
    staging.mkdir()
    with (staging / meta["raw_filename"]).open("xb") as stream:
        stream.write(raw)
    with (staging / "source.json").open("x", encoding="utf-8") as stream:
        json.dump(meta, stream, indent=2, ensure_ascii=False)
    write_hourly(staging / "hourly.csv", rows)
    if daily is not None:
        for operating_date, day_rows in daily.items():
            write_hourly(staging / "daily" / f"{operating_date.isoformat()}.hourly.csv", day_rows)
    final = directory / ("capture-" + identity)
    staging.rename(final)
    return final


def fetch_day(source: str, operating_date: date, *, cache_root: Path | None = None,
              session: Any = None, max_attempts: int = 3, sleep: Any = time.sleep) -> Path:
    """Resume verified complete snapshots; preserve incomplete attempts for audit.

    A capture is published as an entire directory only after all files are
    written. Interrupted staging directories are never read as valid cache.
    Bounded 429/5xx retries keep official rate limits; SSL failures are exposed.
    """
    if operating_date > latest_complete_date():
        raise ValueError("Only elapsed LA operating dates may be captured")
    url = source_url(source, operating_date)
    day_dir = (cache_root or ROOT / "data" / "raw") / source / operating_date.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    cached = _cached_capture(day_dir, url, source)
    if cached is not None:
        return cached
    if session is None:
        import requests
        session = requests.Session()
    response = _request(session, url, max_attempts, sleep)
    raw = response.content
    meta = _response_meta(response, url, source)
    meta["operating_date_local"] = operating_date.isoformat()
    rows, quality = normalize(raw, operating_date, source, meta)
    meta["quality"] = quality
    return _publish_capture(day_dir, raw, meta, rows)


def _split_oasis_payload(raw: bytes, dates: list[date]) -> tuple[dict[date, bytes], list[dict[str, Any]]]:
    """Split in memory; one range raw ZIP is retained once, never 28 copies."""
    reader = csv.DictReader(io.StringIO(_oasis_csv(raw)))
    if not reader.fieldnames or "INTERVALSTARTTIME_GMT" not in reader.fieldnames:
        raise SourceError("OASIS UTC interval columns missing")
    fields = reader.fieldnames
    selected: dict[date, list[dict[str, str]]] = {day: [] for day in dates}
    issues = []
    for line, row in enumerate(reader, start=2):
        try:
            day = _utc_timestamp(row.get("INTERVALSTARTTIME_GMT")).astimezone(LA).date()
        except SourceError:
            try:
                day = date.fromisoformat(row.get("OPR_DT", ""))
            except ValueError:
                issues.append({"line": line, "reason": "unassignable_interval_timestamp"})
                continue
        if day in selected:
            selected[day].append(row)
        else:
            issues.append({"line": line, "reason": "record_outside_requested_range", "operating_date": day.isoformat()})
    payloads = {}
    for day, records in selected.items():
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
        payloads[day] = stream.getvalue().encode("utf-8")
    return payloads, issues


def fetch_oasis_block(start_date: date, end_date: date, *, cache_root: Path | None = None,
                      session: Any = None, max_attempts: int = 3, sleep: Any = time.sleep) -> Path:
    if end_date > latest_complete_date():
        raise ValueError("Only elapsed LA operating dates may be captured")
    url = oasis_range_url(start_date, end_date)
    directory = (cache_root or ROOT / "data" / "raw") / "oasis_blocks" / f"{start_date}_{end_date}"
    directory.mkdir(parents=True, exist_ok=True)
    cached = _cached_capture(directory, url, "oasis")
    if cached is not None:
        return cached
    if session is None:
        import requests
        session = requests.Session()
    response = _request(session, url, max_attempts, sleep)
    raw = response.content
    meta = _response_meta(response, url, "oasis")
    dates = [start_date + timedelta(days=index) for index in range((end_date - start_date).days + 1)]
    meta.update(operating_date_start_local=start_date.isoformat(), operating_date_end_local=end_date.isoformat())
    try:
        payloads, split_issues = _split_oasis_payload(raw, dates)
    except NoDataError:
        payloads, split_issues = {day: raw for day in dates}, []
    daily = {}
    quality_by_date = {}
    all_rows = []
    for day in dates:
        rows, quality = normalize(payloads[day], day, "oasis", meta)
        daily[day] = rows
        quality_by_date[day.isoformat()] = quality
        all_rows.extend(rows)
    meta["quality_by_date"] = quality_by_date
    meta["quality"] = {
        "source_complete": all(report["source_complete"] for report in quality_by_date.values()) and not split_issues,
        "expected_physical_hours": len(all_rows),
        "complete_hours": sum(report["complete_hours"] for report in quality_by_date.values()),
        "incomplete_dates": [day for day, report in quality_by_date.items() if not report["source_complete"]],
        "range_record_issues": split_issues,
    }
    return _publish_capture(directory, raw, meta, all_rows, daily)


def authorize_bulk(source: str, authorization_path: Path | None = None) -> None:
    """The CLI flag cannot replace the root's recorded human authorization."""
    path = authorization_path or ROOT / "logs" / "training_authorization.json"
    if not path.exists():
        raise SourceError("Human source/sample authorization file is missing")
    authorization = json.loads(path.read_text(encoding="utf-8"))
    expected = "CAISO OASIS Solar ACTUAL, NP15+SP15+ZP26" if source == "oasis" else "CAISO Today's Outlook Solar telemetry"
    if (authorization.get("status") != "approved"
            or authorization.get("bulk_download_authorized") is not True
            or not authorization.get("label_confirmation")
            or authorization.get("official_label") != expected):
        raise SourceError("Human source/sample authorization is not approved for this label")


def _date_chunks(start_date: date, end_date: date, chunk_days: int) -> list[tuple[date, date]]:
    if not 1 <= chunk_days <= 31:
        raise ValueError("chunk_days must be from 1 to 31")
    chunks = []
    while start_date <= end_date:
        block_end = min(end_date, start_date + timedelta(days=chunk_days - 1))
        while day_bounds(block_end)[1] - day_bounds(start_date)[0] > timedelta(days=31):
            block_end -= timedelta(days=1)
        chunks.append((start_date, block_end))
        start_date = block_end + timedelta(days=1)
    return chunks


def assemble_labels(start_date: date, end_date: date, *, cache_root: Path | None = None,
                    output_dir: Path | None = None) -> tuple[Path, Path]:
    """Revalidate original official raw data and publish a new hourly label table.

    Retain every physical requested hour, including missing labels. For overlap,
    take the newest complete observation; an incomplete later capture cannot
    erase a prior qualified Actual. Per-hour provenance retains that capture's
    original collection time and raw hash. No telemetry or estimated values.
    """
    if end_date < start_date:
        raise ValueError("end_date must follow start_date")
    raw_root = cache_root or ROOT / "data" / "raw"
    destination = output_dir or ROOT / "data" / "processed"
    dates = [start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)]
    selected = {}
    ranks = {}
    capture_audits = []
    overlaps = revisions = 0
    captures = sorted(set(raw_root.glob("oasis_blocks/*/capture-*")) | set(raw_root.glob("oasis/*/capture-*")))
    for capture in captures:
        meta = json.loads((capture / "source.json").read_text(encoding="utf-8"))
        capture_start = date.fromisoformat(meta.get("operating_date_start_local") or meta["operating_date_local"])
        capture_end = date.fromisoformat(meta.get("operating_date_end_local") or meta["operating_date_local"])
        if capture_end < start_date or capture_start > end_date:
            continue
        if meta.get("source_id") != "caiso_oasis_solar_actual" or meta.get("source_kind") != "actual":
            raise SourceError(f"Non-OASIS Actual source in label cache: {capture}")
        expected_url = oasis_range_url(capture_start, capture_end)
        if meta.get("source_url") != expected_url:
            raise SourceError(f"Source query/date mismatch: {capture}")
        raw = (capture / meta["raw_filename"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
            raise SourceError(f"Raw cache hash mismatch: {capture}")
        collected = _utc_timestamp(meta.get("collected_at_utc"))
        capture_dates = [capture_start + timedelta(days=offset) for offset in range((capture_end - capture_start).days + 1)]
        try:
            payloads, split_issues = _split_oasis_payload(raw, capture_dates)
        except NoDataError:
            payloads, split_issues = {day: raw for day in capture_dates}, []
        quality_by_date = {}
        for day in capture_dates:
            if day < start_date or day > end_date:
                continue
            rows, report = normalize(payloads[day], day, "oasis", meta)
            quality_by_date[day.isoformat()] = report
            for row in rows:
                timestamp = row["timestamp"]
                rank = (int(row["is_complete"]), collected, str(capture))
                if timestamp in selected:
                    overlaps += 1
                    old = selected[timestamp]
                    if old["is_complete"] and row["is_complete"] and old["solar_actual_mw"] != row["solar_actual_mw"]:
                        revisions += 1
                if timestamp not in ranks or rank > ranks[timestamp]:
                    ranks[timestamp] = rank
                    selected[timestamp] = row
        capture_audits.append({
            "capture": str(capture.resolve()), "source_url": meta["source_url"],
            "collected_at_utc": meta["collected_at_utc"], "raw_sha256": meta["sha256"],
            "quality_by_date": quality_by_date, "range_record_issues": split_issues,
        })
    rows = []
    day_summary = {}
    for day in dates:
        day_rows = []
        for blank in _grid(day, "oasis", {}):
            row = selected.get(blank["timestamp"])
            if row is None:
                row = blank
                row.update(quality_reason="not_captured", source_url="")
            day_rows.append(row)
        rows.extend(day_rows)
        day_summary[day.isoformat()] = {
            "physical_hours": len(day_rows), "complete_hours": sum(row["is_complete"] for row in day_rows),
            "missing_hours": [{"timestamp": row["timestamp"], "reason": row["quality_reason"]} for row in day_rows if not row["is_complete"]],
        }
    complete = [row for row in rows if row["is_complete"]]
    missing = [row for row in rows if not row["is_complete"]]
    yearly = {}
    monthly = {}
    negative_by_local_hour = {str(hour): 0 for hour in range(24)}
    night_proxy_negative = 0
    night_proxy_complete = 0
    for row in rows:
        for table, key in ((yearly, row["local_timestamp"][:4]), (monthly, row["local_timestamp"][:7])):
            entry = table.setdefault(key, {"expected_physical_hours": 0, "complete_hours": 0, "missing_hours": 0, "negative_complete_hours": 0})
            entry["expected_physical_hours"] += 1
            entry["complete_hours"] += int(row["is_complete"])
            entry["missing_hours"] += int(not row["is_complete"])
            entry["negative_complete_hours"] += int(row["is_complete"] and row["solar_actual_mw"] < 0)
        if row["is_complete"]:
            local_hour = int(row["local_timestamp"][11:13])
            negative = row["solar_actual_mw"] < 0
            negative_by_local_hour[str(local_hour)] += int(negative)
            if local_hour >= 20 or local_hour < 6:
                night_proxy_complete += 1
                night_proxy_negative += int(negative)
    if len({row["timestamp"] for row in rows}) != len(rows):
        raise SourceError("Duplicate UTC target hours in assembled labels")
    utc_start, _ = day_bounds(start_date)
    _, utc_end = day_bounds(end_date)
    if len(rows) != int((utc_end - utc_start).total_seconds() / 3600):
        raise SourceError("Assembled requested UTC grid is not physically continuous")
    destination.mkdir(parents=True, exist_ok=True)
    identity = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    csv_path = destination / f"labels_caiso_oasis_solar_actual_{start_date}_{end_date}_{identity}.csv"
    audit_path = csv_path.with_suffix(".audit.json")
    write_hourly(csv_path, rows)
    audit = {
        "target_name": TARGET_NAME, "target_name_zh": TARGET_NAME_ZH, "source_id": "caiso_oasis_solar_actual",
        "source_kind": "actual", "unit": "MW", "aggregation": "sum of NP15, SP15 and ZP26 at the same UTC interval start",
        "requested_local_date_start": start_date.isoformat(), "requested_local_date_end": end_date.isoformat(),
        "requested_utc_start": iso_utc(utc_start), "requested_utc_end_exclusive": iso_utc(utc_end),
        "expected_physical_hours": len(rows), "complete_hours": len(complete), "missing_hours_count": len(missing),
        "first_complete_target_utc": complete[0]["timestamp"] if complete else None,
        "last_complete_target_utc": complete[-1]["timestamp"] if complete else None,
        "negative_complete_hourly_totals": sum(row["solar_actual_mw"] < 0 for row in complete),
        "negative_by_local_clock_hour": negative_by_local_hour,
        "night_clock_proxy": {"definition": "LA local hours 20-23 and 00-05; descriptive clock bin, not an astronomical night classification", "complete_hours": night_proxy_complete, "negative_hours": night_proxy_negative},
        "by_local_year": yearly, "by_local_month": monthly,
        "zero_complete_hourly_totals": sum(row["solar_actual_mw"] == 0 for row in complete),
        "minimum_complete_mw": min((row["solar_actual_mw"] for row in complete), default=None),
        "maximum_complete_mw": max((row["solar_actual_mw"] for row in complete), default=None),
        "duplicate_utc_targets_after_selection": 0, "overlapping_capture_rows": overlaps, "observed_value_revision_comparisons": revisions,
        "selection_policy": "latest qualified complete Actual per UTC target; keep newest incomplete row only when no complete row exists",
        "dst_days": {day: summary for day, summary in day_summary.items() if summary["physical_hours"] != 24},
        "incomplete_dates": {day: summary for day, summary in day_summary.items() if summary["missing_hours"]},
        "missing_hours": [{"timestamp": row["timestamp"], "local_timestamp": row["local_timestamp"], "reason": row["quality_reason"]} for row in missing],
        "original_publication_time": None,
        "online_availability_note": "Official specification states Actual is published next day. Timestamp before origin alone does not establish then-available online input.",
        "raw_source_revalidated": True, "captures": capture_audits,
        "csv_path": str(csv_path.resolve()), "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
    }
    with audit_path.open("x", encoding="utf-8") as stream:
        json.dump(audit, stream, indent=2, ensure_ascii=False)
    return csv_path, audit_path


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use an ISO date YYYY-MM-DD") from exc


class _PacedSession:
    """Throttle actual OASIS HTTP calls, including retries; cached days cost no sleep."""
    def __init__(self, session: Any):
        self.session = session
        self.last_request = None

    def get(self, url: str, timeout: Any) -> Any:
        if "oasis.caiso.com/" in url:
            if self.last_request is not None:
                remaining = 6 - (time.monotonic() - self.last_request)
                if remaining > 0:
                    time.sleep(remaining)
            self.last_request = time.monotonic()
        return self.session.get(url, timeout=timeout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("probe", help="Capture at most six real dates for source review")
    probe.add_argument("--source", choices=tuple(SCOPE), default="oasis")
    probe.add_argument("--date", type=_date, action="append")
    download = commands.add_parser("download", help="Only after explicit human sample/source confirmation")
    download.add_argument("--source", choices=tuple(SCOPE), required=True)
    download.add_argument("--start", type=_date, default=date(2023, 1, 1))
    download.add_argument("--end", type=_date)
    download.add_argument("--sample-reviewed", action="store_true", help="Human has explicitly confirmed this source and real sample")
    download.add_argument("--chunk-days", type=int, choices=range(1, 32), default=28, help="OASIS range size; UTC duration never exceeds31days")
    assemble = commands.add_parser("assemble", help="Revalidate captured raw Actual and create new labels/audit files without network")
    assemble.add_argument("--start", type=_date, required=True)
    assemble.add_argument("--end", type=_date)
    for command in (probe, download, assemble):
        command.add_argument("--cache-root", type=Path)
    args = parser.parse_args(argv)
    default_cache = ROOT / "data" / "raw"
    if args.command == "probe":
        default_cache /= "sample"
    args.cache_root = (args.cache_root or default_cache).resolve()
    if not args.cache_root.is_relative_to(ROOT.resolve()):
        parser.error("Capture output must remain inside experiments/caiso_pv")
    if args.command == "assemble":
        csv_path, audit_path = assemble_labels(args.start, args.end or latest_complete_date(), cache_root=args.cache_root)
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        print(json.dumps({"labels_csv": str(csv_path.resolve()), "audit_json": str(audit_path.resolve()),
                          "expected_physical_hours": audit["expected_physical_hours"], "complete_hours": audit["complete_hours"],
                          "missing_hours_count": audit["missing_hours_count"]}, ensure_ascii=False))
        return 0
    if args.command == "probe":
        dates = sorted(set(args.date or [latest_complete_date()]))
        if len(dates) > 6:
            parser.error("probe accepts at most six dates; no implicit bulk download")
    else:
        if not args.sample_reviewed:
            parser.error("Explicit human sample/source confirmation is required before bulk download")
        try:
            authorize_bulk(args.source)
        except (SourceError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        end = args.end or latest_complete_date()
        if end < args.start or end > latest_complete_date():
            parser.error("Range must end after start and at an elapsed LA date")
        dates = [args.start + timedelta(days=offset) for offset in range((end - args.start).days + 1)]
    failures = 0
    import requests
    log_dir = ROOT / "logs" / "source_probe"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / ("capture_run_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".jsonl")
    with requests.Session() as requests_session, log_path.open("x", encoding="utf-8") as log_stream:
        session = _PacedSession(requests_session)
        ranges = _date_chunks(dates[0], dates[-1], args.chunk_days) if args.command == "download" and args.source == "oasis" else [(day, day) for day in dates]
        for operating_date, range_end in ranges:
            try:
                if args.command == "download" and args.source == "oasis":
                    capture = fetch_oasis_block(operating_date, range_end, cache_root=args.cache_root, session=session)
                else:
                    capture = fetch_day(args.source, operating_date, cache_root=args.cache_root, session=session)
                meta = json.loads((capture / "source.json").read_text(encoding="utf-8"))
                result = {"date_start": operating_date.isoformat(), "date_end": range_end.isoformat(), "capture": str(capture), "quality": meta["quality"]}
                failures += int(not meta["quality"]["source_complete"])
            except Exception as exc:
                failures += 1
                url = oasis_range_url(operating_date, range_end) if args.source == "oasis" else source_url(args.source, operating_date)
                result = {"date_start": operating_date.isoformat(), "date_end": range_end.isoformat(), "source_url": url, "error_type": type(exc).__name__, "error": str(exc)}
            line = json.dumps(result, ensure_ascii=False)
            log_stream.write(line + "\n")
            log_stream.flush()
            print(line)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
