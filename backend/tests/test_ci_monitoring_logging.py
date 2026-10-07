"""Structured log context, rollover and Prometheus exception accounting."""

import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from realtime_api import metrics
from realtime_api import structured_logger as logs


def test_json_formatter_retains_business_fields_and_exception_context():
    formatter = logs.StructuredJSONFormatter()
    record = logging.LogRecord("forecast", logging.INFO, __file__, 21, "forecast %s", ("ready",), None)
    record.request_id = "request-1"
    record.duration_ms = 12
    record.response_time_ms = 13
    record.tags = ["load"]
    record.target_hour = "2026-10-01T00:00:00-04:00"
    record._private = "private marker"
    result = json.loads(formatter.format(record))
    assert result["message"] == "forecast ready"
    assert result["timestamp"].endswith("+00:00")
    assert result["request_id"] == "request-1"
    assert result["duration_ms"] == 12 and result["response_time_ms"] == 13
    assert result["target_hour"] == record.target_hour
    assert "_private" not in result and "args" not in result
    try:
        raise ValueError("model unavailable")
    except ValueError:
        error_record = logging.LogRecord("forecast", logging.ERROR, __file__, 34, "failure", (), sys.exc_info())
    error = json.loads(formatter.format(error_record))
    assert "ValueError: model unavailable" in error["exception"]
    assert error["traceback"] == error["exception"]
    plain = json.loads(formatter.format(logging.LogRecord("plain", logging.INFO, __file__, 1, "ready", (), None)))
    assert plain["message"] == "ready"


@pytest.mark.parametrize("level", ["debug", "info", "warning", "error", "critical", "exception"])
def test_context_logger_preserves_context_without_sharing_tags(level):
    logger = logs.ContextLogger("ci.context", request_id="fixed")
    logger.logger = Mock()
    logger.logger.name = "ci.context"
    logger.add_tag("forecast").add_tag("forecast").remove_tag("absent")
    assert logger.tags == ["forecast"]
    bound = logger.bind(user_id="user", session_id="session", correlation_id="correlation")
    bound.add_tag("load")
    assert logger.tags == ["forecast"]
    getattr(bound, level)("request %s", "ready", extra={"target_hour": "hour"})
    call = logger.logger.log.call_args
    assert call.args[1:3] == ("request %s", "ready")
    context = call.kwargs["extra"]
    assert context["request_id"] == "fixed"
    assert context["user_id"] == "user" and context["session_id"] == "session"
    assert context["tags"] == ["forecast", "load"]
    assert context["target_hour"] == "hour"
    assert context["caller_file"] == __file__
    if level == "exception":
        assert call.kwargs["exc_info"] is True
    logger.remove_tag("forecast")
    assert logger.tags == []


def test_async_logger_dispatches_levels_and_contains_handler_failure(capsys):
    logger = logs.AsyncStructuredLogger("ci.async.context")
    logger.logger = Mock()
    try:
        for level in ("debug", "info", "warning", "error"):
            getattr(logger, level + "_async")("event", extra={"key": "value"}).result(timeout=5)
            getattr(logger.logger, level).assert_called_once_with("event", extra={"key": "value"})
        logger.log_async(logging.CRITICAL, "critical event").result(timeout=5)
        logger.logger.critical.assert_called_once_with("critical event")
        logger.logger.error.side_effect = OSError("handler failed")
        logger.error_async("failure").result(timeout=5)
        assert "handler failed" in capsys.readouterr().out
    finally:
        logger.shutdown()


def test_rotation_respects_threshold_and_backup_order(tmp_path):
    rotator = logs.LogRotator(str(tmp_path), max_file_size_mb=1, backup_count=3)
    assert rotator.rotate_file("missing.log") is False
    current = tmp_path / "app.log"
    current.write_text("new", encoding="utf-8")
    assert rotator.rotate_file("app.log") is False
    rotator.max_file_size_bytes = 1
    (tmp_path / "app.log.1").write_text("first", encoding="utf-8")
    (tmp_path / "app.log.2").write_text("second", encoding="utf-8")
    (tmp_path / "app.log.3").write_text("oldest", encoding="utf-8")
    assert rotator.rotate_file("app.log") is True
    assert not current.exists()
    assert (tmp_path / "app.log.1").read_text(encoding="utf-8") == "new"
    assert (tmp_path / "app.log.2").read_text(encoding="utf-8") == "first"
    assert (tmp_path / "app.log.3").read_text(encoding="utf-8") == "second"
    current.write_text("next", encoding="utf-8")
    assert rotator.rotate_file("app.log") is True
    assert (tmp_path / "app.log.1").read_text(encoding="utf-8") == "next"


def test_manager_filters_and_business_events(monkeypatch):
    manager = object.__new__(logs.StructuredLoggingManager)
    manager.config = SimpleNamespace(get_logging_config=lambda: {"level": "WARNING"})
    manager._loggers = {}
    low = logging.LogRecord("api", logging.INFO, __file__, 1, "event", (), None)
    high = logging.LogRecord("api", logging.ERROR, __file__, 1, "event", (), None)
    assert manager._console_filter(low) is False
    assert manager._console_filter(high) is True
    assert manager._access_log_filter(low) is False
    low.request_id = "id"
    assert manager._access_log_filter(low) is True
    assert manager.get_logger("ci.manager", "id").logger.name == "ci.manager"
    assert manager.get_logger("ci.manager").logger.name == "ci.manager"
    captured = Mock()
    monkeypatch.setattr(manager, "get_logger", Mock(return_value=captured))
    manager.log_request_start("GET", "/forecast", "id", "127.0.0.1")
    manager.log_request_end("GET", "/forecast", "id", 200, 12, "127.0.0.1")
    manager.log_prediction("id", "ISO-NE", 23, model_count=3)
    manager.log_weather_data_fetch("id", 5, 34)
    contexts = [call.kwargs["extra"] for call in captured.info.call_args_list]
    assert [context["event_type"] for context in contexts] == ["request_start", "request_end", "load_prediction", "weather_data_fetch"]
    assert contexts[1]["status_code"] == 200 and contexts[1]["duration_ms"] == 12
    assert contexts[2]["models_used"] == 3
    assert contexts[3]["weather_stations_count"] == 5
    assert logs.StructuredLoggingManager() is logs.logging_manager
    for function in (logs.get_logger, logs.get_request_logger, logs.get_api_logger, logs.get_prediction_logger):
        assert function(request_id="id").logger.name


@pytest.mark.parametrize("file_enabled", [False, True])
def test_log_manager_setup_uses_rotating_files_without_mutating_global_logging(monkeypatch, tmp_path, file_enabled):
    manager = object.__new__(logs.StructuredLoggingManager)
    manager.config = SimpleNamespace(get_logging_config=lambda: {
        "level": "INFO", "file": {"enabled": file_enabled, "path": str(tmp_path / "app.log")},
    })
    root = Mock(handlers=[Mock()])
    handlers = []
    def rotating(*args, **kwargs):
        handler = Mock()
        handlers.append((args, kwargs, handler))
        return handler
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(logs, "logging", SimpleNamespace(
        getLogger=lambda: root, DEBUG=logging.DEBUG, INFO=logging.INFO,
        ERROR=logging.ERROR, StreamHandler=lambda stream: Mock(),
    ))
    monkeypatch.setattr(logs, "RotatingFileHandler", rotating)
    manager._setup_logging()
    assert root.removeHandler.call_count == 1
    assert root.addHandler.call_count == (4 if file_enabled else 3)
    assert len(handlers) == (3 if file_enabled else 2)
    assert all(config["backupCount"] == 5 and config["encoding"] == "utf-8" for _, config, _ in handlers)


def _request(route=True):
    scope = {"type": "http", "method": "GET", "path": "/ci-observe/42", "scheme": "http", "server": ("test", 80), "headers": [], "query_string": b""}
    if route:
        scope["route"] = SimpleNamespace(path="/ci-observe/{id}")
    return Request(scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", [True, False])
async def test_prometheus_middleware_records_status_duration_and_balances_active_requests(monkeypatch, route):
    labels = {}
    collectors = []
    for name in ("REQUESTS", "REQUEST_DURATION", "IN_PROGRESS"):
        collector = Mock()
        labels[name] = collector
        monkeypatch.setattr(metrics, name, collector)
        collectors.append(collector)
    response = Response(status_code=201)
    observed = await metrics.metrics_middleware(_request(route), AsyncMock(return_value=response))
    assert observed is response
    path = "/ci-observe/{id}" if route else "/ci-observe/42"
    labels["REQUESTS"].labels.assert_called_once_with(method="GET", path=path, status="201")
    labels["IN_PROGRESS"].labels.return_value.inc.assert_called_once()
    labels["IN_PROGRESS"].labels.return_value.dec.assert_called_once()
    assert labels["REQUEST_DURATION"].labels.return_value.observe.call_args.args[0] >= 0


@pytest.mark.asyncio
async def test_prometheus_middleware_preserves_original_failure_and_exposes_metrics(monkeypatch):
    requests, duration, progress = Mock(), Mock(), Mock()
    monkeypatch.setattr(metrics, "REQUESTS", requests)
    monkeypatch.setattr(metrics, "REQUEST_DURATION", duration)
    monkeypatch.setattr(metrics, "IN_PROGRESS", progress)
    with pytest.raises(TimeoutError, match="upstream timed out"):
        await metrics.metrics_middleware(_request(), AsyncMock(side_effect=TimeoutError("upstream timed out")))
    requests.labels.assert_called_once_with(method="GET", path="/ci-observe/{id}", status="500")
    progress.labels.return_value.dec.assert_called_once()
    duration.labels.return_value.observe.assert_called_once()
    exposed = await metrics.metrics_endpoint()
    assert exposed.status_code == 200
    assert "http_requests_total" in exposed.body.decode("utf-8")
    assert exposed.headers["content-type"].startswith("text/plain")
