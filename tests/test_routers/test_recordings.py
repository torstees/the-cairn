from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, TuneType
from cairn.models_thesession_community import TheSessionRecording
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.recordings import add_reference, create_recording, list_recordings
from cairn.services.tune_sets import create_set
from cairn.services.tunes import create_setting, create_tune, get_tune

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
    return await get_tune(db, created.id)


# ── create for a tune setting ────────────────────────────────────────────────


async def test_recording_create_new_for_setting(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    resp = await client.post(
        f"/recordings/tunes/{tune.id}",
        data={
            "setting_id": str(core.id),
            "artist": "Kevin Burke",
            "title": "Sweeney's Dream",
            "link_youtube": "https://youtu.be/example",
        },
    )
    assert resp.status_code == 200
    assert "Kevin Burke" in resp.text
    assert "Sweeney" in resp.text
    assert "youtube" in resp.text


async def test_recording_create_picks_existing_for_setting(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    recording = await create_recording(db, "Dervish", "Live in Palma")
    resp = await client.post(
        f"/recordings/tunes/{tune.id}",
        data={"setting_id": str(core.id), "recording_id": str(recording.id)},
    )
    assert resp.status_code == 200
    assert "Dervish" in resp.text

    # Pick the same existing recording again (e.g. for a second setting) --
    # no second Recording row should have been created for the same pick.
    await client.post(
        f"/recordings/tunes/{tune.id}",
        data={"setting_id": str(core.id), "recording_id": str(recording.id)},
    )
    all_recordings = await list_recordings(db)
    assert len(all_recordings) == 1


async def test_recording_create_missing_setting_shows_error(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _tune(db)
    resp = await client.post(
        f"/recordings/tunes/{tune.id}",
        data={"setting_id": "", "artist": "Kevin Burke", "title": "Sweeney's Dream"},
    )
    assert resp.status_code == 200
    assert "Pick which setting" in resp.text


async def test_recording_create_neither_pick_nor_new_shows_error(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    resp = await client.post(f"/recordings/tunes/{tune.id}", data={"setting_id": str(core.id)})
    assert resp.status_code == 200
    assert "Pick an existing recording" in resp.text


async def test_recording_create_404_for_unknown_tune(client: AsyncClient) -> None:
    resp = await client.post("/recordings/tunes/9999", data={"setting_id": "1", "artist": "x", "title": "y"})
    assert resp.status_code == 404


# ── create for a tune set ────────────────────────────────────────────────────


async def test_recording_create_new_for_set(client: AsyncClient, db: AsyncSession) -> None:
    tune_set = await create_set(db, title="Evening Jigs")
    resp = await client.post(
        f"/recordings/sets/{tune_set.id}",
        data={"artist": "Altan", "title": "Island Angel"},
    )
    assert resp.status_code == 200
    assert "Altan" in resp.text


async def test_recording_create_404_for_unknown_set(client: AsyncClient) -> None:
    resp = await client.post("/recordings/sets/9999", data={"artist": "x", "title": "y"})
    assert resp.status_code == 404


# ── update (edit) ─────────────────────────────────────────────────────────────


async def test_recording_reference_update_edits_artist_and_title(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    reference = await add_reference(db, recording.id, setting_id=core.id)

    resp = await client.post(
        f"/recordings/references/{reference.id}",
        data={"setting_id": str(core.id), "artist": "Kevin Burke Band", "title": "Sweeney's Dream (Live)"},
    )
    assert resp.status_code == 200
    assert "Kevin Burke Band" in resp.text
    assert "Sweeney's Dream (Live)" in resp.text


async def test_recording_reference_update_repoints_to_different_setting(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    other_setting = await create_setting(
        db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation="|:GABc defg|GABc defg:|")
    )
    # This test's fixture shares one AsyncSession across setup and the
    # simulated HTTP request, unlike production (a fresh session per
    # request) -- tune.settings was already eager-loaded before the second
    # setting existed, and selectinload doesn't refresh an already-loaded
    # collection on the same identity-mapped object. Expire it so the
    # route's own get_tune() call sees both settings, matching what a real,
    # separate request would see.
    db.expire(tune, ["settings"])
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    reference = await add_reference(db, recording.id, setting_id=core.id)

    resp = await client.post(
        f"/recordings/references/{reference.id}",
        data={"setting_id": str(other_setting.id)},
    )
    assert resp.status_code == 200
    assert "Alt" in resp.text


async def test_recording_reference_update_for_set(client: AsyncClient, db: AsyncSession) -> None:
    tune_set = await create_set(db, title="Evening Jigs")
    recording = await create_recording(db, "Dervish", "Live in Palma")
    reference = await add_reference(db, recording.id, set_id=tune_set.id)

    resp = await client.post(
        f"/recordings/references/{reference.id}",
        data={"artist": "Dervish", "title": "Live in Palma (Remastered)"},
    )
    assert resp.status_code == 200
    assert "Remastered" in resp.text


async def test_recording_reference_update_404_for_unknown_id(client: AsyncClient) -> None:
    resp = await client.post("/recordings/references/9999", data={})
    assert resp.status_code == 404


async def test_unauthenticated_update_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.post("/recordings/references/1", data={}, follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("/auth/login")


# ── delete ────────────────────────────────────────────────────────────────────


async def test_recording_reference_delete_for_setting(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    reference = await add_reference(db, recording.id, setting_id=core.id)

    resp = await client.delete(f"/recordings/references/{reference.id}")
    assert resp.status_code == 200
    assert "No recordings tagged yet" in resp.text


async def test_recording_reference_delete_for_set(client: AsyncClient, db: AsyncSession) -> None:
    tune_set = await create_set(db, title="Evening Jigs")
    recording = await create_recording(db, "Altan", "Island Angel")
    reference = await add_reference(db, recording.id, set_id=tune_set.id)

    resp = await client.delete(f"/recordings/references/{reference.id}")
    assert resp.status_code == 200
    assert "No recordings tagged yet" in resp.text


async def test_recording_reference_delete_404_for_unknown_id(client: AsyncClient) -> None:
    resp = await client.delete("/recordings/references/9999")
    assert resp.status_code == 404


# ── guest safety on the pages themselves (see #225) ──────────────────────────


async def test_guest_views_tune_detail_with_recordings_no_crash(
    unauthenticated_client: AsyncClient, db: AsyncSession
) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    recording = await create_recording(db, "Kevin Burke", "Sweeney's Dream")
    await add_reference(db, recording.id, setting_id=core.id)

    resp = await unauthenticated_client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "Kevin Burke" in resp.text


async def test_guest_views_set_detail_with_recordings_no_crash(
    unauthenticated_client: AsyncClient, db: AsyncSession
) -> None:
    tune_set = await create_set(db, title="Evening Jigs")
    recording = await create_recording(db, "Altan", "Island Angel")
    await add_reference(db, recording.id, set_id=tune_set.id)

    resp = await unauthenticated_client.get(f"/sets/{tune_set.id}")
    assert resp.status_code == 200
    assert "Altan" in resp.text


async def test_unauthenticated_create_redirects_to_login(unauthenticated_client: AsyncClient, db: AsyncSession) -> None:
    tune = await _tune(db)
    core = tune.settings[0]
    resp = await unauthenticated_client.post(
        f"/recordings/tunes/{tune.id}",
        data={"setting_id": str(core.id), "artist": "x", "title": "y"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("/auth/login")


async def test_unauthenticated_delete_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.delete("/recordings/references/1", follow_redirects=False)
    assert resp.status_code == 307


# ── TheSession recording suggestions (#188) ──────────────────────────────────


async def test_tune_detail_shows_thesession_suggestion_when_linked(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _tune(db)
    tune.thesession_tune_id = 14408
    await db.commit()
    db.add(
        TheSessionRecording(
            recording_id=3720,
            artist="Dervish",
            recording_name="Cast A Bell",
            track_number=1,
            position=1,
            tune_name="Kettledrum",
            tune_id=14408,
        )
    )
    await db.commit()

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "Cast A Bell (track 1)" in resp.text


async def test_tune_detail_no_suggestions_when_not_linked(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _tune(db)
    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert '"thesession-recording-suggestions">[]' in resp.text
