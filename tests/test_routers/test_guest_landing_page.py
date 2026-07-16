"""Guest landing page at root — see #228."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import ContentType
from cairn.services.content import upsert_content


async def test_guest_root_renders_landing_page(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.get("/")
    assert resp.status_code == 200
    assert "Sign in with Google" in resp.text
    assert 'href="/auth/login"' in resp.text


async def test_guest_root_renders_getting_started_content(
    unauthenticated_client: AsyncClient, db: AsyncSession
) -> None:
    await upsert_content(
        db,
        slug="getting-started",
        title="Welcome to The Cairn",
        content_type=ContentType.page,
        body="This is the friendly pitch for new visitors.",
    )
    resp = await unauthenticated_client.get("/")
    assert resp.status_code == 200
    assert "This is the friendly pitch for new visitors." in resp.text


async def test_guest_root_falls_back_gracefully_without_content_row(unauthenticated_client: AsyncClient) -> None:
    # No getting-started row seeded at all -- shouldn't crash, just show a bare fallback.
    resp = await unauthenticated_client.get("/")
    assert resp.status_code == 200
    assert "Sign in with Google" in resp.text


async def test_logged_in_user_still_sees_dashboard_not_landing_page(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text
    assert "Sign in with Google" not in resp.text
