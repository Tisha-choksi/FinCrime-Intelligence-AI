import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import app


class _FakeSession:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    async def execute(self, _statement):
        if self.should_fail:
            raise RuntimeError("db down")
        return None


async def _override_ok():
    yield _FakeSession()


async def _override_down():
    yield _FakeSession(should_fail=True)


@pytest.mark.asyncio
async def test_health_ok():
    app.dependency_overrides[get_session] = _override_ok
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/health")
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


@pytest.mark.asyncio
async def test_health_db_down():
    app.dependency_overrides[get_session] = _override_down
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/health")
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 503
