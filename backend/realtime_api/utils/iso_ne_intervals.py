"""One observation contract for online features and stored evaluation labels.

Load is the sum of eight zonal hourly means, indexed by hour END. PV is
indexed by hour START. Partial hours may be model inputs, never final labels.
Legacy naive timestamps cannot represent the repeated DST hour: omit ambiguous
hours instead of silently merging them. No database migration is performed here.
"""
import numpy as np
import pandas as pd

ZONE_IDS = tuple(range(4001, 4009))
ACTUAL_REGION = "NewEngland_zonal_HE"
ACTUAL_SOURCE = "iso_ne_zonal_he_v2"


def actual_label_sql(alias="load_predictions"):
    """Aliases are application constants, never request input. Old labels stay archived."""
    return (f"CASE WHEN LOCATE('zonal_he_v2', {alias}.data_source) > 0 THEN "
            f"(SELECT a.actual_load_mw FROM actual_load_data a "
            f"WHERE a.timestamp = {alias}.target_timestamp "
            f"AND a.region = '{ACTUAL_REGION}' AND a.data_source = '{ACTUAL_SOURCE}' LIMIT 1) "
            "ELSE NULL END")


def records(payload, key):
    if isinstance(payload, dict):
        if key in payload:
            value = payload[key]
            return value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        for value in payload.values():
            found = records(value, key)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = records(value, key)
            if found:
                return found
    return []


def zonal_hourly(items, minimum_samples=8, now=None):
    """Deduplicate five-minute slots, validate values, and exclude open hours."""
    rows = []
    now = pd.Timestamp.now(tz="America/New_York") if now is None else pd.Timestamp(now)
    if now.tzinfo is not None:
        now = now.tz_convert("America/New_York").tz_localize(None)
    cutoff = now.floor("h")
    safe_hours, slots = {}, {}
    for item in items:
        try:
            zone = int(item.get("load_zone_id", -1))
            if zone not in ZONE_IDS:
                continue
            begin = item.get("interval_begin_date")
            if begin not in slots:
                slots[begin] = None
                ts = pd.Timestamp(begin)
                if pd.isna(ts):
                    continue
                if ts.tzinfo is not None:
                    ts = ts.tz_convert("America/New_York").tz_localize(None)
                if ts.minute % 5 or ts.second or ts.microsecond or ts.nanosecond:
                    continue
                start = ts.floor("h")
                end = start + pd.Timedelta(hours=1)
                if end > cutoff:
                    continue
                # Check each hour once, not for every zone/sample on every refresh.
                if start not in safe_hours:
                    edges = pd.DatetimeIndex([start, end]).tz_localize(
                        "America/New_York", ambiguous="NaT", nonexistent="NaT")
                    safe_hours[start] = not edges.isna().any()
                if safe_hours[start]:
                    slots[begin] = (ts, start)
            if slots[begin] is None:
                continue
            ts, start = slots[begin]
            values = []
            for name in ("estimated_btm_pv_mw", "estimated_load_mw"):
                try:
                    value = float(item.get(name))
                except (TypeError, ValueError, OverflowError):
                    value = np.nan
                values.append(value if np.isfinite(value) and value >= 0 else np.nan)
            rows.append((ts, start, zone, *values))
        except (TypeError, ValueError, OverflowError):
            continue
    load = pd.DataFrame(index=pd.DatetimeIndex([], name="ts_local"), columns=["load", "minimum_samples"], dtype=float)
    pv = pd.DataFrame(index=pd.DatetimeIndex([], name="ts_start"), columns=["pv_mw", "rt_demand", "minimum_samples"], dtype=float)
    if not rows:
        return load, pv
    raw = pd.DataFrame(rows, columns=["sample", "ts_start", "zone", "pv", "load"])
    raw = raw.drop_duplicates(["sample", "zone"], keep="last")
    grouped = raw.groupby(["ts_start", "zone"])
    means, counts = {}, {}
    for name in ("pv", "load"):
        means[name] = grouped[name].mean().unstack().reindex(columns=ZONE_IDS)
        counts[name] = grouped[name].count().unstack().reindex(columns=ZONE_IDS).fillna(0).min(axis=1)
    load_ok = means["load"].notna().all(axis=1) & (counts["load"] >= minimum_samples)
    pv_ok = means["pv"].notna().all(axis=1) & (counts["pv"] >= minimum_samples)
    load = pd.DataFrame({"load": means["load"].loc[load_ok].sum(axis=1),
                         "minimum_samples": counts["load"].loc[load_ok].astype(int)})
    load.index = load.index + pd.Timedelta(hours=1)
    load.index.name = "ts_local"
    pv = pd.DataFrame({"pv_mw": means["pv"].loc[pv_ok].sum(axis=1),
                       "rt_demand": means["load"].sum(axis=1, min_count=8).where(load_ok).loc[pv_ok],
                       "minimum_samples": counts["pv"].loc[pv_ok].astype(int)})
    return load.sort_index(), pv.sort_index()
