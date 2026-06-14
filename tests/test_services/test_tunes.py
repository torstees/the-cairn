import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, TuneSetting, TuneType
from cairn.schemas import TuneCreate, TuneSettingCreate, TuneUpdate
from cairn.services.tunes import create_setting, create_tune, delete_tune, get_tune, list_tunes, set_core_setting, update_tune

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


# ── create_setting ────────────────────────────────────────────────────────────

def _setting_create(tune_id: int, **kwargs) -> TuneSettingCreate:
    defaults = dict(
        tune_id=tune_id,
        label="Clare style",
        abc_notation="|:DEFG ABcd:|\n",
        ornamentation_level=OrnamentationLevel.none,
    )
    return TuneSettingCreate(**{**defaults, **kwargs})


async def test_create_setting_is_never_core(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    setting = await create_setting(db, tune.id, _setting_create(tune.id))
    assert setting is not None
    assert setting.is_core is False


async def test_create_setting_stores_fields(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    setting = await create_setting(
        db, tune.id,
        _setting_create(tune.id, label="Fiddle arrangement", instrument=Instrument.fiddle, source="Tommy Peoples"),
    )
    assert setting is not None
    assert setting.label == "Fiddle arrangement"
    assert setting.instrument == Instrument.fiddle
    assert setting.source == "Tommy Peoples"


async def test_create_setting_returns_none_for_missing_tune(db: AsyncSession) -> None:
    result = await create_setting(db, 99999, _setting_create(99999))
    assert result is None


async def test_create_setting_tune_now_has_two_settings(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    await create_setting(db, tune.id, _setting_create(tune.id))
    found = await get_tune(db, tune.id)
    assert found is not None
    assert len(found.settings) == 2


# ── set_core_setting ──────────────────────────────────────────────────────────

async def test_set_core_promotes_target(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    new_s = await create_setting(db, tune.id, _setting_create(tune.id))
    assert new_s is not None
    result = await set_core_setting(db, tune.id, new_s.id)
    assert result is not None
    assert result.is_core is True


async def test_set_core_demotes_old_core(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    loaded = await get_tune(db, tune.id)
    assert loaded is not None
    old_core_id = loaded.settings[0].id
    new_s = await create_setting(db, tune.id, _setting_create(tune.id))
    assert new_s is not None
    await set_core_setting(db, tune.id, new_s.id)
    old_core = await db.get(TuneSetting, old_core_id)
    assert old_core is not None
    assert old_core.is_core is False


async def test_set_core_exactly_one_core_after_swap(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    new_s = await create_setting(db, tune.id, _setting_create(tune.id))
    assert new_s is not None
    await set_core_setting(db, tune.id, new_s.id)
    result = await db.execute(
        select(TuneSetting).where(TuneSetting.tune_id == tune.id, TuneSetting.is_core.is_(True))
    )
    cores = result.scalars().all()
    assert len(cores) == 1
    assert cores[0].id == new_s.id


async def test_set_core_idempotent_when_already_core(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    loaded = await get_tune(db, tune.id)
    assert loaded is not None
    core_id = loaded.settings[0].id
    result = await set_core_setting(db, tune.id, core_id)
    assert result is not None
    assert result.is_core is True


async def test_set_core_returns_none_for_wrong_tune(db: AsyncSession) -> None:
    tune_a = await create_tune(db, _tune_create(title="A"), abc_notation=ABC)
    tune_b = await create_tune(db, _tune_create(title="B"), abc_notation=ABC)
    loaded_b = await get_tune(db, tune_b.id)
    assert loaded_b is not None
    setting_b_id = loaded_b.settings[0].id
    result = await set_core_setting(db, tune_a.id, setting_b_id)
    assert result is None


async def test_set_core_returns_none_for_missing_setting(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    result = await set_core_setting(db, tune.id, 99999)
    assert result is None
