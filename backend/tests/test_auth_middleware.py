# -*- coding: utf-8 -*-
"""认证中间件白名单逻辑测试：修复 '/' 前缀全放行漏洞后的行为。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.auth.middleware import AuthMiddleware


def _make_middleware():
    """构造仅用于测试白名单逻辑的实例（不触发任何网络/DB）"""
    mw = AuthMiddleware.__new__(AuthMiddleware)
    mw.exclude_paths = [
        '/docs', '/redoc', '/openapi.json', '/', '/health', '/api/health',
        '/api/auth/login', '/api/auth/register', '/api/auth/reset',
        '/api/auth/health', '/api/weather/current', '/api/system/status',
    ]
    return mw


PUBLIC_PATHS = [
    '/', '/docs', '/redoc', '/openapi.json',
    '/health', '/api/health',
    '/api/auth/login', '/api/auth/register', '/api/auth/reset', '/api/auth/health',
    '/api/weather/current', '/api/system/status',
]

PROTECTED_PATHS = [
    '/api/prediction/load', '/api/prediction/batch', '/api/prediction/history',
    '/api/auth/me', '/api/auth/sessions', '/api/auth/refresh', '/api/auth/logout',
    '/api/auth/change-password', '/api/system/metrics',
    '/api/analytics/accuracy/stats', '/api/analytics/drift/check',
    '/api/solar-generation', '/api/wind-generation', '/api/weather/history',
]


class TestShouldSkipAuth:
    def test_public_paths_are_open(self):
        mw = _make_middleware()
        for path in PUBLIC_PATHS:
            assert mw._should_skip_auth(path) is True, f"{path} 应为公开端点"

    def test_protected_paths_require_auth(self):
        mw = _make_middleware()
        for path in PROTECTED_PATHS:
            assert mw._should_skip_auth(path) is False, f"{path} 应要求认证"

    def test_root_does_not_open_everything(self):
        """回归：'/' 在排除列表里，但绝不能因前缀匹配放行其他路径"""
        mw = _make_middleware()
        assert mw._should_skip_auth('/') is True
        assert mw._should_skip_auth('/api/prediction/load') is False
        assert mw._should_skip_auth('/api/anything') is False

    def test_auth_me_not_leaked_by_login_prefix(self):
        """回归：/api/auth/login 公开，但 /api/auth/me 不能跟着公开"""
        mw = _make_middleware()
        assert mw._should_skip_auth('/api/auth/login') is True
        assert mw._should_skip_auth('/api/auth/me') is False
        assert mw._should_skip_auth('/api/auth/sessions') is False
