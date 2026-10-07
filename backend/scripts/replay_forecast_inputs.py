"""Replay archived feature rows with the original production assets, offline.

No network requests, database writes, training or model exports are performed.
Example: python backend/scripts/replay_forecast_inputs.py --archive-id <64 hex>
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND.parent / ".env")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("输出文件已存在，请指定新文件以保留已有结果")

    from realtime_api.services.container import services, init_services, release_services
    from realtime_api.services.forecast_archive import read_forecast_inputs
    from realtime_api.services.forecast_cache import model_signature

    read_forecast_inputs(args.archive_id)  # Reject invalid ID/integrity before loading.
    init_services()
    report = {"archive_id": args.archive_id, "scope": "exact_issued_feature_replay",
              "uses_later_weather": False, "components": {}}
    try:
        payload = read_forecast_inputs(args.archive_id, model_signature())
        for task, entry in payload["components"].items():
            if task == "pv":
                replay = services.tf_pv_service.predict_features(entry["past"], entry["future"])
                expected = entry["prediction"]["hourly_pv_mw"]
                actual = replay["hourly_pv_mw"]
            else:
                if not hasattr(services.tf_load_price_service, "predict_task_features"):
                    raise ValueError("留档重放要求当前生产独立负荷/电价服务")
                replay = services.tf_load_price_service.predict_task_features(task, entry["past"], entry["future"])
                fields = ["load_forecast_mw"] if task == "load" else ["price_p10", "price_p50", "price_p90"]
                expected = [[row[field] for field in fields] for row in entry["prediction"]["hourly"]]
                actual = [[row[field] for field in fields] for row in replay["hourly"]]
            expected, actual = np.asarray(expected), np.asarray(actual)
            if expected.shape != actual.shape:
                raise ValueError(f"{task} 重放输出形状与原预测不同")
            difference = float(np.max(np.abs(actual - expected)))
            report["components"][task] = {"generated_at": entry["generated_at"],
                "origin_hour": entry["origin_hour"], "input_status": entry["input_status"],
                "shape": list(actual.shape), "max_absolute_difference": difference,
                "matched": bool(np.allclose(actual, expected, rtol=0, atol=0.001))}
        report["all_matched"] = all(row["matched"] for row in report["components"].values())
        content = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(content + "\n")
        print(content)
        return 0 if report["all_matched"] else 1
    finally:
        release_services()


if __name__ == "__main__":
    raise SystemExit(main())
