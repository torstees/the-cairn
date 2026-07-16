from httpx import AsyncClient


async def test_unauthenticated_request_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.get("/boxes/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/auth/login?next=%2Fboxes%2F"


async def test_unauthenticated_root_shows_guest_landing_page(unauthenticated_client: AsyncClient) -> None:
    # A guest (see #228) gets a public landing page at root instead of an
    # immediate redirect to login.
    resp = await unauthenticated_client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "Sign in with Google" in resp.text


async def test_unauthenticated_head_dashboard_still_public(unauthenticated_client: AsyncClient) -> None:
    # Uptime checks (shields.io badge etc.) carry no session cookie — must stay public.
    resp = await unauthenticated_client.head("/", follow_redirects=False)
    assert resp.status_code == 200
