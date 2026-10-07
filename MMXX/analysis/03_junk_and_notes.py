# -*- coding: utf-8 -*-
"""Step 3 - locate junk rows (bad Date/Hr_End) and dump column lists + Notes dict."""
import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(r"C:\MMXX\datas")
OUT_DIR = Path(r"C:\MMXX\analysis\out")

for f in sorted(DATA_DIR.glob("*.xlsx")):
    print("=" * 90)
    print(f, flush=True)
    xl = pd.ExcelFile(f)
    for sh in xl.sheet_names:
        if sh == "Notes":
            continue
        df = pd.read_excel(f, sheet_name=sh)
        date = pd.to_datetime(df["Date"], errors="coerce")
        hr = pd.to_numeric(df.get("Hr_End"), errors="coerce")
        bad = date.isna() | hr.isna()
        if bad.any():
            print(f"\n[{sh}] {int(bad.sum())} bad rows:")
            for i in df.index[bad]:
                row = [str(v)[:24] for v in df.loc[i].tolist()]
                print("   row", int(i) + 2, ":", " | ".join(row[:14]))
    xl.close()

# Notes full text from 2024 (dictionary)
print("\n\n===== NOTES DICTIONARY (2024 file, all rows) =====")
notes = pd.read_excel(DATA_DIR / "2024_smd_hourly.xlsx", sheet_name="Notes", header=None)
for i, r in notes.iterrows():
    vals = ["" if (isinstance(v, float) and pd.isna(v)) else str(v).strip() for v in r.tolist()]
    joined = " | ".join(v for v in vals if v)
    if joined:
        print(f"{int(i)+1:>3}: {joined}")
