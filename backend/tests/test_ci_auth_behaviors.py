"""Authentication failure, permission, and session contracts without a live database.

The database boundary is mocked; signed JWTs, Pydantic responses, authorization
decisions, and transaction arguments are exercised by the real application code.
"""
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import jwt
import pytest
from fastapi import HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials

from realtime_api.auth import dependencies as deps
from realtime_api.auth import middleware as middleware_module
from realtime_api.crud import auth_crud as crud_module
from realtime_api.crud.auth_crud import AuthCRUD
from realtime_api.routers import auth as routes
from realtime_api.schemas.auth import (
    APIAccessLogCreate, LoginRequest, OperationLogCreate, PasswordChange,
    RefreshTokenRequest, RoleCreate, UserCreate, UserResponse, UserRoleAssign,
    UserUpdate,
)


SECRET = "ci-test-secret-with-at-least-thirty-two-characters"
NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)


def request(path="/api/auth/me", method="GET", headers=None, body=b""):
    scope = {
        "type": "http", "method": method, "path": path,
        "query_string": b"", "headers": [
            (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
        ], "scheme": "http", "server": ("test", 80),
        "client": ("127.0.0.1", 4321),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive=receive)


def result(row=None, rows=None, scalar=None, rowcount=1, lastrowid=7):
    return SimpleNamespace(
        fetchone=Mock(return_value=row), fetchall=Mock(return_value=rows or []),
        scalar=Mock(return_value=scalar), rowcount=rowcount, lastrowid=lastrowid,
    )


@pytest.fixture
def db():
    return SimpleNamespace(
        execute=AsyncMock(return_value=result()), commit=AsyncMock(),
        rollback=AsyncMock(), close=AsyncMock(),
    )


@pytest.fixture
def user():
    return UserResponse(
        id=7, username="analyst", email="analyst@example.com", is_active=True,
        is_verified=True, created_at=NOW, updated_at=NOW,
    )


@pytest.fixture
def signing_secret(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET_KEY", SECRET)
    monkeypatch.setattr(crud_module, "get_jwt_secret", lambda: SECRET)


def token(**overrides):
    payload = {"sub": "7", "username": "analyst", "type": "access",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    payload.update(overrides)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def fake_crud(monkeypatch, target, **values):
    crud = SimpleNamespace(**values)
    factory = Mock(return_value=crud)
    monkeypatch.setattr(target, "AuthCRUD", factory)
    return crud


@pytest.mark.asyncio
@pytest.mark.parametrize("method,key", [("get_user_by_id", 7), ("get_user_by_username", "analyst")])
@pytest.mark.parametrize("exists", [True, False])
async def test_user_lookup_requires_active_user_and_returns_valid_schema(db, user, method, key, exists):
    db.execute.return_value = result(user if exists else None)
    actual = await getattr(AuthCRUD(db), method)(key)
    assert actual == (user if exists else None)
    sql, params = db.execute.call_args.args
    assert "is_active = TRUE" in str(sql)
    assert key in params.values()


@pytest.mark.asyncio
async def test_create_user_hashes_password_and_commits_before_readback(monkeypatch, db, user):
    created = UserCreate(username="Analyst", email="analyst@example.com", password="Password123")
    crud = AuthCRUD(db)
    crud._check_user_exists = AsyncMock(return_value=False)
    crud.get_user_by_id = AsyncMock(return_value=user)
    monkeypatch.setattr(crud_module, "hash_password", Mock(return_value="bcrypt-hash"))
    assert await crud.create_user(created, created_by=1) == user
    params = db.execute.call_args.args[1]
    assert params["username"] == "analyst"
    assert params["hashed_password"] == "bcrypt-hash"
    assert params["created_by"] == 1
    assert "Password123" not in params.values()
    db.commit.assert_awaited_once()
    crud.get_user_by_id.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_create_user_duplicate_is_not_inserted(db):
    crud = AuthCRUD(db)
    crud._check_user_exists = AsyncMock(return_value=True)
    with pytest.raises(ValueError, match="已存在"):
        await crud.create_user(UserCreate(username="user", email="u@example.com", password="Password123"))
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("exists,valid", [(False, False), (True, False), (True, True)])
async def test_password_verification_counts_only_existing_user_failures(monkeypatch, db, user, exists, valid):
    row = SimpleNamespace(**user.model_dump(), hashed_password="stored-hash")
    db.execute.return_value = result(row if exists else None)
    monkeypatch.setattr(crud_module, "verify_password", Mock(return_value=valid))
    crud = AuthCRUD(db)
    crud._update_failed_login_attempts = AsyncMock()
    assert await crud.verify_user_password("analyst", "password") == ((True, user) if valid else (False, None))
    if exists and not valid:
        crud._update_failed_login_attempts.assert_awaited_once_with(7)
    else:
        crud._update_failed_login_attempts.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_update_user_changes_only_explicit_fields(db, user, empty):
    crud = AuthCRUD(db)
    crud.get_user_by_id = AsyncMock(return_value=user)
    data = UserUpdate() if empty else UserUpdate(
        email="new@example.com", full_name="New Analyst", department="Operations",
        phone="12345", is_active=False,
    )
    assert await crud.update_user(7, data, updated_by=1) == user
    if empty:
        db.execute.assert_not_awaited()
        db.commit.assert_not_awaited()
    else:
        params = db.execute.call_args.args[1]
        assert params == {**data.model_dump(exclude_none=True), "updated_by": 1, "user_id": 7}
        assert "hashed_password" not in str(db.execute.call_args.args[0])
        db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("exists,old_valid", [(False, False), (True, False), (True, True)])
async def test_password_change_requires_current_password(monkeypatch, db, user, exists, old_valid):
    crud = AuthCRUD(db)
    crud.get_user_by_id = AsyncMock(return_value=user if exists else None)
    db.execute.return_value = result(SimpleNamespace(hashed_password="old-hash"))
    monkeypatch.setattr(crud_module, "verify_password", Mock(return_value=old_valid))
    monkeypatch.setattr(crud_module, "hash_password", Mock(return_value="new-hash"))
    assert await crud.change_password(7, PasswordChange(old_password="old", new_password="Password123")) is (exists and old_valid)
    if exists and old_valid:
        assert db.execute.call_args.args[1] == {"password_hash": "new-hash", "user_id": 7}
        db.commit.assert_awaited_once()
    else:
        db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,field", [("get_user_permissions", "p.code"), ("get_user_roles", "r.name")])
async def test_permission_queries_resolve_rows_without_granting_on_failure(db, method, field):
    db.execute.return_value = result(rows=[("read",), ("write",)])
    assert await getattr(AuthCRUD(db), method)(7) == ["read", "write"]
    sql, params = db.execute.call_args.args
    assert field in str(sql) and params == {"user_id": 7}
    db.execute.side_effect = RuntimeError("database unavailable")
    assert await getattr(AuthCRUD(db), method)(7) == []


@pytest.mark.asyncio
async def test_role_assignment_preserves_expiry_and_grant_actor(db):
    assignment = UserRoleAssign(user_id=7, role_id=2, expires_at=NOW, reason="approved")
    assert await AuthCRUD(db).assign_user_role(assignment, 1) is True
    assert db.execute.call_args.args[1] == {
        "user_id": 7, "role_id": 2, "granted_by": 1, "reason": "approved", "expires_at": NOW,
    }
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_role_rejects_duplicate_without_inserting(db):
    db.execute.return_value = result(SimpleNamespace(id=2))
    with pytest.raises(ValueError, match="已存在"):
        await AuthCRUD(db).create_role(RoleCreate(name="operator"))
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_get_roles_builds_response_rows_and_empty_on_failure(db):
    row = SimpleNamespace(id=2, name="operator", description="operations", level=2,
                          is_system_role=False, created_at=NOW, updated_at=NOW)
    db.execute.return_value = result(rows=[row])
    roles = await AuthCRUD(db).get_roles()
    assert len(roles) == 1 and roles[0].name == "operator" and roles[0].level == 2
    db.execute.side_effect = RuntimeError("offline")
    assert await AuthCRUD(db).get_roles() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args,raises", [
    ("get_user_by_id", (7,), True), ("get_user_by_username", ("user",), True),
    ("verify_user_password", ("user", "bad"), True),
    ("update_user", (7, UserUpdate(email="x@example.com")), True),
    ("create_role", (RoleCreate(name="operator"),), True),
    ("assign_user_role", (UserRoleAssign(user_id=7, role_id=2), 1), False),
    ("remove_user_role", (7, 2), False),
    ("_check_user_exists", ("user", "x@example.com"), False),
])
async def test_auth_crud_database_failure_is_not_a_success(db, method, args, raises):
    db.execute.side_effect = RuntimeError("isolated database failure")
    if raises:
        with pytest.raises(RuntimeError, match="isolated database failure"):
            await getattr(AuthCRUD(db), method)(*args)
    else:
        assert await getattr(AuthCRUD(db), method)(*args) is False
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_password_change_database_failure_is_reported(monkeypatch, db, user):
    crud = AuthCRUD(db)
    crud.get_user_by_id = AsyncMock(return_value=user)
    db.execute.side_effect = RuntimeError("offline")
    assert await crud.change_password(7, PasswordChange(old_password="old", new_password="Password123")) is False
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["_update_failed_login_attempts", "update_last_login"])
async def test_login_counters_are_parameterized_and_committed(db, method):
    await getattr(AuthCRUD(db), method)(7)
    assert all(call.args[1] == {"user_id": 7} for call in db.execute.await_args_list)
    sql = " ".join(str(call.args[0]) for call in db.execute.await_args_list)
    if method == "_update_failed_login_attempts":
        assert "failed_login_attempts + 1" in sql and "failed_login_attempts >= 5" in sql
        assert db.execute.await_count == 2
    else:
        assert "failed_login_attempts = 0" in sql and "last_login_at = NOW()" in sql
    db.commit.assert_awaited_once()
    db.execute.side_effect = RuntimeError("counter storage offline")
    await getattr(AuthCRUD(db), method)(7)
    assert db.commit.await_count == 1


@pytest.mark.parametrize("kind", ["access", "refresh"])
def test_token_custom_lifetime_and_session_binding(signing_secret, kind):
    crud = AuthCRUD(None)
    issued = getattr(crud, f"create_{kind}_token")(7, "analyst", timedelta(minutes=3), "session-uuid")
    payload = crud.verify_token(issued)
    assert payload["type"] == kind and payload["sid"] == "session-uuid"
    assert 179 <= payload["exp"] - payload["iat"] <= 181
    assert payload["jti"]


def test_expired_correctly_signed_token_and_malformed_password_rejected(signing_secret):
    assert AuthCRUD(None).verify_token(token(exp=datetime.now(timezone.utc) - timedelta(seconds=1))) is None
    assert crud_module.verify_password("password", "not-a-bcrypt-hash") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_session_storage_commits_or_rolls_back_atomically(db, fails):
    if fails:
        db.execute.side_effect = RuntimeError("offline")
    saved = await AuthCRUD(db).store_user_session(7, "access", "refresh", "session", "ip", "agent", "web", NOW)
    assert saved is (not fails)
    if fails:
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()
    else:
        db.commit.assert_awaited_once()
        assert db.execute.call_args.args[1]["session_id"] == "session"
        assert db.execute.call_args.args[1]["expires_at"] == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,sid,condition", [
    ("access", None, "s.jwt_token = :token"),
    ("access", "session", "s.session_id = :session_id"),
    ("refresh", "session", "s.refresh_token = :token"),
])
async def test_active_session_checks_token_type_user_expiry_and_revocation(db, kind, sid, condition):
    row = SimpleNamespace(session_id="session", username="analyst")
    db.execute.return_value = result(row)
    assert await AuthCRUD(db).get_active_session("jwt", 7, kind, sid) is row
    sql, params = db.execute.call_args.args
    assert condition in str(sql)
    assert "revoked_at IS NULL" in str(sql) and "expires_at > UTC_TIMESTAMP()" in str(sql)
    assert "u.is_active = TRUE" in str(sql)
    assert params == {"token": "jwt", "user_id": 7, "session_id": sid}


@pytest.mark.asyncio
async def test_active_session_rejects_unknown_token_kind_before_database(db):
    with pytest.raises(ValueError, match="Unsupported"):
        await AuthCRUD(db).get_active_session("jwt", 7, "other")
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("rowcount", [0, 1])
async def test_session_token_update_reports_race_with_revocation(db, rowcount):
    db.execute.return_value = result(rowcount=rowcount)
    assert await AuthCRUD(db).update_session_access_token("session", 7, "new-jwt") is (rowcount > 0)
    assert db.execute.call_args.args[1] == {"session_id": "session", "user_id": 7, "token": "new-jwt"}
    db.commit.assert_awaited_once()
    db.execute.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError, match="offline"):
        await AuthCRUD(db).update_session_access_token("session", 7, "new-jwt")
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("sid", [None, "current-session"])
async def test_revoke_all_sessions_can_preserve_current_device(db, sid):
    assert await AuthCRUD(db).revoke_all_user_sessions(7, sid) is True
    sql, params = db.execute.call_args.args
    assert params["user_id"] == 7
    if sid:
        assert "session_id != :except_session_id" in str(sql) and params["except_session_id"] == sid
    else:
        assert params == {"user_id": 7}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [("revoke_session", ("session",)), ("revoke_all_user_sessions", (7,))])
async def test_revoke_session_storage_failure_rolls_back(db, method, args):
    db.execute.side_effect = RuntimeError("offline")
    assert await getattr(AuthCRUD(db), method)(*args) is False
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("rowcount", [0, 1])
async def test_revoke_session_reports_whether_session_existed(db, rowcount):
    db.execute.return_value = result(rowcount=rowcount)
    assert await AuthCRUD(db).revoke_session("session") is (rowcount > 0)
    assert db.execute.call_args.args[1] == {"session_id": "session"}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,data", [
    ("log_api_access", APIAccessLogCreate(method="GET", url="/api", client_ip="127.0.0.1", status_code=503, response_time_ms=20)),
    ("log_operation", OperationLogCreate(operation_type="UPDATE", resource_type="USER", description="changed", is_success=False, error_message="failed")),
])
async def test_audit_persistence_uses_validated_fields_and_reports_failure(db, method, data):
    assert await getattr(AuthCRUD(db), method)(data) is True
    assert db.execute.call_args.args[1] == data.model_dump()
    db.commit.assert_awaited_once()
    db.execute.side_effect = RuntimeError("audit database offline")
    assert await getattr(AuthCRUD(db), method)(data) is False


@pytest.mark.asyncio
async def test_login_history_records_failed_attempt_without_user(db):
    assert await AuthCRUD(db).log_login_history(None, "ip", "agent", "password", False, "wrong credentials") is True
    params = db.execute.call_args.args[1]
    assert params["user_id"] is None and params["is_success"] is False
    assert params["failure_reason"] == "wrong credentials"
    db.commit.assert_awaited_once()
    db.execute.side_effect = RuntimeError("offline")
    assert await AuthCRUD(db).log_login_history(7, "ip", "agent", "password", True) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,expected", [
    ({"type": "refresh"}, "类型错误"), ({"sub": ""}, "缺少必要信息"),
    ({"username": ""}, "缺少必要信息"), ({"sub": "not-numeric"}, "认证失败"),
])
async def test_current_user_dependency_rejects_invalid_claims(monkeypatch, db, signing_secret, payload, expected):
    factory = Mock()
    monkeypatch.setattr(deps, "AuthCRUD", factory)
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user()(request(), HTTPAuthorizationCredentials(scheme="Bearer", credentials=token(**payload)), db)
    assert exc.value.status_code == 401 and expected in exc.value.detail
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}
    if payload.get("sub") != "not-numeric":
        factory.assert_not_called()


@pytest.mark.asyncio
async def test_current_user_dependency_expired_token_does_not_query_db(monkeypatch, db, signing_secret):
    factory = Mock()
    monkeypatch.setattr(deps, "AuthCRUD", factory)
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user()(request(), HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid-jwt"), db)
    assert exc.value.status_code == 401 and exc.value.detail == "无效的认证令牌"
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "missing", "failure"])
async def test_current_user_dependency_resolves_real_user_or_rejects(monkeypatch, db, user, signing_secret, case):
    reader = AsyncMock(return_value=user if case == "valid" else None)
    if case == "failure":
        reader.side_effect = RuntimeError("database unavailable")
    fake_crud(monkeypatch, deps, get_user_by_id=reader)
    dep = deps.get_current_user()
    args = (request(), HTTPAuthorizationCredentials(scheme="Bearer", credentials=token()), db)
    if case == "valid":
        assert await dep(*args) is user
    else:
        with pytest.raises(HTTPException) as exc:
            await dep(*args)
        assert exc.value.status_code == 401
        assert exc.value.detail == ("认证失败" if case == "failure" else "用户不存在或已被禁用")
    reader.assert_awaited_once_with(7)


def test_disabled_user_cannot_be_active_dependency(user):
    assert deps.get_current_active_user(user) is user
    with pytest.raises(HTTPException) as exc:
        deps.get_current_active_user(user.model_copy(update={"is_active": False}))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("admin,allowed,failure", [(True, False, False), (False, True, False), (False, False, False), (False, False, True)])
async def test_permission_check_admin_allow_deny_and_infrastructure_failure(monkeypatch, db, user, admin, allowed, failure):
    crud = fake_crud(monkeypatch, deps, get_user_roles=AsyncMock(return_value=["系统管理员"] if admin else ["普通用户"]),
                     get_user_permissions=AsyncMock(return_value=["data:read"] if allowed else []))
    if failure:
        crud.get_user_roles.side_effect = RuntimeError("offline")
    check = deps.check_permission("data:read", "读取数据需要权限")
    if (admin or allowed) and not failure:
        assert await check(request(), user, db) is user
    else:
        with pytest.raises(HTTPException) as exc:
            await check(request(), user, db)
        assert exc.value.status_code == (500 if failure else 403)
        assert exc.value.detail == ("权限验证失败" if failure else "读取数据需要权限")
    if admin:
        crud.get_user_permissions.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("all_required,granted,admin,expected", [
    (True, ["read", "write"], False, 200), (True, ["read"], False, 403),
    (False, ["write"], False, 200), (False, [], False, 403),
    (True, [], True, 200), (False, None, False, 500),
])
async def test_rbac_any_and_all_permissions(monkeypatch, db, user, all_required, granted, admin, expected):
    crud = fake_crud(monkeypatch, deps, get_user_roles=AsyncMock(return_value=["超级管理员"] if admin else []),
                     get_user_permissions=AsyncMock(return_value=granted))
    if granted is None:
        crud.get_user_permissions.side_effect = RuntimeError("offline")
    check = deps.rbac_required("read", "write", require_all=all_required)
    if expected == 200:
        assert await check(request(), user, db) is user
    else:
        with pytest.raises(HTTPException) as exc:
            await check(request(), user, db)
        assert exc.value.status_code == expected


@pytest.mark.asyncio
async def test_permission_denial_uses_default_message(monkeypatch, db, user):
    fake_crud(monkeypatch, deps, get_user_roles=AsyncMock(return_value=[]), get_user_permissions=AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as exc:
        await deps.check_permission("read")(request(), user, db)
    assert exc.value.detail == "缺少权限: read"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,resource_failure", [(False, False), (True, False), (False, True)])
async def test_operation_audit_records_success_failure_without_changing_business(monkeypatch, db, user, failure, resource_failure):
    callbacks = []
    monkeypatch.setattr(deps, "fire_and_forget", lambda fn, name: callbacks.append((fn, name)))
    recorder = AsyncMock()
    fake_crud(monkeypatch, deps, log_operation=recorder)

    async def get_db():
        yield db

    monkeypatch.setattr(deps, "get_db_async", get_db)
    req = request(method="POST", headers={"User-Agent": "test-agent"})
    req.state.session_id, req.state.request_id, req.state.client_ip = "session", "request-id", "ip"

    def resource(value, *args, **kwargs):
        if resource_failure:
            raise ValueError("resource lookup failed")
        return 42

    @deps.log_operation("UPDATE", "USER", "{user} changed {resource_id}", resource)
    async def business(req, current_user):
        if failure:
            raise RuntimeError("business failed")
        return {"updated": True}

    if failure:
        with pytest.raises(RuntimeError, match="business failed"):
            await business(req, current_user=user)
    else:
        assert await business(req, current_user=user) == {"updated": True}
    assert len(callbacks) == 1 and callbacks[0][1] == "operation_log"
    await callbacks[0][0]()
    log = recorder.await_args.args[0]
    assert log.user_id == 7 and log.session_id == "session"
    assert log.is_success is (not failure)
    assert log.error_message == ("business failed" if failure else None)
    assert log.resource_id == (None if resource_failure else "42")
    assert log.details["request_id"] == "request-id" and log.details["method"] == "POST"
    db.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_operation_audit_unavailable_storage_does_not_fail_business(monkeypatch, user):
    callbacks = []
    monkeypatch.setattr(deps, "fire_and_forget", lambda fn, name: callbacks.append(fn))

    async def unavailable():
        raise RuntimeError("audit storage offline")
        yield  # defines an asynchronous dependency generator

    monkeypatch.setattr(deps, "get_db_async", unavailable)

    @deps.log_operation("READ", "DATA", "read")
    async def business(req, current_user):
        return "ok"

    assert await business(request(), current_user=user) == "ok"
    await callbacks[0]()


@pytest.mark.asyncio
async def test_audit_without_context_and_invalid_template_preserve_business(monkeypatch, user):
    scheduler = Mock()
    monkeypatch.setattr(deps, "fire_and_forget", scheduler)

    @deps.log_operation("READ", "DATA", "{unknown_placeholder}")
    async def business(*args, **kwargs):
        return 1

    assert await business() == 1
    assert await business(request(), current_user=user) == 1
    scheduler.assert_not_called()


@pytest.mark.asyncio
async def test_sensitive_audit_logs_actor_and_endpoint(monkeypatch, user):
    logger = Mock()
    monkeypatch.setattr(deps, "logger", logger)

    @deps.audit_sensitive_operation("password change", "USER")
    async def business(*args, **kwargs):
        return "done"

    req = request(method="POST")
    assert await business(req, current_user=user) == "done"
    extra = logger.info.call_args.kwargs["extra"]
    assert extra["user_id"] == 7 and extra["endpoint"] == "POST /api/auth/me"
    assert await business() == "done"
    logger.info.assert_called_once()


@pytest.mark.asyncio
async def test_permission_and_role_tools_run_async_queries(monkeypatch, db):
    crud = fake_crud(monkeypatch, deps, get_user_permissions=AsyncMock(return_value=["read"]), get_user_roles=AsyncMock(return_value=["普通用户"]))
    assert await deps.get_user_permissions(7, db) == ["read"]
    assert await deps.get_user_roles(7, db) == ["普通用户"]
    crud.get_user_permissions.assert_awaited_once_with(7)
    crud.get_user_roles.assert_awaited_once_with(7)


@pytest.mark.asyncio
@pytest.mark.parametrize("remember", [False, True])
async def test_login_generates_tokens_bound_to_persisted_session(monkeypatch, db, user, remember):
    crud = fake_crud(monkeypatch, routes,
        verify_user_password=AsyncMock(return_value=(True, user)), update_last_login=AsyncMock(),
        create_access_token=Mock(return_value="access"), create_refresh_token=Mock(return_value="refresh"),
        store_user_session=AsyncMock(return_value=True), log_login_history=AsyncMock())
    answer = await routes.login(LoginRequest(username="analyst", password="Password123", remember_me=remember), request(), db)
    assert answer.user == user and answer.access_token == "access" and answer.expires_in == 43200
    assert answer.refresh_token == ("refresh" if remember else None)
    stored = crud.store_user_session.await_args.kwargs
    assert stored["session_id"] == crud.create_access_token.call_args.kwargs["session_id"]
    assert stored["user_id"] == 7 and stored["platform"] == "web"
    remaining = stored["expires_at"] - datetime.utcnow()
    if remember:
        assert timedelta(days=6) < remaining < timedelta(days=8)
    else:
        assert timedelta(hours=11) < remaining < timedelta(hours=13)
    assert crud.log_login_history.await_args.kwargs["is_success"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("case,code", [("invalid", 401), ("disabled", 403), ("store", 503), ("failure", 500)])
async def test_login_failures_do_not_issue_success_response(monkeypatch, db, user, case, code):
    active_user = user.model_copy(update={"is_active": False}) if case == "disabled" else user
    crud = fake_crud(monkeypatch, routes,
        verify_user_password=AsyncMock(return_value=(case != "invalid", None if case == "invalid" else active_user)),
        update_last_login=AsyncMock(), create_access_token=Mock(return_value="access"),
        create_refresh_token=Mock(return_value="refresh"), store_user_session=AsyncMock(return_value=case != "store"),
        log_login_history=AsyncMock())
    if case == "failure":
        crud.verify_user_password.side_effect = RuntimeError("database offline")
    with pytest.raises(HTTPException) as exc:
        await routes.login(LoginRequest(username="analyst", password="bad"), request(), db)
    assert exc.value.status_code == code
    if case == "invalid":
        assert crud.log_login_history.await_args.kwargs["is_success"] is False
        assert crud.log_login_history.await_args.kwargs["user_id"] is None
    if case in ("invalid", "disabled", "failure"):
        crud.store_user_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role_present", [False, True])
async def test_registration_assigns_only_available_default_role(monkeypatch, db, user, role_present):
    crud = fake_crud(monkeypatch, routes, create_user=AsyncMock(return_value=user), assign_user_role=AsyncMock())
    db.execute.return_value = result(SimpleNamespace(id=2) if role_present else None)
    data = UserCreate(username="analyst", email="a@example.com", password="Password123")
    assert await routes.register_user(data, request(), db) is user
    crud.create_user.assert_awaited_once_with(data)
    if role_present:
        assignment, actor = crud.assign_user_role.await_args.args
        assert assignment.user_id == 7 and assignment.role_id == 2 and actor == 1
    else:
        crud.assign_user_role.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error,code", [(ValueError("duplicate"), 400), (RuntimeError("offline"), 500)])
async def test_registration_rejects_duplicate_and_database_failure(monkeypatch, db, error, code):
    fake_crud(monkeypatch, routes, create_user=AsyncMock(side_effect=error))
    with pytest.raises(HTTPException) as exc:
        await routes.register_user(UserCreate(username="analyst", email="a@example.com", password="Password123"), request(), db)
    assert exc.value.status_code == code


@pytest.mark.asyncio
@pytest.mark.parametrize("case,code", [
    ("ok", 200), ("invalid", 401), ("access", 401), ("sub", 401), ("revoked", 401),
    ("missing_user", 401), ("disabled", 401), ("update_race", 401), ("failure", 503),
])
async def test_refresh_requires_real_active_session_and_stores_new_access_token(monkeypatch, db, user, case, code):
    payload = None if case == "invalid" else {"sub": "not-an-id" if case == "sub" else "7", "type": "access" if case == "access" else "refresh"}
    crud = fake_crud(monkeypatch, routes,
        verify_token=Mock(return_value=payload),
        get_active_session=AsyncMock(return_value=None if case == "revoked" else SimpleNamespace(session_id="session")),
        get_user_by_id=AsyncMock(return_value=None if case == "missing_user" else user.model_copy(update={"is_active": case != "disabled"})),
        create_access_token=Mock(return_value="new-access"), update_session_access_token=AsyncMock(return_value=case != "update_race"))
    if case == "failure":
        crud.get_active_session.side_effect = RuntimeError("offline")
    body = RefreshTokenRequest(refresh_token="refresh")
    if code == 200:
        answer = await routes.refresh_access_token(body, request(), db)
        assert answer.access_token == "new-access" and answer.refresh_token == "refresh" and answer.user == user
        crud.update_session_access_token.assert_awaited_once_with("session", 7, "new-access")
        crud.create_access_token.assert_called_once_with(7, "analyst", session_id="session")
    else:
        with pytest.raises(HTTPException) as exc:
            await routes.refresh_access_token(body, request(), db)
        assert exc.value.status_code == code
        if case != "update_race":
            crud.update_session_access_token.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,method", [("logout", "revoke_session"), ("logout_all_devices", "revoke_all_user_sessions")])
@pytest.mark.parametrize("case,code", [("ok", 200), ("missing", 401), ("rejected", 503), ("failure", 500)])
async def test_logout_needs_stored_session_and_preserves_other_device_contract(monkeypatch, db, user, endpoint, method, case, code):
    operation = AsyncMock(return_value=case != "rejected")
    if case == "failure":
        operation.side_effect = RuntimeError("offline")
    fake_crud(monkeypatch, routes, **{method: operation})
    req = request()
    if case != "missing":
        req.state.session_id = "session"
    if code == 200:
        assert "message" in await getattr(routes, endpoint)(req, user, db)
        operation.assert_awaited_once_with(*(("session",) if endpoint == "logout" else (7, "session")))
    else:
        with pytest.raises(HTTPException) as exc:
            await getattr(routes, endpoint)(req, user, db)
        assert exc.value.status_code == code
        if case == "missing":
            operation.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case,code", [("ok", 200), ("old_password", 400), ("failure", 500)])
async def test_password_route_does_not_report_success_on_failed_update(monkeypatch, db, user, case, code):
    change = AsyncMock(return_value=case == "ok")
    if case == "failure":
        change.side_effect = RuntimeError("offline")
    fake_crud(monkeypatch, routes, change_password=change)
    data = PasswordChange(old_password="old", new_password="Password123")
    if code == 200:
        assert await routes.change_password(data, request(), user, db) == {"message": "密码修改成功"}
    else:
        with pytest.raises(HTTPException) as exc:
            await routes.change_password(data, request(), user, db)
        assert exc.value.status_code == code
    change.assert_awaited_once_with(7, data)


@pytest.mark.asyncio
@pytest.mark.parametrize("has_stats", [False, True])
async def test_profile_combines_permissions_sessions_and_login_statistics(monkeypatch, db, user, has_stats):
    fake_crud(monkeypatch, routes, get_user_permissions=AsyncMock(return_value=["read"]), get_user_roles=AsyncMock(return_value=["operator"]))
    stats = SimpleNamespace(last_login=NOW, total_logins=4) if has_stats else None
    db.execute.side_effect = [result(scalar=2 if has_stats else None), result(stats)]
    answer = await routes.get_current_user_profile(request(), user, db)
    assert answer.user == user and answer.permissions == ["read"] and answer.roles == ["operator"]
    assert answer.active_sessions == (2 if has_stats else 0)
    assert answer.total_logins == (4 if has_stats else 0) and answer.last_login == (NOW if has_stats else None)
    assert all(call.args[1] == {"username": "analyst"} for call in db.execute.await_args_list)


@pytest.mark.asyncio
async def test_user_session_and_login_history_lists_return_own_rows(db, user):
    session_row = SimpleNamespace(id=1, session_id="session", username="analyst", client_ip="ip", platform="web", last_activity=NOW, expires_at=NOW, idle_minutes=3)
    db.execute.return_value = result(rows=[session_row])
    sessions = await routes.get_user_sessions(request(), user, db)
    assert len(sessions) == 1 and sessions[0].session_id == "session" and sessions[0].idle_minutes == 3
    assert db.execute.call_args.args[1] == {"username": "analyst"}
    assert "expires_at > UTC_TIMESTAMP()" in str(db.execute.call_args.args[0])
    history_row = SimpleNamespace(id=2, login_ip="ip", login_method="password", is_success=False, failure_reason="wrong", created_at=NOW)
    db.execute.return_value = result(rows=[history_row])
    history = await routes.get_login_history(request(), 5, user, db)
    assert len(history) == 1 and history[0].is_success is False and history[0].failure_reason == "wrong"
    assert db.execute.call_args.args[1] == {"user_id": 7, "limit": 5}


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["get_current_user_profile", "get_user_sessions", "get_login_history"])
async def test_profile_and_list_routes_report_database_failure(monkeypatch, db, user, endpoint):
    fake_crud(monkeypatch, routes, get_user_permissions=AsyncMock(side_effect=RuntimeError("offline")))
    db.execute.side_effect = RuntimeError("offline")
    kwargs = {"request": request(), "current_user": user, "db": db}
    with pytest.raises(HTTPException) as exc:
        await getattr(routes, endpoint)(**kwargs)
    assert exc.value.status_code == 500


@pytest.mark.asyncio
@pytest.mark.parametrize("case,code", [("ok", 200), ("missing", 403), ("other_user", 403), ("rejected", 400), ("failure", 500)])
async def test_revoke_specific_session_enforces_ownership(monkeypatch, db, user, case, code):
    revoke = AsyncMock(return_value=case != "rejected")
    fake_crud(monkeypatch, routes, revoke_session=revoke)
    db.execute.return_value = result(None if case == "missing" else SimpleNamespace(user_id=8 if case == "other_user" else 7))
    if case == "failure":
        db.execute.side_effect = RuntimeError("offline")
    if code == 200:
        assert await routes.revoke_session("session", request(), user, db) == {"message": "会话已失效"}
        revoke.assert_awaited_once_with("session")
    else:
        with pytest.raises(HTTPException) as exc:
            await routes.revoke_session("session", request(), user, db)
        assert exc.value.status_code == code
        if case in ("missing", "other_user", "failure"):
            revoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_auth_health_has_real_timestamp():
    answer = await routes.auth_health_check()
    assert answer["status"] == "ok" and answer["service"] == "auth"
    assert isinstance(answer["timestamp"], datetime)


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [None, "Basic token", "Bearer", "Bearer a b", "invalid", "Bearer invalid-jwt"])
async def test_middleware_malformed_authorization_is_rejected_before_database(monkeypatch, signing_secret, authorization):
    factory = Mock()
    monkeypatch.setattr(middleware_module, "get_db_async", factory)
    headers = {"Authorization": authorization} if authorization else {}
    middleware = middleware_module.AuthMiddleware(Mock())
    assert await middleware._authenticate_request(request(headers=headers)) == (None, None)
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("claims", [
    {"type": "refresh"}, {"sub": "0"}, {"sub": "-1"}, {"sub": "bad"},
    {"username": ""}, {"sid": ""}, {"sid": 3},
    {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
])
async def test_middleware_requires_access_token_valid_user_and_optional_uuid(monkeypatch, signing_secret, claims):
    factory = Mock()
    monkeypatch.setattr(middleware_module, "get_db_async", factory)
    middleware = middleware_module.AuthMiddleware(Mock())
    assert await middleware._authenticate_request(request(headers={"Authorization": "Bearer " + token(**claims)})) == (None, None)
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["ok", "revoked", "database_failure"])
async def test_middleware_session_lookup_closes_database_generator(monkeypatch, db, signing_secret, case):
    closed = []

    async def get_db():
        try:
            yield db
        finally:
            closed.append(True)

    monkeypatch.setattr(middleware_module, "get_db_async", get_db)
    lookup = AsyncMock(return_value=None if case == "revoked" else SimpleNamespace(session_id="active-session", username="stored-name"))
    if case == "database_failure":
        lookup.side_effect = RuntimeError("database offline")
    fake_crud(monkeypatch, middleware_module, get_active_session=lookup)
    middleware = middleware_module.AuthMiddleware(Mock())
    issued = token(sid="session")
    req = request(headers={"Authorization": "Bearer " + issued})
    if case == "database_failure":
        with pytest.raises(HTTPException) as exc:
            await middleware._authenticate_request(req)
        assert exc.value.status_code == 503
    else:
        assert await middleware._authenticate_request(req) == ((7, "stored-name") if case == "ok" else (None, None))
        if case == "ok":
            assert req.state.session_id == "active-session"
    lookup.assert_awaited_once_with(issued, 7, "access", "session")
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("case,code", [("ok", 200), ("unauthorized", 401), ("service_failure", 503), ("route_failure", 500)])
async def test_middleware_dispatch_sets_audit_headers_and_distinguishes_auth_failure(monkeypatch, case, code):
    middleware = middleware_module.AuthMiddleware(Mock())
    middleware._authenticate_request = AsyncMock(return_value=(None, None) if case == "unauthorized" else (7, "analyst"))
    middleware._log_api_access = AsyncMock()
    next_handler = AsyncMock(return_value=Response(b"ok"))
    if case == "service_failure":
        middleware._authenticate_request.side_effect = HTTPException(503, "database retry")
    if case == "route_failure":
        next_handler.side_effect = RuntimeError("route failed")
    req = request()
    response = await middleware.dispatch(req, next_handler)
    assert response.status_code == code and req.state.request_id
    if case == "ok":
        assert response.headers["X-User-ID"] == "7" and response.headers["X-Request-ID"] == req.state.request_id
        assert req.state.user_id == 7 and req.state.username == "analyst"
        middleware._log_api_access.assert_awaited_once()
    elif case == "route_failure":
        assert b"INTERNAL_SERVER_ERROR" in response.body
        assert middleware._log_api_access.await_args.args[1] is None
        assert middleware._log_api_access.await_args.args[-1] == "route failed"
    else:
        next_handler.assert_not_awaited()
        middleware._log_api_access.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_dispatch_preserves_response_and_records_access():
    middleware = middleware_module.AuthMiddleware(Mock())
    middleware._authenticate_request = AsyncMock()
    middleware._log_api_access = AsyncMock()
    response = Response("healthy")
    next_handler = AsyncMock(return_value=response)
    assert await middleware.dispatch(request("/health"), next_handler) is response
    middleware._authenticate_request.assert_not_awaited()
    middleware._log_api_access.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("body_fails,write_fails", [(False, False), (True, False), (False, True)])
async def test_api_audit_hashes_request_body_and_closes_session_even_on_storage_failure(monkeypatch, db, body_fails, write_fails):
    callbacks, closed = [], []
    monkeypatch.setattr(middleware_module, "fire_and_forget", lambda fn, name: callbacks.append((fn, name)))
    recorder = AsyncMock(side_effect=RuntimeError("audit offline") if write_fails else None)
    fake_crud(monkeypatch, middleware_module, log_api_access=recorder)

    async def get_db():
        try:
            yield db
        finally:
            closed.append(True)

    monkeypatch.setattr(middleware_module, "get_db_async", get_db)
    middleware = middleware_module.AuthMiddleware(Mock())
    req = request(method="POST", headers={"User-Agent": "audit-test", "X-Forwarded-For": "203.0.113.8, proxy"}, body=b"sensitive-password")
    req.scope["query_string"] = b"date=2026-01-02"
    req.state.session_id = "session"
    if body_fails:
        req.body = AsyncMock(side_effect=RuntimeError("client disconnected"))
    await middleware._log_api_access(req, Response(b"answer", status_code=201), time.time(), 7, "request-id")
    assert len(callbacks) == 1 and callbacks[0][1] == "api_access_log"
    await callbacks[0][0]()
    log = recorder.await_args.args[0]
    assert log.user_id == 7 and log.session_id == "session" and log.client_ip == "203.0.113.8"
    assert log.query_params == "date=2026-01-02" and log.status_code == 201
    if body_fails:
        assert log.request_body_hash is None
    else:
        assert len(log.request_body_hash) == 32
    assert 0 <= log.response_time_ms < 5000
    assert "sensitive-password" not in str(log.model_dump())
    assert closed == [True]


@pytest.mark.asyncio
async def test_api_audit_handles_missing_response_and_unavailable_generator(monkeypatch):
    callbacks = []
    monkeypatch.setattr(middleware_module, "fire_and_forget", lambda fn, name: callbacks.append(fn))

    async def unavailable():
        raise RuntimeError("database offline")
        yield

    monkeypatch.setattr(middleware_module, "get_db_async", unavailable)
    middleware = middleware_module.AuthMiddleware(Mock())
    await middleware._log_api_access(request(), None, time.time(), 7, "request-id", "route failed")
    assert len(callbacks) == 1
    await callbacks[0]()
    scheduler = Mock(side_effect=RuntimeError("background shutdown"))
    monkeypatch.setattr(middleware_module, "fire_and_forget", scheduler)
    await middleware._log_api_access(request(), None, time.time(), 7, "request-id")
    scheduler.assert_called_once()


@pytest.mark.parametrize("headers,client,expected", [
    ({"X-Forwarded-For": "203.0.113.4, 127.0.0.1", "X-Real-IP": "other"}, True, "203.0.113.4"),
    ({"X-Real-IP": "203.0.113.5"}, True, "203.0.113.5"),
    ({}, True, "127.0.0.1"), ({}, False, "unknown"),
])
def test_audit_client_ip_resolution(headers, client, expected):
    req = request(headers=headers)
    if not client:
        req.scope["client"] = None
    assert middleware_module.AuthMiddleware(Mock())._get_client_ip(req) == expected
