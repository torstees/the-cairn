"""Guest (unauthenticated) read access to the public catalog — see #225.

Covers the four view surfaces that dropped their router-level login gate
(tunes, warmups, sets, content pages), plus a spot-check that mutation
routes on each of those routers still require login.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import ContentType, ContentVisibility, KeyMode, KeyRoot, Role, TuneType, User, WarmupType
from cairn.schemas import TuneCreate
from cairn.services.content import upsert_content
from cairn.services.tune_sets import create_set
from cairn.services.tunes import create_tune
from cairn.services.warmups import create_warmup

_ABC = "X:1\nT:x\nK:D\n|:DEFA BAFA|DEFA BAFA:|"


async def _other_user(db: AsyncSession, username: str = "owner", role: Role = Role.student) -> User:
    u = User(username=username, email=f"{username}@example.com", google_sub=f"google-sub-{username}", role=role)
    db.add(u)
    await db.flush()
    return u


async def _tune(db: AsyncSession, visibility: ContentVisibility = ContentVisibility.public, created_by=None):
    return await create_tune(
        db,
        TuneCreate(
            title="The Morning Dew",
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
            visibility=visibility,
            created_by=created_by,
        ),
        abc_notation=_ABC,
    )


# ── tunes ───────────────────────────────────────────────────────────────────


async def test_guest_can_view_public_tune_list_and_detail(
    unauthenticated_client: AsyncClient, db: AsyncSession
) -> None:
    tune = await _tune(db)
    resp = await unauthenticated_client.get("/tunes/")
    assert resp.status_code == 200
    assert tune.title in resp.text

    resp = await unauthenticated_client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert tune.title in resp.text


async def test_guest_cannot_view_private_tune(unauthenticated_client: AsyncClient, db: AsyncSession) -> None:
    owner = await _other_user(db)
    tune = await _tune(db, visibility=ContentVisibility.private, created_by=owner.id)
    resp = await unauthenticated_client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 404

    resp = await unauthenticated_client.get("/tunes/")
    assert tune.title not in resp.text


async def test_guest_cannot_view_enrolled_tune(unauthenticated_client: AsyncClient, db: AsyncSession) -> None:
    owner = await _other_user(db)
    tune = await _tune(db, visibility=ContentVisibility.enrolled, created_by=owner.id)
    resp = await unauthenticated_client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 404


async def test_guest_tune_create_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.post(
        "/tunes/",
        data={
            "title": "Guest Tune",
            "tune_type": TuneType.reel.value,
            "key_root": KeyRoot.D.value,
            "key_mode": KeyMode.major.value,
            "time_signature": "4/4",
            "abc_notation": _ABC,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("/auth/login")


async def test_guest_tune_new_form_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.get("/tunes/new", follow_redirects=False)
    assert resp.status_code == 307


# ── warmups ─────────────────────────────────────────────────────────────────


async def test_guest_can_view_warmup_list_and_detail(unauthenticated_client: AsyncClient, db: AsyncSession) -> None:
    warmup = await create_warmup(
        db, title="D Major Scale", warmup_type=WarmupType.scale, content=_ABC, difficulty=1, instruments=[]
    )
    resp = await unauthenticated_client.get("/warmups")
    assert resp.status_code == 200
    assert warmup.title in resp.text

    resp = await unauthenticated_client.get(f"/warmups/{warmup.id}")
    assert resp.status_code == 200
    assert warmup.title in resp.text


async def test_guest_warmup_create_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.post(
        "/warmups",
        data={"title": "Guest Warmup", "warmup_type": WarmupType.scale.value, "content": _ABC, "difficulty": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 307


async def test_guest_warmup_delete_redirects_to_login(unauthenticated_client: AsyncClient, db: AsyncSession) -> None:
    warmup = await create_warmup(
        db, title="D Major Scale", warmup_type=WarmupType.scale, content=_ABC, difficulty=1, instruments=[]
    )
    resp = await unauthenticated_client.delete(f"/warmups/{warmup.id}", follow_redirects=False)
    assert resp.status_code == 307


# ── sets ────────────────────────────────────────────────────────────────────


async def test_guest_can_view_set_index_and_detail(unauthenticated_client: AsyncClient, db: AsyncSession) -> None:
    tune_set = await create_set(db, title="Evening Jigs")
    resp = await unauthenticated_client.get("/sets")
    assert resp.status_code == 200
    assert tune_set.title in resp.text

    resp = await unauthenticated_client.get(f"/sets/{tune_set.id}")
    assert resp.status_code == 200
    assert tune_set.title in resp.text


async def test_guest_set_create_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.post(
        "/sets", data={"title": "Guest Set", "members": "[]"}, follow_redirects=False
    )
    assert resp.status_code == 307


# ── content pages ───────────────────────────────────────────────────────────


async def test_guest_can_view_public_content_page(unauthenticated_client: AsyncClient, db: AsyncSession) -> None:
    await upsert_content(
        db,
        slug="getting-started",
        title="Getting Started",
        content_type=ContentType.page,
        body="Welcome.",
    )
    resp = await unauthenticated_client.get("/pages/getting-started")
    assert resp.status_code == 200
    assert "Getting Started" in resp.text


async def test_guest_cannot_view_private_content_page(unauthenticated_client: AsyncClient, db: AsyncSession) -> None:
    await upsert_content(
        db,
        slug="teacher-notes",
        title="Teacher Notes",
        content_type=ContentType.page,
        body="Internal.",
        visibility=ContentVisibility.private,
    )
    resp = await unauthenticated_client.get("/pages/teacher-notes")
    assert resp.status_code == 404
