"""Immutable inputs for reproducing an issued forecast without later weather.

The ordinary weather endpoint does not expose a model run/issuance timestamp.
Capture the inputs actually used; never invent a weather run from retrieval time.
This archive is independent of the six-hour restart cache and is not a label store.
"""
from datetime import date, datetime
import gzip
import hashlib
import json
import logging
from pathlib import Path
import re
import time
import uuid

import numpy as np
import pandas as pd

from realtime_api.services.forecast_cache import model_signature

logger = logging.getLogger(__name__)
ARCHIVE_DIR = Path(__file__).resolve().parents[2] / "cache" / "forecast_inputs"


def _serializable(value):
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _serializable(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save_forecast_inputs(task_inputs, weather):
    """Return a content ID, or an explicit failed status; never reissue a cache.

Each input entry includes the exact past/future feature rows, output, generation
time, model origin and input quality. Retries for identical content are idempotent.
All three tasks share one compressed copy of the retrieved weather.
"""
    if not task_inputs:
        return {"status": "not_created"}
    started = time.perf_counter()
    temporary = None
    try:
        provenance = dict(weather.attrs.get("forecast_provenance", {}))
        provenance.setdefault("source", "open_meteo_forecast")
        provenance.setdefault("model_run", None)
        provenance.setdefault("run_status", "not_exposed_by_endpoint")
        payload = _serializable({
            "version": 1,
            "timezone": "America/New_York",
            "model_signature": model_signature(),
            "weather": {"provenance": provenance, "columns": list(weather.columns),
                        "records": weather.to_dict("records")},
            "components": task_inputs,
        })
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
        archive_id = hashlib.sha256(content).hexdigest()
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        destination = ARCHIVE_DIR / f"{archive_id}.json.gz"
        if destination.exists():
            read_forecast_inputs(archive_id, payload["model_signature"])
        else:
            temporary = ARCHIVE_DIR / f".{uuid.uuid4().hex}.tmp"
            temporary.write_bytes(gzip.compress(content, compresslevel=3, mtime=0))
            temporary.replace(destination)
        return {"status": "saved", "archive_id": archive_id,
                "weather_run_status": provenance["run_status"],
                "save_time_ms": round((time.perf_counter() - started) * 1000, 2),
                "compressed_bytes": destination.stat().st_size}
    except Exception as exc:
        logger.warning("预测输入留档失败，本次无法进行输入重放: %s", exc)
        return {"status": "failed", "reason": "预测输入留档失败，本次无法进行输入重放"}
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_forecast_inputs(archive_id, expected_signature=None):
    """Load a verified input snapshot. Caller must match assets before replay."""
    if not isinstance(archive_id, str) or not re.fullmatch(r"[0-9a-f]{64}", archive_id):
        raise ValueError("无效的预测输入留档编号")
    content = gzip.decompress((ARCHIVE_DIR / f"{archive_id}.json.gz").read_bytes())
    if hashlib.sha256(content).hexdigest() != archive_id:
        raise ValueError("预测输入留档校验失败")
    payload = json.loads(content)
    if payload.get("version") != 1:
        raise ValueError("预测输入留档版本不支持")
    if expected_signature is not None and payload.get("model_signature") != expected_signature:
        raise ValueError("模型资产已改变，不能声称使用原模型重放")
    return payload
