from httpx import AsyncClient


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
