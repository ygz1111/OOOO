# -*- coding: utf-8 -*-
"""TensorFlow 生产推理特征提供器。

从 ISO-NE Web Services 读取负荷、日前需求、电价和 BTM 光伏实况，
从 Open-Meteo 客户端读取历史/预报天气，严格按训练脚本的时间语义和
特征公式组装独立负荷/电价模型与 pv_v2 的输入。此模块不包含任何模型训练逻辑。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from collections import OrderedDict
from datetime import date, timedelta
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from realtime_api.pv_capacity import btm_pv_capacity_array
from realtime_api.utils.iso_ne import ISO_NE_BASE, get_credentials
from realtime_api.utils.iso_ne_intervals import zonal_hourly

logger = logging.getLogger(__name__)

SYSTEM_LOCATION_ID = 32
HUB_LOCATION_ID = 4000
ZONE_IDS = tuple(range(4001, 4009))
MIN_FIVE_MINUTE_LMP_SAMPLES = 8
# ISO-NE 偶尔会在已经结束的小时缺少少量五分钟分区记录。只要八个分区
# 每区都有至少 2/3（8/12）有效采样，就保留该小时；这与 RT-LMP 的
# 官方五分钟回退阈值一致，并避免一个孤立缺口让 336h 特征窗口倒退数天。
MIN_FIVE_MINUTE_PV_SAMPLES = 8
MAX_LIVE_ORIGIN_LAG_HOURS = 2
PV_CAPACITY_FALLBACK_MW = 5145.798
REGIONAL_LAT = 42.42125
REGIONAL_LON = -71.6575

# 必须与 models.tensorflow_load.tf_split_models 的训练输入顺序一致。
LOAD_PAST_COLS = [
    "RT_Demand", "DA_Demand", "RT_LMP", "DA_LMP", "Dry_Bulb", "Dew_Point",
    "hdd65", "cdd65", "temp_mem", "clock_hour_sin", "clock_hour_cos",
    "dow_sin", "dow_cos", "month_sin", "month_cos", "is_holiday", "is_dst",
    "rt_lag24", "rt_lag168", "rt_prev24_mean", "rt_prev168_mean",
    "rtlmp_lag1", "rtlmp_lag24", "rtlmp_lag168", "rtlmp_prev24_mean", "da_lmp_lag24",
]
LOAD_FUTURE_COLS = [
    "DA_Demand", "DA_LMP", "Dry_Bulb", "Dew_Point", "hdd65", "cdd65",
    "temp_mem", "clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos",
    "month_sin", "month_cos", "is_holiday", "holiday_shoulder", "is_dst", "rt_yest",
]
PV_ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]
PV_WEATHER_COLS = (
    [f"ghi_{zone}" for zone in PV_ZONES]
    + [f"cloud_{zone}" for zone in PV_ZONES]
    + ["temp_mean", "dew_mean"]
)
PV_COMMON_COLS = PV_WEATHER_COLS + [
    "coszen", "sun_up", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "doy_sin", "doy_cos", "trend_days",
]
PV_PAST_COLS = PV_COMMON_COLS + ["pv_mw_ISONE"]
PV_FUTURE_COLS = PV_COMMON_COLS
PV_TREND_START = pd.Timestamp("2025-02-01 00:00")


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def _holiday_days(years: Iterable[int]) -> set[date]:
    result: set[date] = set()
    for year in years:
        values = (
            date(year, 1, 1), _nth_weekday(year, 1, 0, 3),
            _nth_weekday(year, 2, 0, 3), _last_weekday(year, 5, 0),
            date(year, 6, 19), date(year, 7, 4),
            _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 10, 0, 2),
            date(year, 11, 11), _nth_weekday(year, 11, 3, 4),
            date(year, 12, 25),
        )
        result.update(_observed(value) for value in values)
    return result


def _is_dst_day(value: date) -> bool:
    return _nth_weekday(value.year, 3, 6, 2) <= value < _nth_weekday(value.year, 11, 6, 1)


def _solar_coszen(index: pd.DatetimeIndex) -> np.ndarray:
    """计算 ISO-NE 区域每个本地小时的太阳天顶角余弦。

    ``index`` 使用 America/New_York 的本地墙钟时间。计算时先扣除夏令时，
    再使用东部标准时区中央经线 -75° 与区域经度的差值，并加入 NOAA 的
    equation-of-time 修正。旧实现把中央经线写成了 +75°，导致昼夜相位偏移。
    """
    local = index.tz_localize(None)
    jday = local.dayofyear.to_numpy(dtype=float)
    hour = local.hour.to_numpy(dtype=float) + local.minute.to_numpy(dtype=float) / 60.0
    gamma = 2 * np.pi * (jday - 1 + (hour - 12) / 24.0) / 365.0
    decl = (0.006918 - 0.399912 * np.cos(gamma) + 0.070257 * np.sin(gamma)
            - 0.006758 * np.cos(2 * gamma) + 0.000907 * np.sin(2 * gamma)
            - 0.002697 * np.cos(3 * gamma) + 0.00148 * np.sin(3 * gamma))
    equation_of_time = 229.18 * (
        0.000075 + 0.001868 * np.cos(gamma) - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma) - 0.040849 * np.sin(2 * gamma)
    )
    dst_hours = np.fromiter(
        (1.0 if _is_dst_day(value) else 0.0 for value in local.date),
        dtype=float,
        count=len(local),
    )
    standard_minutes = (hour - dst_hours) * 60.0
    true_solar_minutes = (
        standard_minutes + equation_of_time
        + 4.0 * (REGIONAL_LON - (-75.0))
    )
    hra = np.radians(true_solar_minutes / 4.0 - 180.0)
    lat_r = np.radians(REGIONAL_LAT)
    return np.clip(
        np.sin(lat_r) * np.sin(decl) + np.cos(lat_r) * np.cos(decl) * np.cos(hra),
        0.0, None,
    )


def _records(payload: dict, item_key: str) -> list[dict]:
    """递归寻找 ISO-NE 的记录节点，兼容 PascalCase 与 snake_case 包装。"""
    wanted = item_key.lower()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() == wanted:
                if isinstance(value, list):
                    return value
                return [value] if isinstance(value, dict) else []
        for value in payload.values():
            found = _records(value, item_key)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _records(value, item_key)
            if found:
                return found
    return []


def _timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("America/New_York").tz_localize(None)
    return ts


class TFRealtimeFeatureProvider:
    """组装两个 TensorFlow 模型的严格在线输入。

    特征保留五分钟，天气变化或跨小时时重新组装。按日期缓存原始市场数据，
    近期日期每五分钟更新，较早历史每六小时校正，避免重复下载整个历史窗口。
    """

    def __init__(self, cache_ttl: int = 300, timeout: int = 30):
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._cached: dict | None = None
        self._cached_hour = None
        self._cached_weather = None
        self._day_cache = OrderedDict()
        self._day_inflight: dict[tuple, Future] = {}
        self._day_lock = threading.Lock()
        self._session = requests.Session()
        retry = Retry(
            total=3, connect=3, read=3, backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(("GET",)),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=4))

    @staticmethod
    def _current_eastern_hour() -> pd.Timestamp:
        return pd.Timestamp.now(tz="America/New_York").tz_localize(None).floor("h")

    def _get(self, path: str) -> dict:
        username, password = get_credentials()
        if not username:
            raise RuntimeError("TF live 模式需要 ISO_NE_USERNAME 和 ISO_NE_PASSWORD")
        response = self._session.get(
            f"{ISO_NE_BASE}/{path}", auth=(username, password), timeout=self.timeout,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()

    def _fetch_day(self, kind: str, day: date) -> tuple[str, date, list[dict]]:
        stamp = day.strftime("%Y%m%d")
        if kind == "load":
            data = self._get(f"hourlysysload/day/{stamp}")
            rows = _records(data, "HourlySystemLoad")
        elif kind == "da_demand":
            data = self._get(f"dayaheadhourlydemand/day/{stamp}/location/{SYSTEM_LOCATION_ID}")
            rows = _records(data, "HourlyDaDemand")
        elif kind == "da_lmp":
            data = self._get(f"hourlylmp/da/final/day/{stamp}/location/{HUB_LOCATION_ID}")
            rows = _records(data, "HourlyLmp")
        elif kind == "rt_lmp":
            used_final = False
            try:
                data = self._get(f"hourlylmp/rt/prelim/day/{stamp}/location/{HUB_LOCATION_ID}")
            except requests.HTTPError:
                data = self._get(f"hourlylmp/rt/final/day/{stamp}/location/{HUB_LOCATION_ID}")
                used_final = True
            rows = _records(data, "HourlyLmp")
            # 旧日期的 preliminary 端点也可能返回 200 + 空列表；此时仍需
            # 尝试正式历史记录，不能把它误判为该天没有真实电价。
            if not rows and not used_final:
                data = self._get(f"hourlylmp/rt/final/day/{stamp}/location/{HUB_LOCATION_ID}")
                rows = _records(data, "HourlyLmp")
                used_final = True
            rows = [{**row, "_rt_lmp_source": "iso_ne_hourly_final" if used_final else "iso_ne_hourly_preliminary"}
                    for row in rows]
        elif kind == "rt_lmp_5min":
            try:
                data = self._get(f"fiveminutelmp/prelim/day/{stamp}/location/{HUB_LOCATION_ID}")
            except requests.HTTPError:
                data = self._get(f"fiveminutelmp/day/{stamp}/location/{HUB_LOCATION_ID}")
            rows = _records(data, "FiveMinLmp")
        elif kind == "pv":
            data = self._get(f"fiveminuteestimatedzonalload/day/{stamp}")
            rows = _records(data, "five_min_estimated_zonal_load")
        else:
            raise ValueError(kind)
        return kind, day, rows

    def _fetch_day_cached(self, kind: str, day: date) -> tuple[str, date, list[dict]]:
        """有界原始数据缓存；并发请求同一日期只访问一次官方接口。

        空响应和失败不缓存，下一轮仍可取得官方补发的数据。返回记录只读，
        缓存不包含任何插补值。历史修订最多延迟六小时被重新获取。
        """
        key = (kind, day)
        current_hour = self._current_eastern_hour()
        recent = day >= current_hour.date() - timedelta(days=1)
        ttl = min(self.cache_ttl, 300) if recent else 6 * 3600
        with self._day_lock:
            cached = self._day_cache.get(key)
            if (cached and time.monotonic() - cached[0] < ttl
                    and (not recent or cached[2] == current_hour)):
                self._day_cache.move_to_end(key)
                return kind, day, cached[1]
            pending = self._day_inflight.get(key)
            owner = pending is None
            if owner:
                pending = Future()
                self._day_inflight[key] = pending
        if not owner:
            return pending.result()
        try:
            result = self._fetch_day(kind, day)
            if result[2]:
                with self._day_lock:
                    self._day_cache[key] = (time.monotonic(), result[2], current_hour)
                    self._day_cache.move_to_end(key)
                    while len(self._day_cache) > 192:
                        self._day_cache.popitem(last=False)
            pending.set_result(result)
            return result
        except Exception as exc:
            pending.set_exception(exc)
            raise
        finally:
            with self._day_lock:
                self._day_inflight.pop(key, None)

    def _market_frames(self, today: date) -> dict[str, pd.DataFrame]:
        """构建在线预测所需的近期 ISO-NE 市场帧。"""
        return self._market_frames_for_range(
            # 新独立模型的 168h 历史窗口还包含 rt_lag168 / rolling-168，
            # 在线窗口336h，加24h历史回测，16天足够；不再为回退旧锚点多抓5天。
            actual_start=today - timedelta(days=16),
            actual_end=today,
            da_end=today + timedelta(days=1),
        )

    def _fill_rt_lmp_gaps_from_five_minute(
        self,
        frame: pd.DataFrame,
    ) -> pd.DataFrame:
        """用 ISO-NE 官方五分钟 RT-LMP 聚合值补齐小时接口的内部缺口。

        ISO-NE 的小时 preliminary 接口会在个别五分钟间隔尚未回填时省略
        整个小时。五分钟接口通常仍保留该小时的大部分记录。这里只补充小时
        序列首尾之间的缺失点，不外推当前尚未结束的小时，也不覆盖已经发布
        的小时值。每小时至少需要 8 个五分钟点（2/3 覆盖率）；不足时继续
        保持缺失并由上层选择更早的完整预测锚点。
        """
        if frame.empty:
            return frame

        result = frame.copy().sort_index()
        if "rt_lmp_source" not in result:
            result["rt_lmp_source"] = "iso_ne_hourly"
        valid = (result["rt_lmp_source"].isin(["iso_ne_hourly", "iso_ne_hourly_preliminary", "iso_ne_hourly_final"])
                 & np.isfinite(pd.to_numeric(result["rt_lmp"], errors="coerce")))
        if "rt_lmp_label_valid" in result:
            valid &= result["rt_lmp_label_valid"].fillna(False).astype(bool)
        result["rt_lmp_label_valid"] = valid
        if "rt_lmp_samples" not in result:
            result["rt_lmp_samples"] = np.nan
        expected = pd.date_range(result.index.min(), result.index.max(), freq="h")
        missing = expected.difference(pd.DatetimeIndex(result.index))
        if missing.empty:
            return result

        source_days = sorted({
            (pd.Timestamp(hour_end) - pd.Timedelta(hours=1)).date()
            for hour_end in missing
        })
        collected: list[dict] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=min(4, len(source_days))) as pool:
            futures = [
                pool.submit(self._fetch_day_cached, "rt_lmp_5min", day)
                for day in source_days
            ]
            for future in as_completed(futures):
                try:
                    _, _, rows = future.result()
                    collected.extend(rows)
                except Exception as exc:
                    errors.append(str(exc))

        if errors:
            logger.warning(
                "ISO-NE 五分钟 RT-LMP 回退请求部分失败 (%s/%s): %s",
                len(errors), len(source_days), errors[0],
            )

        values = []
        safe_hours = {}
        cutoff = self._current_eastern_hour()
        for item in collected:
            try:
                location = item.get("Location", {})
                loc_id = location.get("@LocId") if isinstance(location, dict) else None
                if loc_id is not None and int(loc_id) != HUB_LOCATION_ID:
                    continue
                sample = _timestamp(item.get("BeginDate"))
                if pd.isna(sample) or sample.minute % 5 or sample.second or sample.microsecond or sample.nanosecond:
                    continue
                start = sample.floor("h")
                hour_end = start + pd.Timedelta(hours=1)
                if hour_end > cutoff:
                    continue
                if start not in safe_hours:
                    edges = pd.DatetimeIndex([start, hour_end]).tz_localize(
                        "America/New_York", ambiguous="NaT", nonexistent="NaT")
                    safe_hours[start] = not edges.isna().any()
                if not safe_hours[start]:
                    continue
                value = float(item.get("LmpTotal"))
                # Negative electricity prices are valid; non-finite values are not.
                values.append((sample, hour_end, value if np.isfinite(value) else np.nan))
            except (TypeError, ValueError, OverflowError):
                continue

        if not values:
            logger.warning(
                "ISO-NE 小时 RT-LMP 缺失 %s 个小时，五分钟接口没有可用回退数据",
                len(missing),
            )
            return result

        five_minute = pd.DataFrame(values, columns=["sample", "ts_local", "rt_lmp"]).drop_duplicates("sample", keep="last")
        aggregated = five_minute.groupby("ts_local")["rt_lmp"].agg(["mean", "count"])
        filled = []
        rejected = []
        for hour_end in missing:
            if hour_end not in aggregated.index:
                rejected.append((hour_end, 0))
                continue
            samples = int(aggregated.loc[hour_end, "count"])
            if samples < MIN_FIVE_MINUTE_LMP_SAMPLES:
                rejected.append((hour_end, samples))
                continue
            result.loc[hour_end, "rt_lmp"] = float(aggregated.loc[hour_end, "mean"])
            result.loc[hour_end, "rt_lmp_source"] = "iso_ne_five_minute_aggregate"
            result.loc[hour_end, "rt_lmp_samples"] = samples
            result.loc[hour_end, "rt_lmp_label_valid"] = False
            filled.append((hour_end, samples))

        if filled:
            logger.warning(
                "使用 ISO-NE 官方五分钟 RT-LMP 补齐 %s/%s 个小时: %s",
                len(filled), len(missing),
                [f"{hour}({samples}/12)" for hour, samples in filled],
            )
        if rejected:
            logger.warning(
                "ISO-NE RT-LMP 仍有 %s 个小时无法可靠补齐: %s",
                len(rejected),
                [f"{hour}({samples}/12)" for hour, samples in rejected[:8]],
            )
        return result.sort_index()

    def _market_frames_for_range(
        self,
        actual_start: date,
        actual_end: date,
        da_end: date,
    ) -> dict[str, pd.DataFrame]:
        """读取指定历史窗口的 ISO-NE 特征源。

        ``actual_*`` 只用于 RT 负荷、RT LMP 与 BTM 光伏等已经发生的特征；
        ``da_end`` 允许日前需求/日前电价多读取一天，以满足每个 24 步模型窗口
        所需的已发布日前曲线。在线预测与按日回测共用该实现，避免两套特征口径。
        """
        if actual_start > actual_end or da_end < actual_end:
            raise ValueError("ISO-NE 特征日期范围无效")
        history_days = [
            actual_start + timedelta(days=offset)
            for offset in range((actual_end - actual_start).days + 1)
        ]
        da_days = [
            actual_start + timedelta(days=offset)
            for offset in range((da_end - actual_start).days + 1)
        ]
        jobs = []
        for kind in ("rt_lmp", "pv"):
            jobs.extend((kind, day) for day in history_days)
        for kind in ("da_demand", "da_lmp"):
            jobs.extend((kind, day) for day in da_days)

        collected: dict[str, list[dict]] = {name: [] for name in
                                            ("da_demand", "rt_lmp", "da_lmp", "pv")}
        errors = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self._fetch_day_cached, kind, day) for kind, day in jobs]
            for future in as_completed(futures):
                try:
                    kind, _, rows = future.result()
                    collected[kind].extend(rows)
                except Exception as exc:  # individual empty future dates are diagnosed below
                    errors.append(str(exc))
        if errors:
            logger.warning("ISO-NE 部分日期请求失败 (%s/%s): %s", len(errors), len(jobs), errors[0])

        def hourly(name: str, value_key: str) -> pd.DataFrame:
            rows = []
            rejected = 0
            for item in collected[name]:
                try:
                    if not isinstance(item, dict):
                        rejected += 1
                        continue
                    location = item.get("Location", {})
                    loc_id = location.get("@LocId") if isinstance(location, dict) else None
                    expected_location = SYSTEM_LOCATION_ID if name == "da_demand" else HUB_LOCATION_ID
                    # ISO BeginDate 是 interval-start；模型的 ts_local 是 hour-ending。
                    start, value = _timestamp(item.get("BeginDate")), float(item.get(value_key))
                    if (loc_id is not None and int(loc_id) != expected_location
                            or pd.isna(start) or start != start.floor("h") or not np.isfinite(value)):
                        rejected += 1
                        continue
                    edges = pd.DatetimeIndex([start, start + pd.Timedelta(hours=1)]).tz_localize(
                        "America/New_York", ambiguous="NaT", nonexistent="NaT")
                    if edges.isna().any():
                        rejected += 1
                        continue
                    row = (start + pd.Timedelta(hours=1), value)
                    if name == "rt_lmp":
                        row += (item.get("_rt_lmp_source", "iso_ne_hourly"),)
                    rows.append(row)
                except (TypeError, ValueError, OverflowError):
                    # A bad DA record must not discard independent PV observations.
                    # Gaps remain missing and are rejected by the strict feature window.
                    rejected += 1
            if rejected:
                logger.warning("ISO-NE 小时 %s 排除 %s 条无效/位置不符/非整点/夏令时歧义记录", name, rejected)
            if not rows:
                # 即使上游完全不可用，也保持时间序列索引契约。此前这里返回
                # RangeIndex，后续 hour-start/hour-end 对齐时给索引加 Timedelta
                # 会抛出 NumPy 类型异常，掩盖真正的“ISO-NE 数据为空”原因。
                return pd.DataFrame(
                    index=pd.DatetimeIndex([], name="ts_local"),
                    columns=[name],
                    dtype=float,
                )
            if name == "rt_lmp":
                frame = pd.DataFrame(rows, columns=["ts_local", name, "rt_lmp_source"]).drop_duplicates("ts_local", keep="last").set_index("ts_local")
            else:
                frame = pd.DataFrame(rows, columns=["ts_local", name]).groupby("ts_local").mean()
            return frame.sort_index()

        load, pv = zonal_hourly(collected["pv"], MIN_FIVE_MINUTE_PV_SAMPLES,
                                now=self._current_eastern_hour())

        rt_lmp = self._fill_rt_lmp_gaps_from_five_minute(
            hourly("rt_lmp", "LmpTotal")
        )

        return {
            "load": load,
            "da_demand": hourly("da_demand", "Load"),
            "rt_lmp": rt_lmp,
            "da_lmp": hourly("da_lmp", "LmpTotal"),
            "pv": pv.sort_index(),
        }

    @staticmethod
    def _weather(weather_df: pd.DataFrame) -> pd.DataFrame:
        required = {"timestamp", "temperature_2m", "dew_point_2m", "cloud_cover", "shortwave_radiation"}
        missing = sorted(required - set(weather_df.columns))
        if missing:
            raise ValueError(f"Open-Meteo 数据缺少在线模型所需字段: {missing}")
        frame = weather_df.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        numeric = [column for column in frame.columns if column != "timestamp" and column != "location"]
        frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
        result = frame.groupby("timestamp")[numeric].mean().sort_index()
        result = result[~result.index.duplicated(keep="last")]
        return result

    @staticmethod
    def _pv_weather(weather_df: pd.DataFrame) -> pd.DataFrame:
        """Preserve the spatial weather inputs required by pv_v2.

        The shared Open-Meteo client has six New England stations.  They map to
        the eight ISO-NE PV zones used in training; SEMA shares the Providence
        proxy and WCMA uses the Boston/Hartford mean.
        """
        required = {
            "timestamp", "location", "temperature_2m", "dew_point_2m",
            "cloud_cover", "shortwave_radiation",
        }
        missing = sorted(required - set(weather_df.columns))
        if missing:
            raise ValueError(f"Open-Meteo 数据缺少 pv_v2 所需字段: {missing}")
        frame = weather_df[list(required)].copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame["location"] = frame["location"].astype(str).str.casefold()
        numeric = ["temperature_2m", "dew_point_2m", "cloud_cover", "shortwave_radiation"]
        frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
        frame = frame.groupby(["timestamp", "location"], as_index=False)[numeric].mean()

        source = {
            "ME": ["portland"], "NH": ["manchester"], "VT": ["burlington"],
            "CT": ["hartford"], "RI": ["providence"], "SEMA": ["providence"],
            "WCMA": ["boston", "hartford"], "NEMA": ["boston"],
        }
        available = set(frame["location"])
        needed = set(name for names in source.values() for name in names)
        if not needed.issubset(available):
            raise ValueError(f"pv_v2 缺少气象站点: {sorted(needed - available)}")

        result = pd.DataFrame(index=pd.DatetimeIndex(sorted(frame["timestamp"].dropna().unique())))
        result.index.name = "timestamp"
        zone_temperature = []
        zone_dew = []
        for zone, names in source.items():
            selected = frame[frame["location"].isin(names)]
            hourly = selected.groupby("timestamp")[numeric].mean().reindex(result.index)
            result[f"ghi_{zone}"] = hourly["shortwave_radiation"]
            result[f"cloud_{zone}"] = hourly["cloud_cover"]
            result[f"temp_{zone}"] = hourly["temperature_2m"]
            result[f"dew_{zone}"] = hourly["dew_point_2m"]
            zone_temperature.append(f"temp_{zone}")
            zone_dew.append(f"dew_{zone}")
        result["temp_mean"] = result[zone_temperature].mean(axis=1)
        result["dew_mean"] = result[zone_dew].mean(axis=1)
        result = result.drop(columns=zone_temperature + zone_dew)
        return result.sort_index()

    @staticmethod
    def _calendar(frame: pd.DataFrame, timestamp_column: str, hour_column: str) -> None:
        ts = pd.DatetimeIndex(frame[timestamp_column])
        hours = frame[hour_column].to_numpy(dtype=float)
        dow = ts.dayofweek.to_numpy(dtype=float)
        frame[f"{hour_column}_sin"] = np.sin(2 * np.pi * hours / 24)
        frame[f"{hour_column}_cos"] = np.cos(2 * np.pi * hours / 24)
        frame["dow_sin"] = np.sin(2 * np.pi * dow / 7)
        frame["dow_cos"] = np.cos(2 * np.pi * dow / 7)

    @staticmethod
    def _require_contiguous(frame: pd.DataFrame, column: str, start: pd.Timestamp,
                            periods: int, label: str) -> pd.DataFrame:
        wanted = pd.date_range(start=start, periods=periods, freq="h")
        selected = frame.set_index(column).reindex(wanted)
        if selected.isna().any().any():
            missing_rows = selected.index[selected.isna().any(axis=1)]
            bad_columns = selected.columns[selected.isna().any()].tolist()
            raise ValueError(
                f"{label}不完整，异常字段={bad_columns}，"
                f"缺少/异常小时: {[str(x) for x in missing_rows[:5]]}"
            )
        selected.index.name = column
        return selected.reset_index()

    @staticmethod
    def _latest_contiguous_hour(indices: list[pd.DatetimeIndex], periods: int) -> pd.Timestamp:
        """Return the latest common hour whose preceding window has no gaps."""
        common = indices[0]
        for index in indices[1:]:
            common = common.intersection(index)
        common = pd.DatetimeIndex(common).sort_values()
        common_set = set(common)
        for candidate in reversed(common):
            start = candidate - pd.Timedelta(hours=periods - 1)
            if all(value in common_set for value in pd.date_range(start, candidate, freq="h")):
                return pd.Timestamp(candidate)
        raise ValueError(f"ISO-NE 最近数据不存在连续 {periods} 小时的共同窗口")

    @staticmethod
    def _fill_future_day_ahead(
        frames: dict[str, pd.DataFrame],
        origin_end: pd.Timestamp,
        periods: int = 24,
    ) -> tuple[dict[str, pd.DataFrame], list[dict]]:
        """补齐尚未发布的未来日前特征，并保留完整来源记录。

        ISO-NE 在清晨通常还没有发布下一交易日的完整 DA_Demand/DA_LMP，
        但滚动 24h 模型必须取得这些未来协变量。对未来窗口中确实尚未发布的
        小时，优先采用前一日同小时值，必要时再采用前一周同小时值；历史窗口
        和已经发布但异常的过去小时绝不在这里补值。
        """
        result = {name: frame.copy() for name, frame in frames.items()}
        wanted = pd.date_range(
            start=origin_end + pd.Timedelta(hours=1), periods=periods, freq="h"
        )
        imputed: list[dict] = []
        for name, column in (("da_demand", "da_demand"), ("da_lmp", "da_lmp")):
            frame = result[name].copy().sort_index()
            published = pd.to_numeric(frame[column], errors="coerce").dropna()
            last_published = published.index.max() if not published.empty else None
            for target in wanted:
                current = frame.loc[target, column] if target in frame.index else np.nan
                if np.isfinite(current):
                    continue
                if last_published is not None and target <= last_published:
                    raise ValueError(
                        f"{column} 已发布区间存在内部缺口，拒绝用持久性数据覆盖: {target}"
                    )
                source_time = None
                source_value = None
                for offset_hours in (24, 168):
                    candidate = target - pd.Timedelta(hours=offset_hours)
                    if candidate not in frame.index:
                        continue
                    candidate_value = frame.loc[candidate, column]
                    if np.isfinite(candidate_value):
                        source_time = candidate
                        source_value = float(candidate_value)
                        break
                if source_time is None:
                    raise ValueError(
                        f"{column} 未来特征缺失且无同小时历史值可回退: {target}"
                    )
                frame.loc[target, column] = source_value
                imputed.append({
                    "field": column,
                    "target_time": str(target),
                    "source_time": str(source_time),
                    "method": "same_hour_persistence",
                })
            result[name] = frame.sort_index()
        return result, imputed

    def _build_load_backtest_windows(
        self,
        market: pd.DataFrame,
        latest_origin_end: pd.Timestamp,
        hours: int = 24,
        skip_incomplete: bool = False,
        future_hours: int = 24,
    ) -> list[dict]:
        """构建过去 ``hours`` 个逐小时回测窗口。

        对目标小时 ``t``，输入窗口截止于 ``t-1``，模型第 0 步输出恰好对齐
        ``t``。未来输入只包含日前曲线、天气、日历和 t-24 的实际需求；没有把
        t 或之后的 RT_Demand/RT_LMP 输入模型。天气使用事后观测，因此该结果应
        标注为回溯验证，而非历史时刻可获得预报的严格在线精度。
        支持真实单步负荷推理时可令 future_hours=1，只要求目标小时协变量；
        默认24小时保留旧服务契约，不生成后续未发布的未来特征。
        """
        if future_hours not in (1, 24):
            raise ValueError("负荷回测未来特征必须为1或24小时")
        past_columns = LOAD_PAST_COLS if future_hours == 24 else LOAD_PAST_COLS[:LOAD_PAST_COLS.index("rtlmp_lag1")]
        windows: list[dict] = []
        targets = pd.date_range(
            latest_origin_end - pd.Timedelta(hours=hours - 1),
            latest_origin_end,
            freq="h",
        )
        for target_end in targets:
            try:
                if "minimum_samples" in market:
                    samples = market.loc[market["ts_local"] == target_end, "minimum_samples"]
                    if len(samples) != 1 or not samples.iloc[0] >= 12:
                        raise ValueError(f"TF负荷回测标签采样不完整: {target_end}")
                input_end = target_end - pd.Timedelta(hours=1)
                if future_hours == 1:
                    edges = pd.date_range(input_end - pd.Timedelta(hours=168), target_end, freq="h").tz_localize(
                        "America/New_York", ambiguous="NaT", nonexistent="NaT")
                    if edges.isna().any():
                        raise ValueError(f"TF负荷单步回测窗口跨越夏令时歧义或不存在的小时: {target_end}")
                past = self._require_contiguous(
                    market[["ts_local"] + past_columns], "ts_local",
                    input_end - pd.Timedelta(hours=167), 168,
                    f"TF负荷回测历史特征({target_end})",
                )
                future = self._require_contiguous(
                    market[["ts_local"] + LOAD_FUTURE_COLS], "ts_local",
                    target_end, future_hours,
                    f"TF负荷回测未来特征({target_end})",
                )
                actual = pd.to_numeric(
                    market.loc[market["ts_local"] == target_end, "RT_Demand"],
                    errors="coerce",
                )
                if len(actual) != 1 or not np.isfinite(actual.iloc[0]):
                    raise ValueError(f"TF负荷回测缺少真实负荷: {target_end}")
            except ValueError as exc:
                if not skip_incomplete:
                    raise
                # 在线总览的未来预测不应因一个历史回测小时缺失而整体 500。
                # 只跳过无法严格构造的回测点；主预测窗口仍由下方严格校验保护。
                logger.warning("跳过不完整的在线负荷回测点 %s: %s", target_end, exc)
                continue
            windows.append({
                "target_time": str(target_end),
                "actual_load_mw": round(float(actual.iloc[0]), 1),
                "past": past.to_dict("records"),
                "future": future.to_dict("records"),
            })
        return windows

    def _build_pv_backtest_windows(
        self,
        pv: pd.DataFrame,
        latest_target_start: pd.Timestamp,
        hours: int = 24,
    ) -> list[dict]:
        """构建过去 ``hours`` 个光伏逐小时回测窗口。

        对 hour-start 目标小时 ``t``，历史输入严格截止于 ``t-1h``，未来输入
        从 ``t`` 开始；调用方只取模型第 0 个输出与 ``t`` 时刻 ISO-NE 八个
        负荷区汇总的 estimated BTM PV 对齐。未来气象使用事后观测，因此这是
        回溯验证，不等同于历史时刻使用当时天气预报的严格在线精度。
        """
        windows: list[dict] = []
        targets = pd.date_range(
            latest_target_start - pd.Timedelta(hours=hours - 1),
            latest_target_start,
            freq="h",
        )
        for target_start in targets:
            if "minimum_samples" in pv:
                samples = pv.loc[pv["ts_start"] == target_start, "minimum_samples"]
                if len(samples) != 1 or not samples.iloc[0] >= 12:
                    continue
            past = self._require_contiguous(
                pv[["ts_start"] + PV_PAST_COLS], "ts_start",
                target_start - pd.Timedelta(hours=96), 96,
                f"TF光伏回测历史特征({target_start})",
            )
            future = self._require_contiguous(
                pv[["ts_start"] + PV_FUTURE_COLS], "ts_start",
                target_start, 24,
                f"TF光伏回测未来特征({target_start})",
            )
            actual = pd.to_numeric(
                pv.loc[pv["ts_start"] == target_start, "pv_mw"],
                errors="coerce",
            )
            if len(actual) != 1 or not np.isfinite(actual.iloc[0]):
                raise ValueError(f"TF光伏回测缺少 ISO-NE BTM PV 实际估算值: {target_start}")
            windows.append({
                "target_time": str(target_start),
                "actual_pv_mw": round(float(actual.iloc[0]), 2),
                "past": past.to_dict("records"),
                "future": future.to_dict("records"),
            })
        return windows

    def _prepare_load_market(
        self,
        frames: dict[str, pd.DataFrame],
        weather: pd.DataFrame,
    ) -> pd.DataFrame:
        """按训练时的字段、时间语义和特征公式生成 tf_v2 市场特征表。"""
        market = frames["load"].join(frames["da_demand"], how="outer")
        market = market.join(frames["rt_lmp"], how="outer").join(frames["da_lmp"], how="outer")
        load_weather = weather.rename_axis("weather_start").copy()
        # Open-Meteo 是 hour-start，tf_v2 的市场序列是 hour-ending。
        load_weather.index = load_weather.index + pd.Timedelta(hours=1)
        market = market.join(load_weather[["temperature_2m", "dew_point_2m"]], how="outer")
        market = market.rename(columns={
            "load": "RT_Demand", "da_demand": "DA_Demand",
            "rt_lmp": "RT_LMP", "da_lmp": "DA_LMP",
        }).sort_index()
        # shift(24) 必须表示24个物理小时，不能因缺一行变成25小时。
        if not market.empty:
            market = market.reindex(pd.date_range(market.index.min(), market.index.max(), freq="h"))
        market["Dry_Bulb"] = market["temperature_2m"] * 9 / 5 + 32
        market["Dew_Point"] = market["dew_point_2m"] * 9 / 5 + 32
        market["hdd65"] = np.clip(65 - market["Dry_Bulb"], 0, None)
        market["cdd65"] = np.clip(market["Dry_Bulb"] - 65, 0, None)
        market["temp_mem"] = market["Dry_Bulb"].shift(1).ewm(alpha=0.1, adjust=False).mean()
        market = market.reset_index(names="ts_local")
        market["clock_hour"] = pd.DatetimeIndex(market["ts_local"]).hour
        self._calendar(market, "ts_local", "clock_hour")
        month = pd.DatetimeIndex(market["ts_local"]).month.to_numpy(dtype=float)
        market["month_sin"] = np.sin(2 * np.pi * month / 12)
        market["month_cos"] = np.cos(2 * np.pi * month / 12)
        years = set(pd.DatetimeIndex(market["ts_local"]).year)
        holidays = _holiday_days(years)
        dates = pd.DatetimeIndex(market["ts_local"]).date
        market["is_holiday"] = [int(value in holidays) for value in dates]
        market["holiday_shoulder"] = [int(value in holidays or value - timedelta(days=1) in holidays or value + timedelta(days=1) in holidays) for value in dates]
        market["is_dst"] = [int(_is_dst_day(value)) for value in dates]
        market["rt_lag24"] = market["RT_Demand"].shift(24)
        market["rt_lag168"] = market["RT_Demand"].shift(168)
        market["rt_prev24_mean"] = market["RT_Demand"].shift(1).rolling(24).mean()
        market["rt_prev168_mean"] = market["RT_Demand"].shift(1).rolling(168).mean()
        market["rtlmp_lag1"] = market["RT_LMP"].shift(1)
        market["rtlmp_lag24"] = market["RT_LMP"].shift(24)
        market["rtlmp_lag168"] = market["RT_LMP"].shift(168)
        market["rtlmp_prev24_mean"] = market["RT_LMP"].shift(1).rolling(24).mean()
        market["da_lmp_lag24"] = market["DA_LMP"].shift(24)
        actual_map = market.set_index("ts_local")["RT_Demand"]
        market["rt_yest"] = [
            actual_map.get(pd.Timestamp(value) - pd.Timedelta(hours=24), np.nan)
            for value in market["ts_local"]
        ]
        return market

    def build_day_backtest(self, target_day: date, weather_df: pd.DataFrame,
                           future_hours: int = 24) -> list[dict]:
        """生成 ``target_day`` 的 tf_v2 逐小时回测输入窗口。

        每个目标小时均取其前 168 小时作为 past 输入，并提供该目标起
        future_hours 小时的日前/气象/日历 future 特征（默认24，单步为1）；模型调用方只使用第 0 个输出与目标小时
        的 ISO-NE 实际负荷对齐。所有实时特征都严格早于该目标小时，天气为
        回顾性观测，因此结果属于回溯验证而非当时可获得天气预报的精度。
        """
        weather = self._weather(weather_df)
        if weather.empty:
            raise ValueError("Open-Meteo 历史气象为空，无法构建 TF 按日回测")
        day_start = pd.Timestamp(target_day)
        # 最早窗口从 D-8 00:00 开始；额外预留一天供 temp_mem 热启动。
        frames = self._market_frames_for_range(
            actual_start=(day_start - pd.Timedelta(days=16)).date(),
            actual_end=target_day,
            da_end=(day_start + pd.Timedelta(days=1)).date(),
        )
        if any(frames[name].empty for name in ("load", "da_demand", "rt_lmp", "da_lmp", "pv")):
            empty = [name for name, value in frames.items() if value.empty]
            raise RuntimeError(f"ISO-NE 历史回测特征源为空: {empty}")
        market = self._prepare_load_market(frames, weather)
        return self._build_load_backtest_windows(
            market, day_start + pd.Timedelta(hours=23), hours=24,
            future_hours=future_hours,
        )

    @staticmethod
    def validate_price_backtest_window(origin_day: date) -> None:
        # Include lag168/rolling168 warm-up, not only the 24 target slots.
        day_start = pd.Timestamp(origin_day)
        edges = pd.date_range(day_start - pd.Timedelta(hours=336), day_start + pd.Timedelta(hours=24), freq="h").tz_localize(
            "America/New_York", ambiguous="NaT", nonexistent="NaT")
        if edges.isna().any():
            raise ValueError("电价回测特征窗口跨越夏令时切换；当前模型本地24小时窗口暂不支持可靠回测")

    def build_price_day_backtest(self, origin_day: date, weather_df: pd.DataFrame) -> dict:
        """重放固定回测相同的 D 00:00 锚点，预测 D 01:00 至 D+1 00:00。

        168 小时历史输入截止锚点；24 小时未来输入仅含日前、天气和日历
        等模型当时可用的字段。真实 RT-LMP 只作为输出标签，不进入未来输入。
        必需特征缺失直接报错；目标标签缺失保留空值，补充输入不计真实误差。
        """
        day_start = pd.Timestamp(origin_day)
        self.validate_price_backtest_window(origin_day)
        weather = self._weather(weather_df)
        if weather.empty:
            raise ValueError("历史气象为空，无法进行电价回测")
        frames = self._market_frames_for_range(
            actual_start=(day_start - pd.Timedelta(days=16)).date(),
            actual_end=origin_day,
            da_end=(day_start + pd.Timedelta(days=1)).date(),
        )
        required = ("load", "da_demand", "rt_lmp", "da_lmp")
        empty = [name for name in required if frames[name].empty]
        if empty:
            raise ValueError(f"电价回测所需 ISO-NE 历史数据为空: {empty}")
        market = self._prepare_load_market(frames, weather)
        past = self._require_contiguous(
            market[["ts_local"] + LOAD_PAST_COLS], "ts_local",
            day_start - pd.Timedelta(hours=167), 168, "电价回测历史输入",
        )
        future_start = day_start + pd.Timedelta(hours=1)
        future = self._require_contiguous(
            market[["ts_local"] + LOAD_FUTURE_COLS], "ts_local",
            future_start, 24, "电价回测未来输入",
        )
        label_columns = ["RT_LMP"] + [name for name in ("rt_lmp_source", "rt_lmp_samples", "rt_lmp_label_valid") if name in market]
        actual = market.set_index("ts_local")[label_columns].reindex(
            pd.date_range(future_start, periods=24, freq="h")).rename_axis("ts_local").reset_index()
        return {
            "past": past.to_dict("records"),
            "future": future.to_dict("records"),
            "actual": actual.to_dict("records"),
        }

    def build(self, weather_df: pd.DataFrame, force_refresh: bool = False) -> dict:
        with self._lock:
            now_hour_end = self._current_eastern_hour()
            if (not force_refresh and self._cached
                    and time.time() - self._cached_at < self.cache_ttl
                    and self._cached_hour == now_hour_end
                    and self._cached_weather is not None
                    and self._cached_weather.equals(weather_df)):
                return self._cached
            if force_refresh:
                with self._day_lock:
                    for key in list(self._day_cache):
                        if key[1] >= now_hour_end.date() - timedelta(days=1):
                            self._day_cache.pop(key)

            weather = self._weather(weather_df)
            pv_weather = self._pv_weather(weather_df)
            if weather.empty:
                raise ValueError("Open-Meteo 数据为空，无法构建 TF 在线特征")
            frames = self._market_frames(pd.Timestamp.now(tz="America/New_York").date())
            if any(frames[name].empty for name in frames):
                empty = [name for name, value in frames.items() if value.empty]
                raise RuntimeError(f"ISO-NE 在线特征源为空: {empty}")

            # 所有实况共同可用的最近完整物理小时。weather/pv 为 hour-start，市场为 hour-end。
            # 只选择已经结束的小时，即使当前小时已发布8个五分钟点也不提前采用。
            latest_actual_hour_end = self._latest_contiguous_hour(
                [frames["load"].index[frames["load"].index <= now_hour_end], frames["rt_lmp"].index,
                 frames["pv"].index + pd.Timedelta(hours=1)],
                # load features contain lag-168 and a 168-hour rolling window.
                periods=336,
            )
            # 实时预测必须锚定最新完整实况小时，不能因为下一交易日的日前曲线
            # 尚未全部发布而把整条预测轴回退到昨天，更不能因一个历史孤立缺口
            # 回退数天。未来尚未发布的 DA 特征在下方显式、可追踪地补齐。
            origin_end = pd.Timestamp(latest_actual_hour_end).floor("h")
            origin_lag_hours = max(
                0.0, (now_hour_end - origin_end).total_seconds() / 3600.0
            )
            if origin_lag_hours > MAX_LIVE_ORIGIN_LAG_HOURS:
                raise ValueError(
                    "ISO-NE 实时数据滞后，拒绝生成伪实时预测: "
                    f"当前={now_hour_end}, 最新完整锚点={origin_end}, "
                    f"滞后={origin_lag_hours:.0f}小时"
                )
            frames, imputed_day_ahead = self._fill_future_day_ahead(
                frames, origin_end, periods=24
            )
            origin_start = origin_end - pd.Timedelta(hours=1)

            # 负荷/电价：市场与天气都映射到 hour-ending。
            market = self._prepare_load_market(frames, weather)
            load_past = self._require_contiguous(
                market[["ts_local"] + LOAD_PAST_COLS], "ts_local",
                origin_end - pd.Timedelta(hours=167), 168, "TF负荷历史特征")
            load_future = self._require_contiguous(
                market[["ts_local"] + LOAD_FUTURE_COLS], "ts_local",
                origin_end + pd.Timedelta(hours=1), 24, "TF负荷未来特征")
            load_backtest = self._build_load_backtest_windows(
                market, origin_end, skip_incomplete=True
            )

            # 光伏：天气和实况均使用 hour-start。
            pv = pv_weather.join(frames["pv"], how="outer").sort_index()
            # pv_v2 直接学习统一 ISO-NE 五分钟接口汇总后的 MW，不再使用旧
            # Normalized BTM PV 与装机容量相乘反归一化。
            pv["pv_mw_ISONE"] = pv["pv_mw"]
            pv = pv.reset_index(names="ts_start")
            pv_index = pd.DatetimeIndex(pv["ts_start"])
            # 与 noaa_local_v2 训练数据契约一致：按 New England 本地时间、
            # 夏令时和东部标准经线计算太阳几何。
            pv["coszen"] = _solar_coszen(pv_index)
            pv["sun_up"] = (pv["coszen"] > 0.02).astype(int)
            pv["hour"] = pv_index.hour
            self._calendar(pv, "ts_start", "hour")
            doy = pv_index.dayofyear.to_numpy(dtype=float)
            pv["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
            pv["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
            pv["trend_days"] = (
                pv_index - PV_TREND_START
            ).total_seconds().to_numpy(dtype=float) / 86400.0
            pv_past = self._require_contiguous(
                pv[["ts_start"] + PV_PAST_COLS], "ts_start",
                origin_start - pd.Timedelta(hours=95), 96, "TF光伏历史特征")
            pv_future = self._require_contiguous(
                pv[["ts_start"] + PV_FUTURE_COLS], "ts_start",
                origin_start + pd.Timedelta(hours=1), 24, "TF光伏未来特征")
            pv_backtest = self._build_pv_backtest_windows(pv, origin_start)

            partial_pv = []
            if "minimum_samples" in frames["pv"].columns:
                relevant_pv = frames["pv"].loc[
                    (frames["pv"].index >= origin_start - pd.Timedelta(hours=335))
                    & (frames["pv"].index <= origin_start)
                ]
                partial_pv = [
                    {"time": str(index), "samples_per_zone": int(value)}
                    for index, value in relevant_pv["minimum_samples"].items()
                    if int(value) < 12
                ]

            source = "iso_ne+open_meteo"
            if imputed_day_ahead:
                source += "+day_ahead_persistence"
            result = {
                "load_price": {"past": load_past.to_dict("records"),
                               "future": load_future.to_dict("records")},
                "load_price_backtest": load_backtest,
                "pv": {"past": pv_past.to_dict("records"),
                       "future": pv_future.to_dict("records")},
                "pv_backtest": pv_backtest,
                "origin_hour_end": str(origin_end),
                "origin_hour_start": str(origin_start),
                "data_source": source,
                "pv_data_source": "iso_ne+open_meteo",
                "input_quality": {
                    "origin_lag_hours": origin_lag_hours,
                    "day_ahead_imputed": imputed_day_ahead,
                    "partial_pv_hours": partial_pv,
                    "pv_minimum_samples_per_zone": MIN_FIVE_MINUTE_PV_SAMPLES,
                },
            }
            self._cached = result
            self._cached_at = time.time()
            self._cached_hour = now_hour_end
            self._cached_weather = weather_df.copy()
            if imputed_day_ahead:
                logger.warning(
                    "未来日前特征包含 %s 个同小时持久性补值，预测锚点=%s",
                    len(imputed_day_ahead), origin_end,
                )
            if partial_pv:
                logger.warning("PV 历史窗口包含部分采样小时: %s", partial_pv)
            logger.info(
                "TF 在线特征已生成，预测锚点(hour-end)=%s，滞后=%.1fh",
                origin_end, origin_lag_hours,
            )
            return result
