import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, TuneType
from cairn.models_thesession_community import TheSessionRecording
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.recordings import (
    add_reference,
    create_recording,
    list_recordings,
    list_recordings_for_set,
    list_recordings_for_setting,
    list_recordings_for_tune,
    recordings_to_json,
    remove_reference,
    thesession_suggestions_json,
    update_recording,
    update_reference,
)
from cairn.services.tune_sets import create_set
from cairn.services.tunes import create_setting, create_tune, get_tune


async def _thesession_recording(db: AsyncSession, **overrides) -> TheSessionRecording:
    defaults = {
        "recording_id": 3720,
        "artist": "Dervish",
        "recording_name": "Cast A Bell",
        "track_number": 1,
        "position": 1,
        "tune_name": "Kettledrum",
        "tune_id": 14408,
    }
    defaults.update(overrides)
    row = TheSessionRecording(**defaults)
    db.add(row)
    await db.flush()
    return row


_ABC = "X:1\nT:x\nK:D\n|:DEFA BAFA|DEFA BAFA:|"


async def _tune(db: AsyncSession):
    created = await create_tune(
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
    # create_tune()'s own object doesn't eager-load .settings -- re-fetch via
    # get_tune() (which does) before touching that relationship.
    return await get_tune(db, created.id)


# ── create_recording / list_recordings ──────────────────────────────────────


async def test_create_recording(db: AsyncSession) -> None:
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream", {"youtube": "https://youtu.be/x"})
    assert recording.artist == "Kevin Burke"
    assert recording.title == "Sweeney's Dream"
    assert recording.links == {"youtube": "https://youtu.be/x"}


async def test_create_recording_no_links(db: AsyncSession) -> None:
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    assert recording.links is None


async def test_list_recordings_ordered_by_artist_then_title(db: AsyncSession) -> None:
    await create_recording(db, "Dervish", "Live in Palma")
    await create_recording(db, "Altan", "Island Angel")
    result = await list_recordings(db)
    assert [r.artist for r in result] == ["Altan", "Dervish"]


def test_recordings_to_json_shape() -> None:
    class _Fake:
        def __init__(self, id, artist, title):
            self.id, self.artist, self.title = id, artist, title

    result = recordings_to_json([_Fake(1, "Altan", "Island Angel")])
    assert result == '[{"id": 1, "artist": "Altan", "title": "Island Angel", "label": "Altan \\u2014 Island Angel"}]'


# ── add_reference ────────────────────────────────────────────────────────────


async def test_add_reference_to_setting(db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    reference = await add_reference(db, recording.id, setting_id=core.id, track_number=3, position=None)
    assert reference.setting_id == core.id
    assert reference.set_id is None
    assert reference.track_number == 3


async def test_add_reference_to_set(db: AsyncSession) -> None:
    tune_set = await create_set(db, title="Evening Jigs")
    recording = await create_recording(db, "Dervish", "Live in Palma")
    reference = await add_reference(db, recording.id, set_id=tune_set.id)
    assert reference.set_id == tune_set.id
    assert reference.setting_id is None


async def test_add_reference_requires_exactly_one_target(db: AsyncSession) -> None:
    recording = await create_recording(db, "Dervish", "Live in Palma")
    with pytest.raises(ValueError, match="Exactly one"):
        await add_reference(db, recording.id)


async def test_add_reference_rejects_both_targets(db: AsyncSession) -> None:
    tune = await _tune(db)
    tune_set = await create_set(db, title="Evening Jigs")
    recording = await create_recording(db, "Dervish", "Live in Palma")
    with pytest.raises(ValueError, match="Exactly one"):
        await add_reference(db, recording.id, setting_id=tune.settings[0].id, set_id=tune_set.id)


# ── list_recordings_for_setting / list_recordings_for_set / list_recordings_for_tune ──


async def test_list_recordings_for_setting(db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    await add_reference(db, recording.id, setting_id=core.id)

    result = await list_recordings_for_setting(db, core.id)
    assert len(result) == 1
    assert result[0].recording.artist == "Kevin Burke"


async def test_list_recordings_for_set(db: AsyncSession) -> None:
    tune_set = await create_set(db, title="Evening Jigs")
    recording = await create_recording(db, "Dervish", "Live in Palma")
    await add_reference(db, recording.id, set_id=tune_set.id)

    result = await list_recordings_for_set(db, tune_set.id)
    assert len(result) == 1
    assert result[0].recording.title == "Live in Palma"


async def test_list_recordings_for_tune_spans_all_settings(db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    await add_reference(db, recording.id, setting_id=core.id)

    result = await list_recordings_for_tune(db, [s.id for s in tune.settings])
    assert len(result) == 1


async def test_list_recordings_for_tune_empty_setting_ids(db: AsyncSession) -> None:
    assert await list_recordings_for_tune(db, []) == []


# ── remove_reference ──────────────────────────────────────────────────────────


async def test_remove_reference(db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    reference = await add_reference(db, recording.id, setting_id=core.id)

    assert await remove_reference(db, reference.id) is True
    assert await list_recordings_for_setting(db, core.id) == []


async def test_remove_reference_unknown_id_returns_false(db: AsyncSession) -> None:
    assert await remove_reference(db, 9999) is False


async def test_remove_reference_does_not_delete_recording_with_other_references(db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    tune_set = await create_set(db, title="Evening Jigs")
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    ref1 = await add_reference(db, recording.id, setting_id=core.id)
    await add_reference(db, recording.id, set_id=tune_set.id)

    await remove_reference(db, ref1.id)
    result = await list_recordings(db)
    assert len(result) == 1
    assert (await list_recordings_for_set(db, tune_set.id))[0].recording.id == recording.id


# ── update_recording / update_reference ──────────────────────────────────────


async def test_update_recording(db: AsyncSession) -> None:
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    updated = await update_recording(db, recording.id, "Kevin Burke Band", "Sweeney's Dream (Live)", {"youtube": "x"})
    assert updated is not None
    assert updated.artist == "Kevin Burke Band"
    assert updated.title == "Sweeney's Dream (Live)"
    assert updated.links == {"youtube": "x"}


async def test_update_recording_unknown_id_returns_none(db: AsyncSession) -> None:
    assert await update_recording(db, 9999, "x", "y") is None


async def test_update_recording_applies_to_every_reference(db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    tune_set = await create_set(db, title="Evening Jigs")
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    await add_reference(db, recording.id, setting_id=core.id)
    await add_reference(db, recording.id, set_id=tune_set.id)

    await update_recording(db, recording.id, "Kevin Burke Band", "Sweeney's Dream (Live)")

    setting_refs = await list_recordings_for_setting(db, core.id)
    set_refs = await list_recordings_for_set(db, tune_set.id)
    assert setting_refs[0].recording.artist == "Kevin Burke Band"
    assert set_refs[0].recording.artist == "Kevin Burke Band"


async def test_update_reference_track_number_and_position(db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    reference = await add_reference(db, recording.id, setting_id=core.id)

    updated = await update_reference(db, reference.id, track_number=4, position=2)
    assert updated is not None
    assert updated.track_number == 4
    assert updated.position == 2


async def test_update_reference_repoints_to_different_setting_of_same_tune(db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    other_setting = await create_setting(
        db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation="|:GABc defg|GABc defg:|")
    )
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    reference = await add_reference(db, recording.id, setting_id=core.id)

    updated = await update_reference(db, reference.id, setting_id=other_setting.id)
    assert updated.setting_id == other_setting.id
    assert await list_recordings_for_setting(db, core.id) == []
    assert len(await list_recordings_for_setting(db, other_setting.id)) == 1


async def test_update_reference_ignores_setting_id_for_set_scoped_reference(db: AsyncSession) -> None:
    tune_set = await create_set(db, title="Evening Jigs")
    recording = await create_recording(db, "Dervish", "Live in Palma")
    reference = await add_reference(db, recording.id, set_id=tune_set.id)

    updated = await update_reference(db, reference.id, setting_id=999, track_number=1)
    assert updated.setting_id is None
    assert updated.set_id == tune_set.id
    assert updated.track_number == 1


async def test_update_reference_unknown_id_returns_none(db: AsyncSession) -> None:
    assert await update_reference(db, 9999, track_number=1) is None


# ── thesession_suggestions_json ──────────────────────────────────────────────


async def test_thesession_suggestions_json_no_thesession_tune_id(db: AsyncSession) -> None:
    assert await thesession_suggestions_json(db, None) == "[]"


async def test_thesession_suggestions_json_none_matching(db: AsyncSession) -> None:
    await _thesession_recording(db, tune_id=14408)
    assert await thesession_suggestions_json(db, 99999) == "[]"


async def test_thesession_suggestions_json_includes_artist_when_a_name(db: AsyncSession) -> None:
    await _thesession_recording(db, tune_id=14408, artist="Dervish", recording_name="Cast A Bell", track_number=1)
    result = json.loads(await thesession_suggestions_json(db, 14408))
    assert len(result) == 1
    item = result[0]
    assert item["artist"] == "Dervish"
    assert item["title"] == "Cast A Bell"
    assert item["track_number"] == 1
    assert item["position"] == 1
    assert item["label"] == "Cast A Bell (track 1)"
    assert "Dervish" in item["tooltip"]
    assert "Cast A Bell" in item["tooltip"]


async def test_thesession_suggestions_json_tooltip_unknown_artist(db: AsyncSession) -> None:
    await _thesession_recording(db, tune_id=14408, artist="1651")
    item = json.loads(await thesession_suggestions_json(db, 14408))[0]
    assert "Unknown artist" in item["tooltip"]


async def test_thesession_suggestions_json_blanks_legacy_numeric_artist(db: AsyncSession) -> None:
    await _thesession_recording(db, tune_id=14408, artist="1651")
    result = json.loads(await thesession_suggestions_json(db, 14408))
    assert result[0]["artist"] == ""


async def test_thesession_suggestions_json_multiple_tracks(db: AsyncSession) -> None:
    await _thesession_recording(db, tune_id=14408, track_number=1, tune_name="Kettledrum")
    await _thesession_recording(db, tune_id=14408, track_number=2, tune_name="Maiden Lane")
    result = json.loads(await thesession_suggestions_json(db, 14408))
    assert len(result) == 2
