from httpx import AsyncClient

from cairn.templating import APP_VERSION


async def test_version_endpoint_returns_current_version(client: AsyncClient) -> None:
    resp = await client.get("/version")
    assert resp.status_code == 200
    assert resp.json() == {"version": APP_VERSION}


async def test_dashboard_footer_shows_version(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert f"v{APP_VERSION}" in resp.text
