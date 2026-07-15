import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.main import app


@pytest_asyncio.fixture
async def unauthenticated_client(db: AsyncSession):
    """A client with no session cookie and no get_current_user override — exercises
    the real dependency, unlike the `client` fixture (which always logs in)."""

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_unauthenticated_request_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.get("/boxes/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/auth/login?next=%2Fboxes%2F"


async def test_unauthenticated_dashboard_get_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.get("/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/auth/login?next=%2F"


async def test_unauthenticated_head_dashboard_still_public(unauthenticated_client: AsyncClient) -> None:
    # Uptime checks (shields.io badge etc.) carry no session cookie — must stay public.
    resp = await unauthenticated_client.head("/", follow_redirects=False)
    assert resp.status_code == 200
