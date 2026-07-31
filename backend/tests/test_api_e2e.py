# -*- coding: utf-8 -*-
"""
API 集成测试（HTTP 层端到端）

通过 FastAPI TestClient 启动完整应用（含 lifespan 模型加载），验证：
  - 认证：未认证 401 / 登录 200 / 带 token 访问受保护端点 200
  - 白名单：/api/health、/metrics 公开
  - 预测：POST /api/prediction/load 返回 24 小时真实预测
  - 光伏：GET /api/solar-generation 返回 ML 集成预测

注意：需要已训练模型权重（backend/models/models/*.pth），
CI 环境（权重未入库）下自动跳过。
"""
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 模型权重存在才运行集成测试（CI 无权重则跳过）
MODEL_WEIGHTS = [
    BACKEND_DIR / "models" / "models" / "enhancedlstm_best_model.pth",
    BACKEND_DIR / "models" / "models" / "bigru_best_model.pth",
    BACKEND_DIR / "models" / "models" / "deeptcn_best_model.pth",
    BACKEND_DIR / "models" / "models" / "spatialtransformer_best_model.pth",
]

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in MODEL_WEIGHTS),
    reason="模型权重不存在（训练产物未入库），跳过集成测试",
)


@pytest.fixture(scope="module")
def client():
    """启动一次完整应用（lifespan 加载模型），供本模块所有测试复用"""
    from fastapi.testclient import TestClient
    from realtime_api.app import app

    with TestClient(app) as c:
        yield c


def _login(client, username="testuser99", password="Test@12345"):
    """登录并返回 access_token；账号不存在则注册"""
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    if r.status_code == 200:
        tok = r.json()["access_token"]
        import jwt
        from realtime_api.config_manager import get_jwt_secret
        try:
            jwt.decode(tok, get_jwt_secret(), algorithms=["HS256"])
            print(f"[dbg] login token OK for {username}")
        except Exception as e:
            print(f"[dbg] login token DECODE FAIL: {e}")
        return tok
    # 注册后重试
    reg = client.post("/api/auth/register", json={
        "username": username, "email": f"{username}@test.com", "password": password,
    })
    if reg.status_code in (200, 201, 400):
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, f"登录失败: {r.text}"
        return r.json()["access_token"]
    raise AssertionError(f"无法登录/注册: {reg.status_code} {reg.text}")


class TestAuthFlow:
    def test_unauthenticated_protected_401(self, client):
        r = client.post("/api/prediction/load", json={})
        assert r.status_code == 401
        assert client.get("/api/system/metrics").status_code == 401
        assert client.get("/api/analytics/accuracy/stats").status_code == 401

    def test_public_endpoints_open(self, client):
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/metrics").status_code == 200

    def test_login_and_me(self, client):
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200
        assert "user" in me.json() or "username" in str(me.json())

    def test_refresh_token_not_valid_as_access(self, client):
        # 带 remember_me 拿 refresh token
        r = client.post("/api/auth/login", json={
            "username": "testuser99", "password": "Test@12345", "remember_me": True,
        })
        if r.status_code != 200:
            pytest.skip("登录不可用，跳过 refresh 测试")
        refresh = r.json().get("refresh_token")
        if not refresh:
            pytest.skip("无 refresh_token")
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh}"})
        assert me.status_code == 401  # refresh 不能当 access 用


class TestPredictionFlow:
    def test_load_prediction(self, client):
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        r = client.post("/api/prediction/load", json={}, headers=headers)
        assert r.status_code == 200, f"预测失败: {r.text[:300]}"
        data = r.json()
        assert data["status"] == "success"
        preds = data["predictions"]
        assert len(preds) == 24
        # 负荷预测值应在合理范围（新英格兰电网 5000~30000 MW）
        loads = [p["load_forecast_mw"] for p in preds]
        assert all(5000 <= v <= 30000 for v in loads)
        # 模型信息完整
        names = [m["name"] for m in data["model_info"]]
        assert len(names) == 4

    def test_solar_generation(self, client):
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        r = client.get("/api/solar-generation", headers=headers)
        assert r.status_code == 200, f"光伏预测失败: {r.text[:300]}"
        data = r.json()
        assert data["model_type"] == "ml_ensemble"
        assert len(data["hourly_pv_mw"]) == 24
        # 光伏出力非负且不超过合理上限
        pv = data["hourly_pv_mw"]
        assert all(0 <= float(v) <= 5000 for v in pv)
