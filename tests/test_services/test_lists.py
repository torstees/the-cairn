from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, KeyMode, KeyRoot, PracticeListType, ProgressStatus, Role, TuneType, User
from cairn.schemas import TuneCreate
from cairn.services.boxes import create_box
from cairn.services.lists import (
    activate_list,
    add_tune_to_list,
    create_list,
    deactivate_list,
    get_active_list,
    get_list_entry,
    remove_tune_from_list,
    update_list_entry_display_alias,
    update_list_entry_transpose,
)
from cairn.services.tunes import add_alias, create_tune, get_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|"


async def _user(db: AsyncSession, username: str = "alice") -> User:
    u = User(username=username, email=f"{username}@example.com", hashed_password="x", role=Role.student)
    db.add(u)
    await db.flush()
    return u


async def _tune(db: AsyncSession, title: str = "The Morning Dew") -> object:
    return await create_tune(
        db,
        TuneCreate(
            title=title, tune_type=TuneType.reel, key_root=KeyRoot.D, key_mode=KeyMode.major, time_signature="4/4"
        ),
        abc_notation=_ABC,
    )


async def _box(db: AsyncSession, user_id: int, name: str = "Session Box") -> object:
    return await create_box(db, user_id, name, instruments=[Instrument.flute])


# ── create_list ────────────────────────────────────────────────────────────────


async def test_create_list_defaults(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "My Repertoire", PracticeListType.repertoire)
    assert pl.id is not None
    assert pl.name == "My Repertoire"
    assert pl.list_type == PracticeListType.repertoire
    assert pl.progress_goal == ProgressStatus.committed
    assert pl.target_date is None
    assert pl.is_active is False


async def test_create_list_with_optional_fields(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(
        db,
        u.id,
        box.id,
        "  Woodshed  ",
        PracticeListType.woodshed,
        progress_goal=ProgressStatus.session_ready,
        target_date=date(2026, 12, 31),
    )
    assert pl.name == "Woodshed"
    assert pl.progress_goal == ProgressStatus.session_ready
    assert pl.target_date == date(2026, 12, 31)


# ── activate_list / deactivate_list ───────────────────────────────────────────


async def test_activate_list_sets_is_active(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    result = await activate_list(db, u.id, pl.id)
    assert result is not None
    assert result.is_active is True


async def test_activate_list_deactivates_previous(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl1 = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    pl2 = await create_list(db, u.id, box.id, "List B", PracticeListType.woodshed)
    await activate_list(db, u.id, pl1.id)
    await activate_list(db, u.id, pl2.id)
    await db.refresh(pl1)
    assert pl1.is_active is False
    assert pl2.is_active is True


async def test_activate_list_wrong_user_returns_none(db: AsyncSession) -> None:
    u1 = await _user(db, "alice")
    u2 = await _user(db, "bob")
    box = await _box(db, u1.id)
    pl = await create_list(db, u1.id, box.id, "List A", PracticeListType.repertoire)
    result = await activate_list(db, u2.id, pl.id)
    assert result is None


async def test_activate_list_unknown_id_returns_none(db: AsyncSession) -> None:
    u = await _user(db)
    result = await activate_list(db, u.id, 9999)
    assert result is None


async def test_deactivate_list_clears_active(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    await activate_list(db, u.id, pl.id)
    await deactivate_list(db, u.id)
    assert await get_active_list(db, u.id) is None


async def test_deactivate_list_no_active_is_noop(db: AsyncSession) -> None:
    u = await _user(db)
    await deactivate_list(db, u.id)  # must not raise


# ── get_active_list ────────────────────────────────────────────────────────────


async def test_get_active_list_returns_none_when_none_active(db: AsyncSession) -> None:
    u = await _user(db)
    assert await get_active_list(db, u.id) is None


async def test_get_active_list_returns_active(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    await activate_list(db, u.id, pl.id)
    active = await get_active_list(db, u.id)
    assert active is not None
    assert active.id == pl.id


# ── add_tune_to_list / remove_tune_from_list ──────────────────────────────────


async def test_add_tune_to_list(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    entry = await add_tune_to_list(db, pl.id, tune.id)
    assert entry is not None
    assert entry.tune_id == tune.id
    assert entry.list_id == pl.id
    assert entry.setting_id is None


async def test_add_tune_to_list_with_setting(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    loaded = await get_tune(db, tune.id)
    setting_id = loaded.settings[0].id
    entry = await add_tune_to_list(db, pl.id, tune.id, setting_id=setting_id)
    assert entry.setting_id == setting_id


async def test_add_tune_to_list_unknown_list_returns_none(db: AsyncSession) -> None:
    tune = await _tune(db)
    result = await add_tune_to_list(db, 9999, tune.id)
    assert result is None


async def test_add_tune_to_list_with_display_alias(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    entry = await add_tune_to_list(db, pl.id, tune.id, display_alias_id=alias.id)
    assert entry.display_alias_id == alias.id


async def test_add_tune_to_list_display_alias_defaults_to_none(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    entry = await add_tune_to_list(db, pl.id, tune.id)
    assert entry.display_alias_id is None


async def test_update_list_entry_display_alias(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    await add_tune_to_list(db, pl.id, tune.id)

    updated = await update_list_entry_display_alias(db, pl.id, tune.id, alias.id)
    assert updated is not None
    assert updated.display_alias_id == alias.id

    reloaded = await get_list_entry(db, pl.id, tune.id)
    assert reloaded.display_alias.name == "Sunrise Reel"


async def test_update_list_entry_display_alias_missing_entry_returns_none(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    result = await update_list_entry_display_alias(db, pl.id, tune.id, None)
    assert result is None


async def test_update_list_entry_transpose(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    await add_tune_to_list(db, pl.id, tune.id)

    updated = await update_list_entry_transpose(db, pl.id, tune.id, KeyRoot.E, 1)
    assert updated is not None
    assert updated.transpose_key_root == KeyRoot.E
    assert updated.transpose_octave == 1

    reloaded = await get_list_entry(db, pl.id, tune.id)
    assert reloaded.transpose_key_root == KeyRoot.E
    assert reloaded.transpose_octave == 1


async def test_update_list_entry_transpose_can_clear(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    await add_tune_to_list(db, pl.id, tune.id)
    await update_list_entry_transpose(db, pl.id, tune.id, KeyRoot.E, 1)

    cleared = await update_list_entry_transpose(db, pl.id, tune.id, None, 0)
    assert cleared.transpose_key_root is None
    assert cleared.transpose_octave == 0


async def test_update_list_entry_transpose_missing_entry_returns_none(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    result = await update_list_entry_transpose(db, pl.id, tune.id, KeyRoot.E, 0)
    assert result is None


async def test_remove_tune_from_list_returns_true(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    await add_tune_to_list(db, pl.id, tune.id)
    result = await remove_tune_from_list(db, pl.id, tune.id)
    assert result is True


async def test_remove_tune_from_list_missing_returns_false(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    result = await remove_tune_from_list(db, pl.id, 9999)
    assert result is False


async def test_get_active_list_eager_loads_entries(db: AsyncSession) -> None:
    u = await _user(db)
    box = await _box(db, u.id)
    pl = await create_list(db, u.id, box.id, "List A", PracticeListType.repertoire)
    tune = await _tune(db)
    await add_tune_to_list(db, pl.id, tune.id)
    await activate_list(db, u.id, pl.id)
    active = await get_active_list(db, u.id)
    assert len(active.entries) == 1
