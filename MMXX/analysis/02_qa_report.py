# -*- coding: utf-8 -*-
"""
Step 2 - systematic QA report per workbook/year.
Reads every sheet, checks headers, time continuity (Date + Hr_End key),
missing values, duplicates and per-column summaries.
Writes a JSON report to out/<year>_qa.json and prints a compact summary.
"""
import json
import math
from pathlib import Path

import pandas as pd

DATA_DIR = Path(r"C:\MMXX\datas")
OUT_DIR = Path(r"C:\MMXX\analysis\out")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ZONE_KEYWORDS = ["ISO NE CA", "ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]


def norm_key(date, hr):
    # build canonical hour-ending datetime: hour ends at Hr_End o'clock of Date's day
    return pd.Timestamp(date.date()) + pd.Timedelta(hours=int(hr))


def analyze_workbook(path: Path) -> dict:
    xl = pd.ExcelFile(path)
    sheets = xl.sheet_names
    report = {"file": path.name, "sheets": sheets}

    # ---- Notes sheet: full text ----
    if "Notes" in sheets:
        notes = pd.read_excel(path, sheet_name="Notes", header=None)
        notes_rows = []
        for _, row in notes.iterrows():
            vals = ["" if (isinstance(v, float) and math.isnan(v)) else str(v).strip() for v in row.tolist()]
            notes_rows.append(vals)
        report["notes"] = notes_rows

    # ---- data sheets ----
    sheet_reports = {}
    for sh in sheets:
        if sh == "Notes":
            continue
        sr = {}
        df = pd.read_excel(path, sheet_name=sh)
        cols = list(df.columns)
        sr["n_cols"] = len(cols)
        sr["columns"] = [str(c) for c in cols]
        sr["n_rows"] = int(len(df))

        # date range / hr range
        df["_Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["_Hr"] = pd.to_numeric(df.get("Hr_End"), errors="coerce")
        df["_key"] = df.apply(lambda r: norm_key(r["_Date"], r["_Hr"]) if pd.notna(r["_Date"]) and pd.notna(r["_Hr"]) else pd.NaT, axis=1)
        good = df["_key"].notna()
        sr["date_min"] = str(df.loc[good, "_key"].min())
        sr["date_max"] = str(df.loc[good, "_key"].max())
        sr["n_bad_date_or_hr"] = int((~good).sum())
        sr["n_duplicate_keys"] = int(df.loc[good, "_key"].duplicated().sum())

        # time continuity: expected hourly slots over calendar span (1..24 per day)
        expected = set()
        if good.any():
            d0 = df.loc[good, "_Date"].min().date()
            d1 = df.loc[good, "_Date"].max().date()
            days = pd.date_range(pd.Timestamp(d0), pd.Timestamp(d1), freq="D")
            for d in days:
                for h in range(1, 25):
                    expected.add(norm_key(d, h))
        actual = set(df.loc[good, "_key"].dropna())
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        sr["n_days_span"] = len(set(pd.Timestamp(x).date() for x in expected))
        sr["expected_hours"] = len(expected)
        sr["missing_hour_slots"] = [str(x) for x in missing]
        sr["extra_slots_outside_expected"] = [str(x) for x in extra]

        # days with != 24 rows (DST-ish check)
        cnt = df.loc[good].groupby(df.loc[good, "_Date"].dt.date).size()
        odd_days = {str(k): int(v) for k, v in cnt.items() if v != 24}
        sr["days_with_rows_ne_24"] = odd_days

        # duplicates full-row
        sr["n_fullrow_duplicates"] = int(df.duplicated().sum())

        # missing values per column
        mv = {str(c): int(v) for c, v in df.isna().sum().items()}
        sr["missing_counts"] = {k: v for k, v in mv.items() if v > 0}
        sr["missing_total_pct"] = round(float(df.isna().sum().sum()) / (df.shape[0] * df.shape[1]) * 100, 4)

        # numeric describe for numeric columns
        num = df.select_dtypes(include="number").drop(columns=[c for c in df.select_dtypes(include="number").columns if str(c).startswith("_")], errors="ignore")
        desc = {}
        for c in num.columns:
            s = num[c]
            desc[str(c)] = {
                "count": int(s.count()),
                "mean": round(float(s.mean()), 4) if s.count() else None,
                "std": round(float(s.std(ddof=0)), 4) if s.count() > 1 else None,
                "min": round(float(s.min()), 4) if s.count() else None,
                "p1": round(float(s.quantile(0.01)), 4) if s.count() else None,
                "p25": round(float(s.quantile(0.25)), 4) if s.count() else None,
                "p50": round(float(s.median()), 4) if s.count() else None,
                "p75": round(float(s.quantile(0.75)), 4) if s.count() else None,
                "p99": round(float(s.quantile(0.99)), 4) if s.count() else None,
                "max": round(float(s.max()), 4) if s.count() else None,
                "n_zero": int((s == 0).sum()),
                "n_neg": int((s < 0).sum()),
            }
        sr["numeric_summary"] = desc
        sheet_reports[sh] = sr
    xl.close()
    report["sheets_detail"] = sheet_reports
    return report


if __name__ == "__main__":
    for f in sorted(DATA_DIR.glob("*.xlsx")):
        print(f"\n\n########## {f.name} ##########", flush=True)
        rep = analyze_workbook(f)
        with open(OUT_DIR / f"{f.stem}_qa.json", "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
        # compact console echo
        d = rep["sheets_detail"]
        for sh, sr in d.items():
            ncol = sr["n_cols"]
            print(f"[{sh}] rows={sr['n_rows']} cols={ncol}")
            print(f"    span {sr['date_min']} -> {sr['date_max']} | bad_keys={sr['n_bad_date_or_hr']} dup_keys={sr['n_duplicate_keys']} fullrow_dups={sr['n_fullrow_duplicates']}")
            print(f"    expected_hours={sr['expected_hours']} missing={len(sr['missing_hour_slots'])} extra={len(sr['extra_slots_outside_expected'])} days_ne24={sr['days_with_rows_ne_24']}")
            if sr["missing_counts"]:
                print(f"    missing cols: {sr['missing_counts']}")
            if sr["numeric_summary"]:
                # only compact line for the 2 demand cols
                for k in ("DA_Demand", "RT_Demand", "SystemLoad"):
                    if k in sr["numeric_summary"]:
                        ss = sr["numeric_summary"][k]
                        print(f"    {k}: min={ss['min']} p1={ss['p1']} med={ss['p50']} p99={ss['p99']} max={ss['max']} zero={ss['n_zero']} neg={ss['n_neg']}")
        print(f"  -> saved {OUT_DIR / (f.stem + '_qa.json')}")
