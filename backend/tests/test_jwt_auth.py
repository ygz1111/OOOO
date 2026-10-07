# -*- coding: utf-8 -*-
"""认证与令牌测试：密码哈希、JWT 签发/校验、token type 约束、密钥来源。"""
import os
import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jwt
from realtime_api.crud.auth_crud import (
    AuthCRUD,
    hash_password,
    verify_password,
    JWT_ALGORITHM,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        h = hash_password("Test@12345")
        assert h.startswith("$2")
        assert verify_password("Test@12345", h) is True

    def test_wrong_password_rejected(self):
        h = hash_password("Test@12345")
        assert verify_password("wrong-pass", h) is False

    def test_hash_is_salted(self):
        assert hash_password("same-password") != hash_password("same-password")


class TestTokenLifecycle:
    def _crud(self):
        return AuthCRUD(db_session=None)  # create_*_token / verify_token 不依赖 db

    def test_access_token_roundtrip(self):
        crud = self._crud()
        token = crud.create_access_token(1, "admin")
        payload = crud.verify_token(token)
        assert payload is not None
        assert payload["type"] == "access"
        assert int(payload["sub"]) == 1
        assert payload["username"] == "admin"

    def test_refresh_token_roundtrip(self):
        crud = self._crud()
        token = crud.create_refresh_token(1, "admin")
        payload = crud.verify_token(token)
        assert payload is not None
        assert payload["type"] == "refresh"

    def test_verify_token_rejects_unknown_type(self):
        crud = self._crud()
        # 手工构造一个 type 非法但签名有效的 token
        import datetime
        from realtime_api.config_manager import get_jwt_secret
        bad = jwt.encode(
            {"sub": "1", "username": "u", "type": "evil",
             "exp": datetime.datetime.now(datetime.timezone.utc)
             + datetime.timedelta(minutes=5)},
            get_jwt_secret(), algorithm=JWT_ALGORITHM,
        )
        assert crud.verify_token(bad) is None

    def test_expired_token_rejected(self):
        import datetime
        crud = self._crud()
        expired = jwt.encode(
            {"sub": "1", "username": "u", "type": "access",
             "exp": datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(minutes=5)},
            "any-secret", algorithm="HS256",
        )
        # 签名不符也会被拒（这里同时验证错误签名）
        assert crud.verify_token(expired) is None


class TestJwtSecretSource:
    def test_environment_secret_has_runtime_priority(self, monkeypatch):
        """即使配置单例已初始化，运行时环境密钥也必须优先。"""
        from realtime_api.config_manager import get_jwt_secret

        expected = "runtime-secret-that-is-long-enough-for-hs256-tests-123456"
        monkeypatch.setenv("AUTH_JWT_SECRET_KEY", expected)
        assert get_jwt_secret() == expected

    def test_secret_not_insecure_default(self):
        """密钥必须来自环境变量配置，不能回退到不安全的默认值"""
        from realtime_api.config_manager import get_jwt_secret
        secret = get_jwt_secret()
        assert secret
        assert len(secret) >= 16
        assert secret not in (
            "your-secret-key", "default-secret-key",
            "your-secret-key-change-in-production",
        )

    def test_direct_config_import_loads_project_environment(self):
        """绕过 app.py 直接导入配置时也必须读到项目根目录 .env。"""
        backend = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.pop("AUTH_JWT_SECRET_KEY", None)
        command = (
            "from realtime_api.config_manager import get_jwt_secret; "
            "s=get_jwt_secret(); "
            "print(len(s)>=32 and s not in "
            "{'your-secret-key','default-secret-key',"
            "'your-secret-key-change-in-production'})"
        )
        result = subprocess.run(
            [sys.executable, "-c", command],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        assert result.stdout.strip().splitlines()[-1] == "True"
