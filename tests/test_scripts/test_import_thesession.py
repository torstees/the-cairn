from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models_thesession_community import (
    TheSessionEvent,
    TheSessionRecording,
    TheSessionSet,
    TheSessionSetMember,
    TheSessionVenue,
)
from cairn.models_thesession_tunes import TheSessionAlias, TheSessionSetting, TheSessionTunePopularity
from scripts.import_thesession import (
    import_aliases,
    import_events,
    import_recordings,
    import_sets,
    import_settings,
    import_tune_popularity,
    import_venues,
    parse_alias_row,
    parse_event_row,
    parse_recording_row,
    parse_set_header_row,
    parse_set_member_row,
    parse_setting_row,
    parse_tune_popularity_row,
    parse_venue_row,
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

_SET_ROW_1 = {
    "tuneset": "1",
    "date": "2016-02-06 18:33:11",
    "member_id": "1",
    "username": "Jeremy",
    "settingorder": "1",
    "name": "Tarbolton, The",
    "tune_id": "560",
    "setting_id": "560",
    "type": "reel",
    "meter": "4/4",
    "mode": "Edorian",
    "abc": "|:D|Eeed e2 BA|",
}

_SET_ROW_2 = {
    **_SET_ROW_1,
    "settingorder": "2",
    "name": "The Longford Collector",
    "tune_id": "561",
    "setting_id": "561",
}

_RECORDING_ROW = {
    "id": "3720",
    "artist": "Dervish",  # real data: a name, not the bare numeric id the original spec assumed
    "recording": "Cast A Bell",
    "track": "1",
    "number": "1",
    "tune": "Kettledrum",
    "tune_id": "14408",
}

_VENUE_ROW = {
    "id": "6010",
    "name": "Sláinte Irish Pub",
    "address": "Av. San Martín 6066",
    "town": "Buenos Aires",
    "area": "Buenos Aires",
    "country": "Argentina",
    "latitude": "-34.59538269",
    "longitude": "-58.50145340",
    "date": "2016-06-07 15:57:16",
}

_EVENT_ROW = {
    "id": "11",
    "event": "Colm Gannon, Sean Mckeon And John Blake",
    "dtstart": "2006-06-07 09:30:00",
    "dtend": "2006-06-07 12:00:00",
    "venue": "The Goalpost",
    "address": "226 Water Street",
    "town": "Quincy",
    "area": "Massachusetts",
    "country": "USA",
    "latitude": "42.24073792",
    "longitude": "-71.00814819",
}


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


# ── community data (TODO 8.4) ─────────────────────────────────────────────────


def test_parse_set_header_row() -> None:
    parsed = parse_set_header_row(_SET_ROW_1)
    assert parsed == {
        "tuneset_id": 1,
        "submitted_date": datetime(2016, 2, 6, 18, 33, 11),
        "member_id": 1,
        "username": "Jeremy",
        "name": "Tarbolton, The",
    }


def test_parse_set_member_row() -> None:
    assert parse_set_member_row(_SET_ROW_1) == {
        "tuneset_id": 1,
        "position": 1,
        "tune_id": 560,
        "setting_id": 560,
    }


def test_parse_recording_row() -> None:
    assert parse_recording_row(_RECORDING_ROW) == {
        "recording_id": 3720,
        "artist": "Dervish",
        "recording_name": "Cast A Bell",
        "track_number": 1,
        "position": 1,
        "tune_name": "Kettledrum",
        "tune_id": 14408,
    }


def test_parse_recording_row_blank_tune_id() -> None:
    row = {**_RECORDING_ROW, "tune_id": ""}
    assert parse_recording_row(row)["tune_id"] is None


def test_parse_recording_row_legacy_numeric_artist() -> None:
    # A small fraction of real rows still hold a bare leftover numeric id
    # rather than a name -- stored as-is either way (faithful mirror).
    row = {**_RECORDING_ROW, "artist": "1651"}
    assert parse_recording_row(row)["artist"] == "1651"


def test_parse_venue_row() -> None:
    parsed = parse_venue_row(_VENUE_ROW)
    assert parsed == {
        "id": 6010,
        "name": "Sláinte Irish Pub",
        "address": "Av. San Martín 6066",
        "town": "Buenos Aires",
        "area": "Buenos Aires",
        "country": "Argentina",
        "latitude": -34.59538269,
        "longitude": -58.50145340,
        "submitted_date": datetime(2016, 6, 7, 15, 57, 16),
    }


def test_parse_event_row() -> None:
    parsed = parse_event_row(_EVENT_ROW)
    assert parsed == {
        "id": 11,
        "name": "Colm Gannon, Sean Mckeon And John Blake",
        "starts_at": datetime(2006, 6, 7, 9, 30, 0),
        "ends_at": datetime(2006, 6, 7, 12, 0, 0),
        "venue_name": "The Goalpost",
        "address": "226 Water Street",
        "town": "Quincy",
        "area": "Massachusetts",
        "country": "USA",
        "latitude": 42.24073792,
        "longitude": -71.00814819,
    }


async def test_import_sets_creates_deduplicated_header_and_all_members(db: AsyncSession) -> None:
    sets_count, members_count = await import_sets(db, [_SET_ROW_1, _SET_ROW_2])
    assert sets_count == 1
    assert members_count == 2

    result = await db.execute(select(TheSessionSet))
    sets = result.scalars().all()
    assert len(sets) == 1
    assert sets[0].tuneset_id == 1
    assert sets[0].username == "Jeremy"

    result = await db.execute(select(TheSessionSetMember).order_by(TheSessionSetMember.position))
    members = result.scalars().all()
    assert [m.tune_id for m in members] == [560, 561]
    assert [m.position for m in members] == [1, 2]


async def test_import_sets_rerun_does_not_duplicate(db: AsyncSession) -> None:
    await import_sets(db, [_SET_ROW_1, _SET_ROW_2])
    await import_sets(db, [_SET_ROW_1, _SET_ROW_2])
    result = await db.execute(select(TheSessionSet))
    assert len(result.scalars().all()) == 1
    result = await db.execute(select(TheSessionSetMember))
    assert len(result.scalars().all()) == 2


async def test_import_sets_rerun_drops_stale_rows(db: AsyncSession) -> None:
    other_set_row = {**_SET_ROW_1, "tuneset": "2", "name": "The Kesh"}
    await import_sets(db, [_SET_ROW_1, other_set_row])
    await import_sets(db, [_SET_ROW_1])
    result = await db.execute(select(TheSessionSet))
    remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].tuneset_id == 1


async def test_import_recordings_creates_rows(db: AsyncSession) -> None:
    count = await import_recordings(db, [_RECORDING_ROW])
    assert count == 1
    result = await db.execute(select(TheSessionRecording).where(TheSessionRecording.recording_id == 3720))
    recording = result.scalar_one()
    assert recording.recording_name == "Cast A Bell"
    assert recording.tune_id == 14408


async def test_import_recordings_allows_duplicate_recording_id(db: AsyncSession) -> None:
    # recording_id repeats across tracks of the same recording -- not unique per row.
    second_track = {**_RECORDING_ROW, "track": "2", "tune": "Maiden Lane", "tune_id": "13727"}
    count = await import_recordings(db, [_RECORDING_ROW, second_track])
    assert count == 2
    result = await db.execute(select(TheSessionRecording).where(TheSessionRecording.recording_id == 3720))
    assert len(result.scalars().all()) == 2


async def test_import_venues_creates_rows(db: AsyncSession) -> None:
    count = await import_venues(db, [_VENUE_ROW])
    assert count == 1
    result = await db.execute(select(TheSessionVenue).where(TheSessionVenue.id == 6010))
    venue = result.scalar_one()
    assert venue.name == "Sláinte Irish Pub"
    assert venue.country == "Argentina"


async def test_import_events_creates_rows(db: AsyncSession) -> None:
    count = await import_events(db, [_EVENT_ROW])
    assert count == 1
    result = await db.execute(select(TheSessionEvent).where(TheSessionEvent.id == 11))
    event = result.scalar_one()
    assert event.venue_name == "The Goalpost"
    assert event.starts_at == datetime(2006, 6, 7, 9, 30, 0)
