import numpy as np
import pandas as pd
df = pd.read_parquet("/home/wy/ai-projects/smart-grid/data/processed/pv_features.parquet").sort_values("ts_start").reset_index(drop=True)
print("len", len(df), "cols", list(df.columns)[:8])
print("split values:", df["split"].value_counts().to_dict())
split = df["split"].values
n = len(df)
idx = np.arange(96, n - 24)
print("cand", len(idx))
m1 = split[idx] == "test"
m2 = split[idx + 23] == "test"
print("m1 sum", int(m1.sum()), "m2 sum", int(m2.sum()), "both", int((m1 & m2).sum()))
print("split dtype", df["split"].dtype)
