import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, TuneSetting, TuneType
from cairn.schemas import TuneCreate, TuneUpdate
from cairn.services.tunes import create_tune, delete_tune, get_tune, list_tunes, update_tune

ABC = "X:1\nT:Test\nM:4/4\nK:D\n|:DEFG|ABcd:|\n"


def _tune_create(**kwargs) -> TuneCreate:
    defaults = dict(title="The Morning Dew", tune_type=TuneType.reel, key_root=KeyRoot.D, key_mode=KeyMode.major, time_signature="4/4")
    return TuneCreate(**{**defaults, **kwargs})


# ── create_tune ────────────────────────────────────────────────────────────────

async def test_create_tune_returns_tune_with_id(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    assert tune.id is not None
    assert tune.title == "The Morning Dew"


async def test_create_tune_creates_exactly_one_core_setting(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))
    settings = result.scalars().all()
    assert len(settings) == 1
    assert settings[0].is_core is True
    assert settings[0].abc_notation == ABC


async def test_create_tune_setting_label_default(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))
    setting = result.scalar_one()
    assert setting.label == "Standard"


async def test_create_tune_setting_label_custom(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC, setting_label="Clare style")

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))
    setting = result.scalar_one()
    assert setting.label == "Clare style"


# ── get_tune ──────────────────────────────────────────────────────────────────

async def test_get_tune_returns_tune(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    found = await get_tune(db, created.id)
    assert found is not None
    assert found.id == created.id
    assert found.title == created.title


async def test_get_tune_loads_settings(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    found = await get_tune(db, created.id)
    assert found is not None
    assert len(found.settings) == 1
    assert found.settings[0].is_core is True


async def test_get_tune_returns_none_for_missing_id(db: AsyncSession) -> None:
    result = await get_tune(db, 99999)
    assert result is None


# ── list_tunes ────────────────────────────────────────────────────────────────

async def test_list_tunes_returns_all(db: AsyncSession) -> None:
    await create_tune(db, _tune_create(title="Banish Misfortune"), abc_notation=ABC)
    await create_tune(db, _tune_create(title="The Foxhunter"), abc_notation=ABC)
    tunes = await list_tunes(db)
    assert len(tunes) == 2


async def test_list_tunes_ordered_by_title(db: AsyncSession) -> None:
    await create_tune(db, _tune_create(title="The Foxhunter"), abc_notation=ABC)
    await create_tune(db, _tune_create(title="Banish Misfortune"), abc_notation=ABC)
    tunes = await list_tunes(db)
    assert tunes[0].title == "Banish Misfortune"
    assert tunes[1].title == "The Foxhunter"


async def test_list_tunes_empty(db: AsyncSession) -> None:
    tunes = await list_tunes(db)
    assert tunes == []


# ── update_tune ───────────────────────────────────────────────────────────────

async def test_update_tune_changes_fields(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    updated = await update_tune(db, tune.id, TuneUpdate(title="Revised Title", key_root=KeyRoot.G, key_mode=KeyMode.major))
    assert updated is not None
    assert updated.title == "Revised Title"
    assert updated.key_root == KeyRoot.G
    assert updated.key_mode == KeyMode.major
    assert updated.time_signature == "4/4"  # unchanged


async def test_update_tune_exclude_unset(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(region="Clare"), abc_notation=ABC)
    updated = await update_tune(db, tune.id, TuneUpdate(title="New Title"))
    assert updated is not None
    assert updated.region == "Clare"  # untouched field preserved


async def test_update_tune_returns_none_for_missing_id(db: AsyncSession) -> None:
    result = await update_tune(db, 99999, TuneUpdate(title="Ghost"))
    assert result is None


# ── delete_tune ───────────────────────────────────────────────────────────────

async def test_delete_tune_removes_tune(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    result = await delete_tune(db, tune.id)
    assert result is True
    assert await get_tune(db, tune.id) is None


async def test_delete_tune_cascades_to_settings(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    tune_id = tune.id
    await delete_tune(db, tune_id)

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune_id))
    assert result.scalars().all() == []


async def test_delete_tune_returns_false_for_missing_id(db: AsyncSession) -> None:
    result = await delete_tune(db, 99999)
    assert result is False
