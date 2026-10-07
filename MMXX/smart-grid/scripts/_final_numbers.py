import json
import numpy as np
import pandas as pd

ROOT = "/home/wy/ai-projects/smart-grid"
df = pd.read_parquet(f"{ROOT}/data/processed/ca_features.parquet")
for part in ("val", "test"):
    m = df["split"] == part
    da = np.mean(np.abs(df.loc[m, "DA_Demand"] - df.loc[m, "RT_Demand"]))
    naive24 = np.mean(np.abs(df.loc[m, "RT_Demand"].values[24:] - df.loc[m, "RT_Demand"].values[:-24]))
    print(part, "rows", int(m.sum()), "DA_MAE", round(float(da), 1))
metrics = json.load(open(f"{ROOT}/runs/tf_v2/metrics.json"))
print("epochs", metrics["epochs_done"], "minutes", metrics["minutes"])
for k in ("val", "test"):
    v = metrics[k]
    print(k, "load", v["load_MAE_MW"], v["load_RMSE_MW"], v["load_MAPE_pct"], v["load_R2"],
          "| price", v["price_p50_MAE_usd"], v["price_p50_RMSE_usd"], "cov", v["price_p10p90_coverage"])
cal = json.load(open(f"{ROOT}/runs/tf_v2/calibration.json"))
print("calib test cov", cal["test_calibrated"]["p10p90_coverage"], "p10below", cal["test_calibrated"]["p10_below"])
