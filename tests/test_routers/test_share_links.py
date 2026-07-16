from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, Role, TuneType, User
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.share_links import create_share_link
from cairn.services.tunes import create_setting, create_tune

_ABC = "X:1\nT:x\nK:D\n|:DEFA BAFA|DEFA BAFA:|"
_ALT_ABC = "X:1\nT:x\nK:D\n|:GABc defg|GABc defg:|"


async def _seed_tune(db: AsyncSession):
    return await create_tune(
        db,
        TuneCreate(
            title="The Morning Dew",
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
        ),
        abc_notation=_ABC,
    )


async def _other_user(db: AsyncSession, username: str = "other") -> User:
    u = User(username=username, email=f"{username}@example.com", google_sub=f"google-sub-{username}", role=Role.student)
    db.add(u)
    await db.flush()
    return u


# ── create/revoke via tunes.py ─────────────────────────────────────────────────


async def test_tune_share_link_create_shows_in_detail_page(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.post(f"/tunes/{tune.id}/share-links")
    assert resp.status_code == 200
    assert "/shared/" in resp.text
    assert "Whole tune" in resp.text


async def test_tune_share_link_create_404_for_unknown_tune(client: AsyncClient) -> None:
    resp = await client.post("/tunes/9999/share-links")
    assert resp.status_code == 404


async def test_tune_share_link_revoke(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    link = await create_share_link(db, user.id, tune.id)
    resp = await client.delete(f"/tunes/{tune.id}/share-links/{link.id}")
    assert resp.status_code == 200
    assert "No shared links yet" in resp.text


async def test_tune_share_link_revoke_404_for_another_users_link(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    other = await _other_user(db)
    link = await create_share_link(db, other.id, tune.id)
    resp = await client.delete(f"/tunes/{tune.id}/share-links/{link.id}")
    assert resp.status_code == 404


# ── per-setting share via settings.py ───────────────────────────────────────────


async def test_setting_share_link_create(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    setting = await create_setting(db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ALT_ABC))
    resp = await client.post(f"/tunes/{tune.id}/settings/{setting.id}/share-links")
    assert resp.status_code == 200
    assert "Alt" in resp.text
    assert "/shared/" in resp.text


async def test_setting_share_link_create_404_for_unknown_setting(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.post(f"/tunes/{tune.id}/settings/9999/share-links")
    assert resp.status_code == 404


# ── public /shared/{token} view ─────────────────────────────────────────────────


async def test_shared_detail_public_view_for_whole_tune(unauthenticated_client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    other = await _other_user(db)
    link = await create_share_link(db, other.id, tune.id)

    resp = await unauthenticated_client.get(f"/shared/{link.token}")
    assert resp.status_code == 200
    assert tune.title in resp.text
    assert "view only" in resp.text


async def test_shared_detail_public_view_for_specific_setting(
    unauthenticated_client: AsyncClient, db: AsyncSession
) -> None:
    tune = await _seed_tune(db)
    setting = await create_setting(db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ALT_ABC))
    other = await _other_user(db)
    link = await create_share_link(db, other.id, tune.id, setting_id=setting.id)

    resp = await unauthenticated_client.get(f"/shared/{link.token}")
    assert resp.status_code == 200
    assert "GABc defg" in resp.text


async def test_shared_detail_404_for_unknown_token(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.get("/shared/nonexistent-token")
    assert resp.status_code == 404


async def test_shared_detail_404_after_revoke(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    link = await create_share_link(db, user.id, tune.id)
    await client.delete(f"/tunes/{tune.id}/share-links/{link.id}")

    # /shared/ never checks auth, so the already-logged-in `client` works fine here too.
    resp = await client.get(f"/shared/{link.token}")
    assert resp.status_code == 404
