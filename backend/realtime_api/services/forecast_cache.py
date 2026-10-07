"""Versioned local restart cache; never changes forecast generation/target times."""
import hashlib
import json
import logging
from pathlib import Path

import pandas as pd

from realtime_api.services.container import services, get_engine_config

logger = logging.getLogger(__name__)
CACHE_PATH = Path(__file__).resolve().parents[2] / "cache" / "live_forecast.json"


def model_signature():
    assets = []
    for service in (services.tf_load_price_service, services.tf_pv_service):
        directory = Path(service.assets_dir).resolve()
        for path in sorted(directory.iterdir()):
            if path.suffix in (".h5", ".json"):
                stat = path.stat()
                assets.append((str(path), stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(json.dumps([get_engine_config(), assets], sort_keys=True).encode()).hexdigest()


def age_hours(generated_at, now):
    # Naive storage uses ET. Reject nonexistent/ambiguous DST hours rather than
    # guessing which repeated hour it represents, and measure age in real hours.
    def aware(value):
        stamp = pd.Timestamp(value)
        return stamp.tz_localize("America/New_York") if stamp.tzinfo is None else stamp.tz_convert("America/New_York")
    return (aware(now) - aware(generated_at)).total_seconds() / 3600


def save_previous(previous):
    if not previous:
        return
    try:
        payload = {"version": 1, "signature": model_signature(), "components": {
            task: {"result": result, "quality": quality, "origin_hour": str(origin)}
            for task, (result, quality, origin) in previous.items()}}
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CACHE_PATH.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(CACHE_PATH)
    except Exception as exc:
        logger.warning("本地预测缓存保存失败: %s", exc)


def read_previous(now, validate):
    if not CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if payload["version"] != 1 or payload["signature"] != model_signature():
            logger.info("本地预测缓存契约或模型资产已变更，跳过恢复")
            return {}
        restored = {}
        for task in ("load", "price", "pv"):
            entry = payload["components"].get(task)
            if not entry:
                continue
            try:
                result, quality = entry["result"], entry["quality"]
                if not 0 <= age_hours(result["generated_at"], now) <= 6:
                    continue
                if not result["data_source"].startswith("iso_ne+open_meteo:zonal_he_v2"):
                    raise ValueError("缓存来源不符合在线契约")
                origin = pd.Timestamp(entry["origin_hour"])
                if origin != pd.Timestamp(result["generated_at"]).floor("h"):
                    raise ValueError("缓存生成小时不一致")
                validate(result, task, origin)
                targets = pd.DatetimeIndex(result["timestamps"])
                # Legacy naive keys cannot express DST repeated/missing hours.
                # A restart must not revive an ambiguous interval.
                targets.tz_localize("America/New_York")
                boundaries = targets + pd.Timedelta(hours=1 if task == "pv" else -1)
                boundaries.tz_localize("America/New_York")
                if quality["generated_at"] != result["generated_at"]:
                    raise ValueError("缓存生成时间不一致")
                restored[task] = (result, quality, origin)
            except Exception as exc:
                logger.warning("忽略无效 %s 预测缓存: %s", task, exc)
        return restored
    except Exception as exc:
        logger.warning("本地预测缓存恢复失败: %s", exc)
        return {}
