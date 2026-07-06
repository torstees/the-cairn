from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models_thesession_tunes import TheSessionAlias, TheSessionSetting, TheSessionTunePopularity
from scripts.import_thesession import (
    import_aliases,
    import_settings,
    import_tune_popularity,
    parse_alias_row,
    parse_setting_row,
    parse_tune_popularity_row,
)

_SETTING_ROW = {
    "tune_id": "1",
    "setting_id": "10",
    "name": "Cooley's",
    "type": "reel",
    "meter": "4/4",
    "mode": "Edorian",
    "abc": "|:D2 FA DFAd|",
    "date": "2016-03-31 15:34:45",
    "username": "danninagh",
    "composer": "",
}

_ALIAS_ROW = {"tune_id": "1", "alias": "Joe Cooley's", "name": "Cooley's"}

_POPULARITY_ROW = {"name": "Cooley's", "tune_id": "1", "tunebooks": "6676"}


# ── row parsing ─────────────────────────────────────────────────────────────


def test_parse_setting_row() -> None:
    parsed = parse_setting_row(_SETTING_ROW)
    assert parsed == {
        "setting_id": 10,
        "tune_id": 1,
        "name": "Cooley's",
        "tune_type_raw": "reel",
        "meter": "4/4",
        "mode_raw": "Edorian",
        "abc": "|:D2 FA DFAd|",
        "submitted_date": datetime(2016, 3, 31, 15, 34, 45),
        "username": "danninagh",
        "composer": None,
    }


def test_parse_setting_row_blank_date_and_username() -> None:
    row = {**_SETTING_ROW, "date": "", "username": "  "}
    parsed = parse_setting_row(row)
    assert parsed["submitted_date"] is None
    assert parsed["username"] is None


def test_parse_alias_row() -> None:
    assert parse_alias_row(_ALIAS_ROW) == {"tune_id": 1, "alias": "Joe Cooley's", "canonical_name": "Cooley's"}


def test_parse_tune_popularity_row() -> None:
    assert parse_tune_popularity_row(_POPULARITY_ROW) == {"tune_id": 1, "name": "Cooley's", "tunebooks": 6676}


# ── import (delete-all + bulk insert) ────────────────────────────────────────


async def test_import_settings_creates_rows(db: AsyncSession) -> None:
    count = await import_settings(db, [_SETTING_ROW])
    assert count == 1
    result = await db.execute(select(TheSessionSetting).where(TheSessionSetting.setting_id == 10))
    setting = result.scalar_one()
    assert setting.name == "Cooley's"
    assert setting.tune_type_raw == "reel"


async def test_import_settings_rerun_does_not_duplicate(db: AsyncSession) -> None:
    await import_settings(db, [_SETTING_ROW])
    await import_settings(db, [_SETTING_ROW])
    result = await db.execute(select(TheSessionSetting))
    assert len(result.scalars().all()) == 1


async def test_import_settings_rerun_drops_stale_rows(db: AsyncSession) -> None:
    other_row = {**_SETTING_ROW, "setting_id": "11", "tune_id": "2", "name": "The Kesh"}
    await import_settings(db, [_SETTING_ROW, other_row])
    # Second run's source no longer includes setting_id 11 — it should be gone, not leaked.
    await import_settings(db, [_SETTING_ROW])
    result = await db.execute(select(TheSessionSetting))
    remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].setting_id == 10


async def test_import_aliases_creates_rows(db: AsyncSession) -> None:
    count = await import_aliases(db, [_ALIAS_ROW])
    assert count == 1
    result = await db.execute(select(TheSessionAlias).where(TheSessionAlias.tune_id == 1))
    alias = result.scalar_one()
    assert alias.alias == "Joe Cooley's"
    assert alias.canonical_name == "Cooley's"


async def test_import_tune_popularity_creates_rows(db: AsyncSession) -> None:
    count = await import_tune_popularity(db, [_POPULARITY_ROW])
    assert count == 1
    result = await db.execute(select(TheSessionTunePopularity).where(TheSessionTunePopularity.tune_id == 1))
    popularity = result.scalar_one()
    assert popularity.tunebooks == 6676
