"""Missing async dependencies must produce an actionable error, not a NameError."""
import builtins
import runpy
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_missing_sqlalchemy_async_dependency_keeps_module_importable(monkeypatch):
    real_import = builtins.__import__

    def without_async(name, *args, **kwargs):
        if name == "sqlalchemy.ext.asyncio":
            raise ImportError("SQLAlchemy asyncio requires greenlet")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_async)
    module = runpy.run_path(str(Path(__file__).parents[1] / "realtime_api/database.py"))
    assert module["_SQLALCHEMY_ASYNC_AVAILABLE"] is False
    session = module["get_db_async"]()
    with pytest.raises(RuntimeError, match=r"sqlalchemy\[asyncio\]"):
        await session.__anext__()
    await session.aclose()
    # No worker is started by importing the module; release its unused executor.
    module["db_manager"]._executor.shutdown(wait=True)
