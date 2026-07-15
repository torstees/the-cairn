from fastapi.responses import RedirectResponse
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Role, User
from cairn.routers import auth as auth_module
from cairn.routers.auth import _safe_next_path


def test_safe_next_path_allows_relative_paths() -> None:
    assert _safe_next_path("/tunes") == "/tunes"
    assert _safe_next_path("/tunes?page=2") == "/tunes?page=2"


def test_safe_next_path_rejects_off_site_targets() -> None:
    assert _safe_next_path(None) == "/"
    assert _safe_next_path("") == "/"
    assert _safe_next_path("https://evil.example") == "/"
    assert _safe_next_path("//evil.example") == "/"


async def test_login_stores_safe_next_path_and_redirects_to_google(client: AsyncClient, monkeypatch) -> None:
    captured = {}

    async def fake_authorize_redirect(request, redirect_uri):
        captured["next"] = request.session.get("next")
        captured["redirect_uri"] = redirect_uri
        return RedirectResponse("https://accounts.google.com/o/oauth2/fake", status_code=302)

    monkeypatch.setattr(auth_module.oauth.google, "authorize_redirect", fake_authorize_redirect)

    resp = await client.get("/auth/login?next=/boxes", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://accounts.google.com/o/oauth2/fake"
    assert captured["next"] == "/boxes"
    assert str(captured["redirect_uri"]).endswith("/auth/callback")


async def test_login_falls_back_to_root_for_unsafe_next(client: AsyncClient, monkeypatch) -> None:
    captured = {}

    async def fake_authorize_redirect(request, redirect_uri):
        captured["next"] = request.session.get("next")
        return RedirectResponse("https://accounts.google.com/o/oauth2/fake")

    monkeypatch.setattr(auth_module.oauth.google, "authorize_redirect", fake_authorize_redirect)

    await client.get("/auth/login?next=https://evil.example", follow_redirects=False)
    assert captured["next"] == "/"


async def test_callback_auto_provisions_new_user_as_student(client: AsyncClient, db: AsyncSession, monkeypatch) -> None:
    async def fake_authorize_access_token(request):
        return {"userinfo": {"sub": "google-sub-new", "email": "newplayer@example.com"}}

    monkeypatch.setattr(auth_module.oauth.google, "authorize_access_token", fake_authorize_access_token)

    resp = await client.get("/auth/callback", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/"

    user = await db.scalar(select(User).where(User.google_sub == "google-sub-new"))
    assert user is not None
    assert user.username == "newplayer"
    assert user.email == "newplayer@example.com"
    assert user.role == Role.student


async def test_callback_logs_in_existing_user_without_duplicating(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    existing = User(
        username="fiddler", email="fiddler@example.com", google_sub="google-sub-existing", role=Role.teacher
    )
    db.add(existing)
    await db.flush()

    async def fake_authorize_access_token(request):
        return {"userinfo": {"sub": "google-sub-existing", "email": "fiddler@example.com"}}

    monkeypatch.setattr(auth_module.oauth.google, "authorize_access_token", fake_authorize_access_token)

    await client.get("/auth/callback", follow_redirects=False)

    result = await db.scalars(select(User).where(User.google_sub == "google-sub-existing"))
    matches = result.all()
    assert len(matches) == 1
    assert matches[0].id == existing.id
    assert matches[0].role == Role.teacher  # untouched by login


async def test_callback_dedupes_username_collision(client: AsyncClient, db: AsyncSession, monkeypatch) -> None:
    taken = User(username="alice", email="alice@old-provider.example", google_sub="google-sub-old", role=Role.student)
    db.add(taken)
    await db.flush()

    async def fake_authorize_access_token(request):
        return {"userinfo": {"sub": "google-sub-alice-2", "email": "alice@new-provider.example"}}

    monkeypatch.setattr(auth_module.oauth.google, "authorize_access_token", fake_authorize_access_token)

    await client.get("/auth/callback", follow_redirects=False)

    user = await db.scalar(select(User).where(User.google_sub == "google-sub-alice-2"))
    assert user is not None
    assert user.username == "alice2"


async def test_callback_redirects_to_stored_next_path(client: AsyncClient, db: AsyncSession, monkeypatch) -> None:
    async def fake_authorize_redirect(request, redirect_uri):
        request.session["next"] = "/boxes"
        return RedirectResponse("https://accounts.google.com/o/oauth2/fake")

    async def fake_authorize_access_token(request):
        return {"userinfo": {"sub": "google-sub-flow", "email": "flow@example.com"}}

    monkeypatch.setattr(auth_module.oauth.google, "authorize_redirect", fake_authorize_redirect)
    monkeypatch.setattr(auth_module.oauth.google, "authorize_access_token", fake_authorize_access_token)

    await client.get("/auth/login?next=/boxes", follow_redirects=False)
    resp = await client.get("/auth/callback", follow_redirects=False)
    assert resp.headers["location"] == "/boxes"


async def test_logout_clears_session_and_redirects_to_login(client: AsyncClient, monkeypatch) -> None:
    async def fake_authorize_access_token(request):
        return {"userinfo": {"sub": "google-sub-logout", "email": "logout@example.com"}}

    monkeypatch.setattr(auth_module.oauth.google, "authorize_access_token", fake_authorize_access_token)

    await client.get("/auth/callback", follow_redirects=False)
    resp = await client.post("/auth/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/auth/login"


async def test_provision_user_commits_not_just_flushes(db: AsyncSession, monkeypatch) -> None:
    # Regression test: _provision_user() originally only called db.flush(), never
    # db.commit(). Each real request gets a fresh session with no auto-commit, so
    # the provisioned row was silently rolled back at the end of the request that
    # created it — invisible to this test's shared-session fixture (which sees a
    # flushed-but-uncommitted row just fine), but fatal in production: the next
    # request's login check found no user, bounced back through Google's silent
    # re-auth, and looped forever. Assert on the actual db.commit() call instead
    # of just querying afterward, since a query through the same session can't
    # tell flush and commit apart.
    from unittest.mock import AsyncMock

    commit_spy = AsyncMock(side_effect=db.commit)
    monkeypatch.setattr(db, "commit", commit_spy)

    await auth_module._provision_user(db, {"sub": "google-sub-commit-check", "email": "committer@example.com"})

    assert commit_spy.await_count >= 1
