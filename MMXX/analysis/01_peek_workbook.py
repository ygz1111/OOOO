# -*- coding: utf-8 -*-
"""Step 1 - structural peek of the SMD xlsx workbooks (read-only)."""
import sys
import os
from pathlib import Path

DATA_DIR = Path(r"C:\MMXX\datas")

def peek(path: Path):
    print("=" * 100)
    print(f"FILE: {path.name}  ({path.stat().st_size/1e6:.2f} MB)")
    print("=" * 100)
    # Use pandas for a fast structural read
    import pandas as pd
    xl = pd.ExcelFile(path)
    for sh in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=sh, header=None, nrows=8)
        print(f"\n[sheet] {sh!r}  shape(head sample)={df.shape}")
        # print header guess + first rows compactly
        for i, row in df.iterrows():
            vals = [("" if (isinstance(v, float) and pd.isna(v)) else str(v)) for v in row.tolist()]
            print(f"  row{i}: " + " | ".join(vals[:12]))
    xl.close()

if __name__ == "__main__":
    files = sorted(DATA_DIR.glob("*.xlsx"))
    print(f"found {len(files)} xlsx files under {DATA_DIR}")
    for f in files:
        peek(f)
