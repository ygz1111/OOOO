"""Inference service for the separately trained load and price TensorFlow models."""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np
import pandas as pd
from models.tensorflow_load import tf_split_models as M

_BACKEND = Path(__file__).resolve().parents[1]

class Scaler:
    def __init__(self, d, prefix):
        self.mean=np.asarray(d[f"{prefix}_mean"], dtype="float64"); self.scale=np.asarray(d[f"{prefix}_scale"], dtype="float64")
    def transform(self,x): return (np.asarray(x,dtype="float64")-self.mean)/self.scale
    def inverse(self,x): return np.asarray(x,dtype="float64")*self.scale+self.mean

class TFSplitService:
    MODEL_NAME="tf_split_v1"; MODEL_LABEL="TF Split v1 (独立负荷 + 独立电价分位)"
    def __init__(self, assets_dir=None):
        self.assets_dir=Path(assets_dir or _BACKEND/"models"/"tf_assets"/"tf_split_v1")
        self._loaded=False; self._frame=None; self._origin=None; self._inference_count=0; self._total_inference_time_ms=0.0
    @property
    def is_ready(self): return self._loaded
    def _need(self,name):
        p=self.assets_dir/name
        if not p.exists(): raise FileNotFoundError(f"TF Split 资产缺失: {p}")
        return p
    def load_models(self):
        self._load_sp=Scaler(json.loads(self._need("load_scalers.json").read_text()),"sp"); self._load_sf=Scaler(json.loads(self._need("load_scalers.json").read_text()),"sf"); self._load_sy=Scaler(json.loads(self._need("load_scalers.json").read_text()),"sy")
        self._price_sp=Scaler(json.loads(self._need("price_scalers.json").read_text()),"sp"); self._price_sf=Scaler(json.loads(self._need("price_scalers.json").read_text()),"sf"); self._price_sy=Scaler(json.loads(self._need("price_scalers.json").read_text()),"sy")
        self._load_model,self._price_model=M.load_models(str(self._need("load_best.weights.h5")),str(self._need("price_best.weights.h5")))
        self._load_first_step_model = M.build_load_first_step_model(self._load_model)
        self._frame=pd.read_parquet(self._need("ca_features.parquet")).sort_values("seq").reset_index(drop=True)
        self._frame["ts_local"]=pd.to_datetime(self._frame["ts_local"]); self._frame["rt_yest"]=self._frame["RT_Demand"].shift(24)
        self._origin=self._frame["ts_local"].iloc[-25]; self._loaded=True
    def _matrix(self, frame, cols, rows, label):
        if len(frame)!=rows: raise ValueError(f"{label}行数必须为 {rows}")
        miss=[x for x in cols if x not in frame]
        if miss: raise ValueError(f"{label}缺少训练特征: {miss}")
        x=frame[cols].apply(pd.to_numeric,errors="coerce").to_numpy("float64")
        if not np.isfinite(x).all(): raise ValueError(f"{label}含 NaN/Inf")
        return x
    def _run(self,past,future,times,origin,data_source,task=None):
        t = time.perf_counter()
        ff = self._matrix(future, M.FUTURE_COLS, M.HORIZON, "未来输入")
        load, q = None, None
        if task in (None, "load"):
            lp = self._matrix(past, M.LOAD_PAST_COLS, M.LOOKBACK, "负荷历史输入")
            raw_load = self._load_model.predict([self._load_sp.transform(lp).astype("float32")[None], self._load_sf.transform(ff).astype("float32")[None]], verbose=0)[0, :, 0]
            load = self._load_sy.inverse(raw_load[:, None]).ravel()
            if not np.isfinite(load).all():
                raise ValueError("负荷输出包含非有限值")
        if task in (None, "price"):
            pp = self._matrix(past, M.PRICE_PAST_COLS, M.LOOKBACK, "电价历史输入")
            raw = self._price_model.predict([self._price_sp.transform(pp).astype("float32")[None], self._price_sf.transform(ff).astype("float32")[None]], verbose=0)[0]
            q = np.sinh(self._price_sy.inverse(raw)) * 50.0
            if not np.isfinite(q).all():
                raise ValueError("电价输出包含非有限值")
        rows = [{"hour": i, "timestamp": str(pd.Timestamp(ts)),
                 "load_forecast_mw": round(float(load[i]), 1) if load is not None else None,
                 **{f"price_p{n}": round(float(q[i, j]), 2) if q is not None else None for j, n in enumerate((10, 50, 90))},
                 "price_unit": "USD/MWh"} for i, ts in enumerate(times)]
        anchor_load = float(past["RT_Demand"].iloc[-1])
        history_actual = [
            {
                "target_time": str(pd.Timestamp(ts)),
                "actual_load_mw": round(float(value), 1),
            }
            for ts, value in zip(
                pd.to_datetime(past["ts_local"].iloc[-24:]),
                pd.to_numeric(past["RT_Demand"].iloc[-24:]),
            )
        ]
        ms=(time.perf_counter()-t)*1000; self._inference_count+=1; self._total_inference_time_ms+=ms
        return {"status":"success","model":self.MODEL_NAME,"hourly":rows,"timestamps":[r["timestamp"] for r in rows],"origin":str(origin),"anchor_actual_load_mw":round(anchor_load,1),"anchor_history_actual":history_actual,"data_source":data_source,"inference_time_ms":round(ms,1),"ensemble_weights":{"tf_split_v1":1.0},"unit":{"load":"MW","price":"USD/MWh"}}
    def predict_features(self,past_features,future_features):
        if not self._loaded: raise RuntimeError("TF Split 模型未加载")
        p=pd.DataFrame(past_features); f=pd.DataFrame(future_features); times=pd.to_datetime(f.get("ts_local",f.get("timestamp"))).tolist()
        return self._run(p,f,times,pd.to_datetime(p.get("ts_local",p.get("timestamp")).iloc[-1]),"live_features")
    def predict_task_features(self, task, past_features, future_features):
        if task not in ("load", "price") or not self._loaded:
            raise ValueError("独立预测任务无效或模型未加载")
        p, f = pd.DataFrame(past_features), pd.DataFrame(future_features)
        times = list(pd.to_datetime(f["ts_local"]))
        return self._run(p, f, times, pd.Timestamp(p.ts_local.iloc[-1]), "live_features", task)
    @staticmethod
    def _first_step_times(frame, rows, label):
        column = "ts_local" if "ts_local" in frame else "timestamp"
        if column not in frame or len(frame) != rows:
            raise ValueError(f"{label}时间戳缺失或行数必须为 {rows}")
        try:
            times = [pd.Timestamp(value) for value in frame[column]]
            times = pd.DatetimeIndex([value.tz_convert("America/New_York").tz_localize(None)
                                      if value.tzinfo is not None else value for value in times])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{label}时间戳无法解析") from exc
        if (times.isna().any() or not times.equals(times.floor("h"))
                or not times.equals(pd.date_range(times[0], periods=rows, freq="h"))):
            raise ValueError(f"{label}时间必须为连续整点小时")
        edges = times.insert(0, times[0] - pd.Timedelta(hours=1)).tz_localize(
            "America/New_York", ambiguous="NaT", nonexistent="NaT")
        if edges.isna().any():
            raise ValueError(f"{label}跨越夏令时歧义或不存在的小时，暂不支持可靠回测")
        return times
    def predict_load_first_step_features(self, past_features, future_features):
        """Replay one load target using the same loaded weights and one future hour."""
        if not self._loaded:
            raise RuntimeError("TF Split 模型未加载")
        started = time.perf_counter()
        past, future = pd.DataFrame(past_features), pd.DataFrame(future_features)
        past_times = self._first_step_times(past, M.LOOKBACK, "负荷单步历史输入")
        future_times = self._first_step_times(future, 1, "负荷单步未来输入")
        if future_times[0] != past_times[-1] + pd.Timedelta(hours=1):
            raise ValueError("负荷单步目标必须紧接历史窗口的下一小时")
        lp = self._matrix(past, M.LOAD_PAST_COLS, M.LOOKBACK, "负荷单步历史输入")
        ff = self._matrix(future, M.FUTURE_COLS, 1, "负荷单步未来输入")
        raw = np.asarray(self._load_first_step_model.predict([
            self._load_sp.transform(lp).astype("float32")[None],
            self._load_sf.transform(ff).astype("float32")[None]], verbose=0))
        if raw.shape != (1, 1, 1) or not np.isfinite(raw).all():
            raise ValueError("负荷单步输出形状异常或包含非有限值")
        load = float(self._load_sy.inverse(raw[0, :, 0][:, None]).ravel()[0])
        if not np.isfinite(load) or load < 0:
            raise ValueError("负荷单步输出含非有限值或负负荷")
        row = {"hour": 0, "timestamp": str(future_times[0]), "load_forecast_mw": round(load, 1)}
        elapsed = (time.perf_counter() - started) * 1000
        self._inference_count += 1
        self._total_inference_time_ms += elapsed
        return {"status": "success", "model": self.MODEL_NAME, "hourly": [row],
                "timestamps": [row["timestamp"]], "origin": str(past_times[-1]),
                "data_source": "historical_replay:first_step", "inference_time_ms": round(elapsed, 1),
                "ensemble_weights": {"tf_split_v1": 1.0}, "unit": {"load": "MW"}}
    def predict(self,origin_ts_local=None):
        if not self._loaded: raise RuntimeError("TF Split 模型未加载")
        origin=pd.Timestamp(origin_ts_local) if origin_ts_local else self._origin; pos=int(np.flatnonzero(self._frame.ts_local==origin)[0])
        p=self._frame.iloc[pos-M.LOOKBACK+1:pos+1]; f=self._frame.iloc[pos+1:pos+M.HORIZON+1]
        return self._run(p,f,list(f.ts_local),origin,"frozen_tail_demo")
    def price_backtest(self,selected_date=None):
        f=self._frame; candidates=f.iloc[M.LOOKBACK:len(f)-M.HORIZON].copy(); dates=sorted(candidates.loc[candidates.ts_local.dt.hour==0,"ts_local"].dt.strftime("%Y-%m-%d").unique()); rng={"earliest":dates[0],"latest":dates[-1]}
        if selected_date is None:return {"available_date_range":rng,"date":None,"points":[],"metrics":None}
        origin=pd.Timestamp(selected_date); res=self.predict(str(origin)); actual=f.iloc[int(np.flatnonzero(f.ts_local==origin)[0])+1:int(np.flatnonzero(f.ts_local==origin)[0])+25].RT_LMP.to_numpy(float); points=[]
        for row,a in zip(res["hourly"],actual): points.append({**row,"price_actual":round(float(a),2),"error_p50":round(float(row["price_p50"]-a),2)})
        e=np.asarray([p["error_p50"] for p in points]); valid=np.abs(actual)>=1
        coverage = float(np.mean([(p["price_p10"] <= a <= p["price_p90"]) for p, a in zip(points, actual)]) * 100)
        # Near-zero (including negative) RT-LMP labels remain valid for absolute
        # errors/coverage; an empty relative-error subset has no defined MAPE.
        mape = round(float((np.abs(e[valid])/np.abs(actual[valid])).mean()*100),2) if valid.any() else None
        metrics={"count":24,"mae_usd":round(float(np.abs(e).mean()),2),"rmse_usd":round(float(np.sqrt((e**2).mean())),2),"mape_pct":mape,"median_ae_usd":round(float(np.median(np.abs(e))),2),"bias_usd":round(float(e.mean()),2),"p10_p90_coverage":round(coverage,1)}
        metric_note = "P50 与真实 RT-LMP 的回测对比"
        if mape is None:
            metric_note += "；MAPE 仅统计绝对电价≥1 USD/MWh 的小时，本日无符合条件样本"
        return {"available_date_range":rng,"date":selected_date,"origin":str(origin),"model":self.MODEL_NAME,"data_source":"frozen_historical_backtest","points":points,"metrics":metrics,"metric_note":metric_note}
    def get_model_info(self):
        """Expose the two independently trained networks as separate models."""
        load_params = int(self._load_model.count_params()) if self._loaded else 0
        price_params = int(self._price_model.count_params()) if self._loaded else 0
        return {
            "tf_load_split_v1": {
                "name": "负荷预测模型",
                "label": "TensorFlow 负荷预测模型（TF Split v1）",
                "task": "未来24小时负荷预测",
                "architecture": "BiGRU-GRU",
                "weight": 1.0,
                "num_params": load_params,
                "loaded": self.is_ready,
                "lookback": 168,
                "horizon": 24,
            },
            "tf_price_split_v1": {
                "name": "电价预测模型",
                "label": "TensorFlow 电价预测模型（TF Split v1）",
                "task": "未来24小时P10/P50/P90电价预测",
                "architecture": "BiGRU-GRU Quantile",
                "weight": 1.0,
                "num_params": price_params,
                "loaded": self.is_ready,
                "lookback": 168,
                "horizon": 24,
            },
        }
    def calculate_demo_feature_sensitivity(self):
        """Return frozen-window occlusion sensitivity for the load model.

        This keeps the operation-situation page compatible with the split service
        without introducing a second inference path.
        """
        if not self._loaded:
            raise RuntimeError("TF Split 模型未加载")
        pos = int(np.flatnonzero(self._frame.ts_local == self._origin)[0])
        past = self._frame.iloc[pos - M.LOOKBACK + 1:pos + 1].copy()
        future = self._frame.iloc[pos + 1:pos + M.HORIZON + 1].copy()
        base_p = self._load_sp.transform(past[M.LOAD_PAST_COLS]).astype("float32")[None]
        base_f = self._load_sf.transform(future[M.FUTURE_COLS]).astype("float32")[None]
        baseline = self._load_sy.inverse(
            self._load_model.predict([base_p, base_f], verbose=0)[0, :, 0][:, None]
        ).ravel()
        groups = {
            "负荷与需求": ["RT_Demand", "DA_Demand", "rt_lag24", "rt_lag168", "rt_prev24_mean", "rt_prev168_mean"],
            "电价": ["RT_LMP", "DA_LMP"],
            "气象": ["Dry_Bulb", "Dew_Point", "hdd65", "cdd65", "temp_mem"],
            "时间与日历": ["clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos", "is_holiday", "is_dst"],
        }
        impacts = []
        for label, cols in groups.items():
            altered = base_p.copy()
            changed = [col for col in cols if col in M.LOAD_PAST_COLS]
            for col in changed:
                altered[0, :, M.LOAD_PAST_COLS.index(col)] = 0.0
            curve = self._load_sy.inverse(
                self._load_model.predict([altered, base_f], verbose=0)[0, :, 0][:, None]
            ).ravel()
            delta = curve - baseline
            impacts.append({
                "feature_group": label,
                "mean_absolute_impact_mw": round(float(np.mean(np.abs(delta))), 2),
                "peak_impact_mw": round(float(np.max(np.abs(delta))), 2),
                "directional_change_mw": round(float(np.mean(delta)), 2),
                "feature_count": len(changed),
            })
        return sorted(impacts, key=lambda item: item["mean_absolute_impact_mw"], reverse=True)
    def get_status(self): return {"ready":self.is_ready,"loaded":self.is_ready,"model":self.MODEL_NAME,"inference_count":self._inference_count,"total_inferences":self._inference_count,"avg_inference_time_ms":round(self._total_inference_time_ms/max(self._inference_count,1),1),"average_inference_time_ms":round(self._total_inference_time_ms/max(self._inference_count,1),1)}
    def close(self): self._loaded=False
