from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, Role, TuneType, User
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.share_links import (
    create_share_link,
    get_share_link_by_token,
    list_share_links_for_tune,
    revoke_share_link,
)
from cairn.services.tunes import create_setting, create_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|"
_ALT_ABC = "|:GABc defg|GABc defg:|"


async def _user(db: AsyncSession, username: str = "alice") -> User:
    u = User(username=username, email=f"{username}@example.com", google_sub=f"google-sub-{username}", role=Role.student)
    db.add(u)
    await db.flush()
    return u


async def _tune(db: AsyncSession, owner_id: int | None = None):
    return await create_tune(
        db,
        TuneCreate(
            title="The Morning Dew",
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
            created_by=owner_id,
        ),
        abc_notation=_ABC,
    )


# ── create_share_link ──────────────────────────────────────────────────────────


async def test_create_share_link_for_whole_tune(db: AsyncSession) -> None:
    user = await _user(db)
    tune = await _tune(db, user.id)
    link = await create_share_link(db, user.id, tune.id)
    assert link.tune_id == tune.id
    assert link.setting_id is None
    assert link.created_by == user.id
    assert len(link.token) > 20


async def test_create_share_link_for_specific_setting(db: AsyncSession) -> None:
    user = await _user(db)
    tune = await _tune(db, user.id)
    setting = await create_setting(db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ALT_ABC))
    link = await create_share_link(db, user.id, tune.id, setting_id=setting.id)
    assert link.tune_id is None
    assert link.setting_id == setting.id


async def test_create_share_link_tokens_are_unique(db: AsyncSession) -> None:
    user = await _user(db)
    tune = await _tune(db, user.id)
    link1 = await create_share_link(db, user.id, tune.id)
    link2 = await create_share_link(db, user.id, tune.id)
    assert link1.token != link2.token


# ── get_share_link_by_token ────────────────────────────────────────────────────


async def test_get_share_link_by_token_found(db: AsyncSession) -> None:
    user = await _user(db)
    tune = await _tune(db, user.id)
    link = await create_share_link(db, user.id, tune.id)
    found = await get_share_link_by_token(db, link.token)
    assert found is not None
    assert found.id == link.id
    assert found.tune.title == "The Morning Dew"


async def test_get_share_link_by_token_not_found(db: AsyncSession) -> None:
    assert await get_share_link_by_token(db, "nonexistent-token") is None


# ── list_share_links_for_tune ──────────────────────────────────────────────────


async def test_list_share_links_includes_tune_and_setting_level(db: AsyncSession) -> None:
    user = await _user(db)
    tune = await _tune(db, user.id)
    setting = await create_setting(db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ALT_ABC))
    await create_share_link(db, user.id, tune.id)
    await create_share_link(db, user.id, tune.id, setting_id=setting.id)

    result = await list_share_links_for_tune(db, tune.id, [setting.id])
    assert len(result) == 2


async def test_list_share_links_empty_when_none_created(db: AsyncSession) -> None:
    user = await _user(db)
    tune = await _tune(db, user.id)
    result = await list_share_links_for_tune(db, tune.id, [])
    assert result == []


# ── revoke_share_link ──────────────────────────────────────────────────────────


async def test_revoke_share_link_by_creator(db: AsyncSession) -> None:
    user = await _user(db)
    tune = await _tune(db, user.id)
    link = await create_share_link(db, user.id, tune.id)
    assert await revoke_share_link(db, link.id, user.id) is True
    assert await get_share_link_by_token(db, link.token) is None


async def test_revoke_share_link_by_non_creator_returns_false(db: AsyncSession) -> None:
    user = await _user(db, "alice")
    other = await _user(db, "bob")
    tune = await _tune(db, user.id)
    link = await create_share_link(db, user.id, tune.id)
    assert await revoke_share_link(db, link.id, other.id) is False
    assert await get_share_link_by_token(db, link.token) is not None


async def test_revoke_share_link_unknown_id_returns_false(db: AsyncSession) -> None:
    user = await _user(db)
    assert await revoke_share_link(db, 9999, user.id) is False
