import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import weather_bulk as bulk
from weather_data import SITES, VARIABLES


def approve(tmp_path,monkeypatch):
    monkeypatch.setattr(bulk,"EXPERIMENT_ROOT",tmp_path)
    (tmp_path/"logs").mkdir()
    (tmp_path/"logs"/"training_authorization.json").write_text(json.dumps({"status":"approved","weather_kind":"forecast_fixed_lead_day2"}))


def response(status=200,missing=False):
    axis=pd.date_range("2024-06-01T00:00Z",periods=4,freq="h")
    units={"temperature_2m":"°C","relative_humidity_2m":"%","cloud_cover":"%","wind_speed_10m":"m/s","surface_pressure":"hPa"}
    units.update({v:"W/m²" for v in VARIABLES[3:7]})
    hourly={v+"_previous_day2":[1.0]*4 for v in VARIABLES}
    if missing:hourly["shortwave_radiation_previous_day2"][2]=None
    data={"utc_offset_seconds":0,"hourly_units":{v+"_previous_day2":u for v,u in units.items()},
          "hourly":{"time":[int(t.timestamp()) for t in axis],**hourly}}
    result=requests.Response();result.status_code=status;result.url="https://previous-runs-api.open-meteo.com/v1/forecast"
    result._content=json.dumps(data).encode();result.headers={}
    return result


class NoWait:
    def acquire(self):pass


class Session:
    def __init__(self,*results):self.results=list(results);self.calls=0
    def get(self,*args,**kwargs):
        self.calls+=1
        result=self.results.pop(0)
        if isinstance(result,Exception):raise result
        return result


def test_pending_authorization_blocks_before_any_weather_request_or_output(tmp_path,monkeypatch):
    monkeypatch.setattr(bulk,"EXPERIMENT_ROOT",tmp_path)
    with pytest.raises(PermissionError,match="pending"):
        bulk.download_weather(pd.Timestamp("2024-01-01T00:00Z"),pd.Timestamp("2024-02-01T00:00Z"),output_id="test")
    assert not (tmp_path/"data").exists()


def test_month_chunks_are_bounded_without_overlap_or_dst_calendar_loss():
    start=pd.Timestamp("2024-03-01T00:00Z");end=pd.Timestamp("2024-04-12T03:00Z")
    chunks=bulk.monthly_chunks(start,end)
    assert chunks==[(start,pd.Timestamp("2024-04-01T00:00Z")),(pd.Timestamp("2024-04-01T00:00Z"),end)]


def test_raw_cache_hash_resume_and_missing_cells_are_preserved(tmp_path,monkeypatch):
    approve(tmp_path,monkeypatch)
    session=Session(response(missing=True))
    args=(SITES[0],"previous_day2","gfs_global",pd.Timestamp("2024-06-01T00:00Z"),pd.Timestamp("2024-06-01T03:00Z"))
    frame,manifest=bulk.fetch_chunk(*args,limiter=NoWait(),session=session)
    assert len(frame)==3
    assert np.isnan(frame.shortwave_radiation.iloc[1])
    assert manifest["missing_by_variable"]["shortwave_radiation"]==1
    assert hashlib.sha256(Path(manifest["raw_path"]).read_bytes()).hexdigest()==manifest["sha256"]
    second,again=bulk.fetch_chunk(*args,limiter=NoWait(),session=session)
    assert session.calls==1
    assert again==manifest
    assert second.shortwave_radiation.isna().sum()==1


def test_network_failure_and_429_retry_then_recover_without_fabrication(tmp_path,monkeypatch):
    approve(tmp_path,monkeypatch)
    monkeypatch.setattr(bulk.time,"sleep",lambda seconds:None)
    session=Session(requests.ConnectionError("offline"),response(status=429),response())
    frame,_=bulk.fetch_chunk(SITES[0],"previous_day2","gfs_global",pd.Timestamp("2024-06-01T00:00Z"),
                            pd.Timestamp("2024-06-01T03:00Z"),limiter=NoWait(),session=session)
    assert session.calls==3
    assert np.isfinite(frame[list(VARIABLES)].to_numpy()).all()
