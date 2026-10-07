"""Session lifecycle regressions using only an isolated in-memory SQL database."""
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from fastapi import FastAPI, Request

from realtime_api import database
from realtime_api.auth import middleware
from realtime_api.crud import auth_crud
from realtime_api.crud.auth_crud import AuthCRUD
from realtime_api.routers.auth import router


class MemoryResult:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return SimpleNamespace(**dict(row)) if row is not None else None


class MemorySession:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, username TEXT, email TEXT,
                full_name TEXT, department TEXT, phone TEXT,
                is_active INTEGER DEFAULT 1, is_verified INTEGER DEFAULT 1,
                last_login_at TEXT, created_at TEXT, updated_at TEXT
            );
            INSERT INTO users (id, username, email, created_at, updated_at)
            VALUES (1, 'alpha', 'alpha@example.test', '2026-01-01', '2026-01-01');
            CREATE TABLE user_sessions (
                id INTEGER PRIMARY KEY, user_id INTEGER, session_id TEXT UNIQUE,
                jwt_token TEXT, refresh_token TEXT, client_ip TEXT, user_agent TEXT,
                platform TEXT, expires_at TEXT, last_activity TEXT,
                is_active INTEGER DEFAULT 1, revoked_at TEXT
            );
        """)

    async def execute(self, query, params=None):
        sql = str(query).replace("UTC_TIMESTAMP()", "CURRENT_TIMESTAMP").replace("NOW()", "CURRENT_TIMESTAMP")
        return MemoryResult(self.connection.execute(sql, params or {}))

    async def commit(self):
        self.connection.commit()

    async def rollback(self):
        self.connection.rollback()


@pytest.fixture
def auth_app(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET_KEY", "isolated-auth-regression-key-12345678901234567890")
    session = MemorySession()

    async def db_dependency():
        yield session

    async def valid_password(self, username, password):
        return True, await self.get_user_by_id(1)

    monkeypatch.setattr(AuthCRUD, "verify_user_password", valid_password)
    monkeypatch.setattr(AuthCRUD, "update_last_login", AsyncMock())
    monkeypatch.setattr(AuthCRUD, "log_login_history", AsyncMock(return_value=True))
    monkeypatch.setattr(middleware, "get_db_async", db_dependency)
    monkeypatch.setattr(middleware.AuthMiddleware, "_log_api_access", AsyncMock())
    app = FastAPI()
    app.add_middleware(middleware.AuthMiddleware)
    app.include_router(router)
    app.dependency_overrides[database.get_db_async] = db_dependency

    @app.get("/api/private")
    async def private(request: Request):
        return {"session_id": request.state.session_id}

    yield app, session
    session.connection.close()


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://isolated")


async def login(client, remember=True):
    result = await client.post("/api/auth/login", json={
        "username": "alpha", "password": "isolated-test-password", "remember_me": remember,
    })
    assert result.status_code == 200
    return result.json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_non_remember_login_stores_session_for_full_access_lifetime(auth_app):
    app, db = auth_app
    async with client_for(app) as client:
        tokens = await login(client, remember=False)
        payload = AuthCRUD(db).verify_token(tokens["access_token"])
        row = db.connection.execute("SELECT * FROM user_sessions").fetchone()
        assert payload["sid"] == row["session_id"]
        assert tokens["refresh_token"] is None
        expiry = datetime.fromisoformat(row["expires_at"]).replace(tzinfo=timezone.utc)
        assert abs(expiry.timestamp() - payload["exp"]) < 2
        assert (expiry - datetime.now(timezone.utc)).total_seconds() > 11.9 * 3600
        assert (await client.get("/api/private", headers=bearer(tokens["access_token"]))).status_code == 200


@pytest.mark.asyncio
async def test_failed_session_storage_never_returns_successful_login(auth_app, monkeypatch):
    app, _ = auth_app
    monkeypatch.setattr(AuthCRUD, "store_user_session", AsyncMock(return_value=False))
    async with client_for(app) as client:
        response = await client.post("/api/auth/login", json={"username": "alpha", "password": "unused"})
    assert response.status_code == 503
    assert "access_token" not in response.json()


@pytest.mark.asyncio
async def test_logout_revokes_actual_session_and_blocks_access_and_refresh(auth_app):
    app, db = auth_app
    async with client_for(app) as client:
        tokens = await login(client)
        response = await client.post("/api/auth/logout", headers=bearer(tokens["access_token"]))
        assert response.status_code == 200
        assert db.connection.execute("SELECT is_active FROM user_sessions").fetchone()[0] == 0
        assert (await client.get("/api/private", headers=bearer(tokens["access_token"]))).status_code == 401
        assert (await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401


@pytest.mark.asyncio
async def test_logout_all_preserves_current_device_and_revokes_other_device(auth_app):
    app, _ = auth_app
    async with client_for(app) as client:
        first, second = await login(client), await login(client)
        assert first["access_token"] != second["access_token"]
        assert first["refresh_token"] != second["refresh_token"]
        assert (await client.post("/api/auth/logout-all", headers=bearer(second["access_token"]))).status_code == 200
        assert (await client.get("/api/private", headers=bearer(first["access_token"]))).status_code == 401
        assert (await client.get("/api/private", headers=bearer(second["access_token"]))).status_code == 200
        assert (await client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})).status_code == 401
        assert (await client.post("/api/auth/refresh", json={"refresh_token": second["refresh_token"]})).status_code == 200


@pytest.mark.asyncio
async def test_refresh_persists_new_access_token_and_binds_existing_session(auth_app):
    app, db = auth_app
    async with client_for(app) as client:
        original = await login(client)
        response = await client.post("/api/auth/refresh", json={"refresh_token": original["refresh_token"]})
        assert response.status_code == 200
        refreshed = response.json()
        old_payload = AuthCRUD(db).verify_token(original["access_token"])
        new_payload = AuthCRUD(db).verify_token(refreshed["access_token"])
        assert old_payload["sid"] == new_payload["sid"]
        assert original["access_token"] != refreshed["access_token"]
        assert db.connection.execute("SELECT jwt_token FROM user_sessions").fetchone()[0] == refreshed["access_token"]
        # Requests already issued with the earlier signed token retain their own expiry.
        for token in (original["access_token"], refreshed["access_token"]):
            assert (await client.get("/api/private", headers=bearer(token))).status_code == 200


@pytest.mark.asyncio
async def test_legacy_tokens_without_sid_are_resolved_from_existing_records(auth_app):
    app, db = auth_app
    crud = AuthCRUD(db)
    access = crud.create_access_token(1, "alpha")
    refresh = crud.create_refresh_token(1, "alpha")
    assert "sid" not in crud.verify_token(access)
    await crud.store_user_session(1, access, refresh, "legacy-session", None, None, "web", datetime.utcnow() + timedelta(days=7))
    async with client_for(app) as client:
        assert (await client.get("/api/private", headers=bearer(access))).status_code == 200
        response = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert response.status_code == 200
        updated = response.json()["access_token"]
        assert crud.verify_token(updated)["sid"] == "legacy-session"
        assert (await client.post("/api/auth/logout", headers=bearer(updated))).status_code == 200
        assert (await client.post("/api/auth/refresh", json={"refresh_token": refresh})).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidate_sql", [
    "UPDATE user_sessions SET expires_at = '2000-01-01'",
    "UPDATE user_sessions SET revoked_at = CURRENT_TIMESTAMP",
    "UPDATE users SET is_active = 0",
])
async def test_invalid_session_or_disabled_user_cannot_access_or_refresh(auth_app, invalidate_sql):
    app, db = auth_app
    async with client_for(app) as client:
        tokens = await login(client)
        db.connection.execute(invalidate_sql)
        db.connection.commit()
        assert (await client.get("/api/private", headers=bearer(tokens["access_token"]))).status_code == 401
        assert (await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh_route", [False, True])
async def test_database_outage_is_retryable_and_recovers_without_new_login(auth_app, monkeypatch, refresh_route):
    app, db = auth_app
    async with client_for(app) as client:
        tokens = await login(client)
        original_execute = db.execute
        monkeypatch.setattr(db, "execute", AsyncMock(side_effect=RuntimeError("isolated database outage")))
        if refresh_route:
            response = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        else:
            response = await client.get("/api/private", headers=bearer(tokens["access_token"]))
        assert response.status_code == 503
        monkeypatch.setattr(db, "execute", original_execute)
        assert (await client.get("/api/private", headers=bearer(tokens["access_token"]))).status_code == 200
        assert (await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 200


@pytest.mark.asyncio
async def test_refresh_update_failure_does_not_invalidate_existing_session(auth_app, monkeypatch):
    app, _ = auth_app
    monkeypatch.setattr(AuthCRUD, "update_session_access_token", AsyncMock(side_effect=RuntimeError("isolated write failure")))
    async with client_for(app) as client:
        tokens = await login(client)
        response = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert response.status_code == 503
        assert (await client.get("/api/private", headers=bearer(tokens["access_token"]))).status_code == 200


@pytest.mark.asyncio
async def test_refresh_type_and_malformed_subject_are_rejected(auth_app):
    app, db = auth_app
    async with client_for(app) as client:
        tokens = await login(client)
        assert (await client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]})).status_code == 401
        malformed = jwt.encode({"type": "refresh", "sub": "bad-subject", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                               auth_crud.get_jwt_secret(), algorithm="HS256")
        assert (await client.post("/api/auth/refresh", json={"refresh_token": malformed})).status_code == 401
        assert (await client.get("/api/private", headers=bearer(tokens["refresh_token"]))).status_code == 401


@pytest.mark.asyncio
async def test_session_cannot_be_reused_with_another_signed_user_id(auth_app):
    app, db = auth_app
    async with client_for(app) as client:
        tokens = await login(client)
        session_id = AuthCRUD(db).verify_token(tokens["access_token"])["sid"]
        other_user = AuthCRUD(db).create_access_token(2, "different-user", session_id=session_id)
        assert (await client.get("/api/private", headers=bearer(other_user))).status_code == 401


@pytest.mark.asyncio
async def test_password_database_error_is_not_reported_as_wrong_password(monkeypatch):
    failing_db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("isolated lookup failure")))
    with pytest.raises(RuntimeError, match="isolated lookup failure"):
        await AuthCRUD(failing_db).verify_user_password("alpha", "unused")


def test_async_database_url_preserves_reserved_characters_without_connecting(monkeypatch):
    config = SimpleNamespace(user="test@user", password="isolated@password:/#?", host="localhost",
                             port=3306, database="test-grid", charset="utf8mb4", pool_size=2)
    captured = {}

    def capture_engine(url, **kwargs):
        captured["url"] = url
        return object()

    monkeypatch.setattr(database, "DatabaseConfig", lambda: config)
    monkeypatch.setattr(database, "_async_engine", None)
    monkeypatch.setattr(database, "_AsyncSessionLocal", None)
    monkeypatch.setattr(database, "create_async_engine", capture_engine)
    monkeypatch.setattr(database, "async_sessionmaker", lambda **kwargs: object())
    database._init_async_engine()
    assert captured["url"].username == config.user
    assert captured["url"].password == config.password
    assert captured["url"].host == config.host
    assert captured["url"].database == config.database
