"""Consistent business/HTTP exception responses without contacting providers."""

import json
from enum import IntEnum

from fastapi import HTTPException
import pytest
from starlette.requests import Request

from realtime_api import error_handling as errors


@pytest.mark.parametrize("exception_type,status", [
    (errors.AuthenticationError, 401), (errors.InvalidCredentialsError, 401),
    (errors.TokenExpiredError, 401), (errors.PermissionDeniedError, 401),
    (errors.ValidationError, 400), (errors.ResourceNotFoundError, 404),
    (errors.DuplicateResourceError, 409), (errors.DatabaseError, 500),
    (errors.RedisError, 500), (errors.ModelServiceError, 500),
    (errors.ModelNotReadyError, 500), (errors.WeatherAPIError, 500),
    (errors.PredictionError, 500), (errors.ConfigurationError, 500),
])
def test_business_exception_retains_identity_message_and_http_status(exception_type, status):
    exception = exception_type(detail="provider unavailable")
    assert exception.status_code == status
    assert exception.error_id.startswith("err_")
    assert exception.detail["error_id"] == exception.error_id
    assert exception.detail["error_code"] == exception.error_code.value
    assert exception.detail["detail"] == "provider unavailable"
    assert exception.detail["message"]


def test_error_payload_defaults_override_and_unknown_code():
    default = errors.create_error_response(errors.ErrorCode.MODEL_NOT_READY)
    assert default["error_id"].startswith("err_") and default["timestamp"]
    explicit = errors.create_error_response(errors.ErrorCode.DATABASE_ERROR, "cannot query", "database unavailable", "fixed")
    assert explicit["error_id"] == "fixed" and explicit["message"] == "cannot query"
    assert explicit["detail"] == "database unavailable"
    assert errors.get_error_message(errors.ErrorCode.VALIDATION_ERROR)
    assert errors.get_error_message(errors.ErrorCode.SUCCESS) == "未知错误"
    success = errors.SmartGridException(errors.ErrorCode.SUCCESS, "ok", error_id="fixed")
    assert success.status_code == 200
    class UnknownCode(IntEnum):
        FUTURE = 60000
    assert errors.SmartGridException(UnknownCode.FUTURE, "future").status_code == 500
    assert errors.ResourceNotFoundError("snapshot", message="no snapshot").message == "no snapshot"
    assert errors.DuplicateResourceError("snapshot", message="snapshot exists").message == "snapshot exists"


def request(client):
    return Request({"type": "http", "method": "GET", "path": "/forecast", "scheme": "http", "server": ("localhost", 80), "headers": [], "query_string": b"", "client": client})


@pytest.mark.asyncio
@pytest.mark.parametrize("client", [None, ("127.0.0.1", 1234)])
async def test_business_response_does_not_lose_original_error_fields(client):
    exception = errors.ModelNotReadyError("inputs not ready", "missing weather")
    response = await errors.ErrorHandler().handle_exception(request(client), exception)
    assert response.status_code == 500
    assert json.loads(response.body) == exception.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(400, errors.ErrorCode.BAD_REQUEST), (401, errors.ErrorCode.UNAUTHORIZED), (403, errors.ErrorCode.FORBIDDEN), (404, errors.ErrorCode.NOT_FOUND), (409, errors.ErrorCode.CONFLICT), (422, errors.ErrorCode.VALIDATION_ERROR), (429, errors.ErrorCode.TOO_MANY_REQUESTS), (503, errors.ErrorCode.INTERNAL_SERVER_ERROR)])
async def test_http_exception_maps_semantic_code_and_keeps_status(status, code):
    response = await errors.ErrorHandler().handle_exception(request(None), HTTPException(status_code=status, detail="upstream refused"))
    body = json.loads(response.body)
    assert response.status_code == status
    assert body["error_code"] == code.value
    assert body["message"] == body["detail"] == "upstream refused"


@pytest.mark.asyncio
async def test_unknown_exception_is_reported_with_unique_id():
    response = await errors.ErrorHandler().handle_exception(request(("127.0.0.1", 1234)), RuntimeError("failed provider"))
    body = json.loads(response.body)
    assert response.status_code == 500
    assert body["error_code"] == errors.ErrorCode.UNKNOWN_ERROR.value
    assert body["detail"] == "failed provider"
    empty_detail = HTTPException(status_code=400)
    empty_detail.detail = None
    response = await errors.ErrorHandler().handle_exception(request(None), empty_detail)
    assert json.loads(response.body)["message"] == "请求失败"
