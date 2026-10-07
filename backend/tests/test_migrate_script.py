"""数据库迁移入口的最小可靠性测试。"""

import importlib.util
import re
import sqlite3
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "migrate.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("smartgrid_migrate", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_column_fallback_types_match_canonical_schema():
    module = _load_script()
    columns = module.COLUMN_CHECKS["load_predictions"]

    assert columns["net_load_mw"] == "DECIMAL(10, 3) NULL"
    assert columns["actual_load_mw"] == "DECIMAL(10, 3) NULL"
    assert columns["data_source"] == "VARCHAR(50) NULL"


def test_create_table_failure_makes_migration_fail(monkeypatch, tmp_path):
    module = _load_script()
    init_sql = tmp_path / "init-db.sql"
    init_sql.write_text(
        "CREATE TABLE IF NOT EXISTS broken_table (id INT);",
        encoding="utf-8",
    )

    class FakeCursor:
        def __init__(self):
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            if sql.startswith("CREATE TABLE"):
                raise RuntimeError("simulated DDL failure")

        def fetchone(self):
            # 关键列已存在；遗留风电列不存在。
            if "COLUMN_NAME" in self.last_sql:
                return (1,)
            return (0,)

        def fetchall(self):
            return []

        def close(self):
            pass

    class FakeConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(module, "INIT_SQL", str(init_sql))
    monkeypatch.setattr(module.mysql.connector, "connect", lambda **kwargs: FakeConnection())
    monkeypatch.setattr("sys.argv", ["migrate.py"])

    assert module.main() == 1


def test_view_extraction_is_idempotent():
    module = _load_script()
    views = module.extract_create_views(
        "CREATE VIEW today_predictions AS SELECT id FROM load_predictions;"
    )

    assert views == [
        (
            "today_predictions",
            "CREATE OR REPLACE VIEW `today_predictions` AS SELECT id FROM load_predictions;",
        )
    ]


def test_active_session_view_uses_utc_expiry_with_non_utc_server_clock():
    module = _load_script()
    sql = Path(module.INIT_SQL).read_text(encoding="utf-8")
    view_sql = dict(module.extract_create_views(sql))["active_sessions_view"]
    # last_activity and idle_minutes retain the existing server-local clock.
    assert "TIMESTAMPDIFF(MINUTE, s.last_activity, NOW())" in view_sql
    select_sql = view_sql.split(" AS ", 1)[1]
    # SQLite runs the real WHERE predicate; only MySQL's unrelated idle function
    # is replaced, since this regression targets expiry in a UTC+8 server.
    select_sql = re.sub(r"TIMESTAMPDIFF\(MINUTE,\s*s\.last_activity,\s*NOW\(\)\)", "0", select_sql)
    with sqlite3.connect(":memory:") as db:
        db.create_function("NOW", 0, lambda: "2026-01-01 20:00:00")
        db.create_function("UTC_TIMESTAMP", 0, lambda: "2026-01-01 12:00:00")
        db.executescript("""
            CREATE TABLE users (id INTEGER, username TEXT, is_active INTEGER);
            INSERT INTO users VALUES (1, 'isolated', 1), (2, 'disabled', 0);
            CREATE TABLE user_sessions (
                id INTEGER, session_id TEXT, user_id INTEGER, client_ip TEXT,
                platform TEXT, last_activity TEXT, expires_at TEXT, is_active INTEGER, revoked_at TEXT
            );
            INSERT INTO user_sessions VALUES
                (1, 'valid', 1, NULL, 'web', '2026-01-01 20:00:00', '2026-01-01 13:00:00', 1, NULL),
                (2, 'expired', 1, NULL, 'web', '2026-01-01 20:00:00', '2026-01-01 11:00:00', 1, NULL),
                (3, 'revoked', 1, NULL, 'web', '2026-01-01 20:00:00', '2026-01-01 13:00:00', 1, '2026-01-01 12:00:00'),
                (4, 'disabled', 2, NULL, 'web', '2026-01-01 20:00:00', '2026-01-01 13:00:00', 1, NULL);
        """)
        rows = db.execute(select_sql).fetchall()
    assert [row[1] for row in rows] == ["valid"]
