from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, KeyMode, KeyRoot, PracticeListType, Role, TuneType, User
from cairn.routers.tunes import _STUB_USER_ID
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.boxes import add_tune, create_box, get_box_entry, set_preferred_setting
from cairn.services.lists import add_tune_to_list, create_list, get_list_entry
from cairn.services.tunes import add_alias, create_setting, create_tune

_ABC = "X:1\nT:x\nK:D\n|:DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA:|"


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


async def _seed_user(db: AsyncSession) -> User:
    u = User(username="tester", email="t@example.com", hashed_password="x", role=Role.student)
    db.add(u)
    await db.flush()
    assert u.id == _STUB_USER_ID
    return u


async def test_tune_list_renders(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get("/tunes/")
    assert resp.status_code == 200
    assert tune.title in resp.text


async def test_tune_list_includes_abc_hover_preview(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get("/tunes/")
    assert resp.status_code == 200
    assert f'data-abc-preview-id="{tune.id}"' in resp.text
    marker = f'<template id="tune-abc-preview-{tune.id}">'
    assert marker in resp.text
    preview = resp.text.split(marker, 1)[1].split("</template>", 1)[0]
    # Only the first four bars should be present, not the closing repeat.
    assert preview.count("|") == 5
    assert "DEFA BAFA:|" not in preview


async def test_tune_list_shows_all_aliases_when_five_or_fewer(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    # Tune.aliases is ordered by sort_name, which strips a leading article —
    # "The Dawn Air" sorts as "Dawn Air", ahead of "Morning Star".
    for name in ["Morning Star", "The Dawn Air", "Sunrise Reel"]:
        await add_alias(db, tune.id, name)

    resp = await client.get("/tunes/")
    assert resp.status_code == 200
    assert "Also known as: The Dawn Air, Morning Star, Sunrise Reel" in resp.text
    assert "hellip" not in resp.text  # no truncation, no tooltip needed
    assert "group-hover:block" not in resp.text


async def test_tune_list_truncates_aliases_with_hover_tooltip(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    names = [f"Alias {n}" for n in range(1, 8)]  # 7 aliases, over the 5-shown cap
    for name in names:
        await add_alias(db, tune.id, name)

    resp = await client.get("/tunes/")
    assert resp.status_code == 200
    # Only the first 5 are shown inline, followed by an ellipsis — the visible
    # summary line ends at "&hellip;</span>", before the hidden tooltip span.
    shown = ", ".join(names[:5])
    marker = f"Also known as: {shown}&hellip;"
    assert marker in resp.text
    visible_summary = resp.text.split(marker, 1)[1].split("</span>", 1)[0]
    assert "Alias 6" not in visible_summary
    assert "Alias 7" not in visible_summary
    # The hover tooltip carries the full list, including the truncated tail.
    assert "group-hover:block" in resp.text
    tooltip = resp.text.split("group-hover:block", 1)[1]
    assert "Alias 6" in tooltip
    assert "Alias 7" in tooltip


async def test_tune_detail_shows_add_form_for_box_not_containing_tune(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "Session Box" in resp.text
    assert f'hx-post="/tunes/{tune.id}/boxes"' in resp.text
    assert f'<input type="hidden" name="box_id" value="{box.id}">' in resp.text


async def test_tune_detail_shows_membership_for_box_containing_tune(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})
    assert resp.status_code == 200

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "Core setting" in resp.text
    assert f'hx-post="/tunes/{tune.id}/boxes/{box.id}/setting"' not in resp.text  # no non-core settings yet
    assert f'href="/boxes/{box.id}"' in resp.text


async def test_tune_detail_breadcrumbs_to_progress_when_from_progress(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}", params={"from": "progress"})
    assert resp.status_code == 200
    assert 'href="/progress"' in resp.text
    assert '&larr; Progress' in resp.text
    assert '&larr; Tunes' not in resp.text


async def test_tune_detail_box_breadcrumb_outranks_from_progress(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})

    resp = await client.get(f"/tunes/{tune.id}", params={"box_id": box.id, "from": "progress"})
    assert resp.status_code == 200
    assert f'href="/boxes/{box.id}"' in resp.text
    assert '&larr; Progress' not in resp.text


async def test_tune_detail_no_from_param_still_breadcrumbs_to_tunes(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert '&larr; Tunes' in resp.text


async def test_tune_detail_breadcrumbs_to_list_when_list_id_given(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, _STUB_USER_ID, box.id, "Weekly Session", PracticeListType.repertoire)
    await add_tune_to_list(db, practice_list.id, tune.id)

    resp = await client.get(f"/tunes/{tune.id}", params={"list_id": practice_list.id})
    assert resp.status_code == 200
    assert f'href="/lists/{practice_list.id}"' in resp.text
    assert "Weekly Session" in resp.text
    assert '&larr; Tunes' not in resp.text


async def test_tune_detail_uses_list_setting_override(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, _STUB_USER_ID, box.id, "Weekly Session", PracticeListType.repertoire)
    setting = await create_setting(
        db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ABC, instrument=Instrument.fiddle)
    )
    await add_tune_to_list(db, practice_list.id, tune.id, setting_id=setting.id)

    resp = await client.get(f"/tunes/{tune.id}", params={"list_id": practice_list.id})
    assert resp.status_code == 200
    assert f'window.__cairnActiveSettingId = {setting.id};' in resp.text


async def test_tune_detail_list_setting_outranks_box_setting(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, _STUB_USER_ID, box.id, "Weekly Session", PracticeListType.repertoire)
    box_setting = await create_setting(
        db,
        tune.id,
        TuneSettingCreate(tune_id=tune.id, label="Box Alt", abc_notation=_ABC, instrument=Instrument.fiddle),
    )
    list_setting = await create_setting(
        db,
        tune.id,
        TuneSettingCreate(tune_id=tune.id, label="List Alt", abc_notation=_ABC, instrument=Instrument.flute),
    )
    await add_tune(db, box.id, tune.id)
    await set_preferred_setting(db, box.id, tune.id, box_setting.id)
    await add_tune_to_list(db, practice_list.id, tune.id, setting_id=list_setting.id)

    resp = await client.get(f"/tunes/{tune.id}", params={"box_id": box.id, "list_id": practice_list.id})
    assert resp.status_code == 200
    assert f'window.__cairnActiveSettingId = {list_setting.id};' in resp.text


async def test_tune_add_to_box(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])

    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})
    assert resp.status_code == 200
    assert "Session Box" in resp.text

    entry = await get_box_entry(db, box.id, tune.id)
    assert entry is not None


async def test_tune_add_to_box_with_setting(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    setting = await create_setting(
        db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ABC, instrument=Instrument.fiddle)
    )

    resp = await client.post(
        f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id), "setting_id": str(setting.id)}
    )
    assert resp.status_code == 200

    entry = await get_box_entry(db, box.id, tune.id)
    assert entry is not None
    assert entry.setting_id == setting.id


async def test_tune_add_to_box_also_adds_to_list(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, _STUB_USER_ID, box.id, "Weekly Session", PracticeListType.repertoire)

    resp = await client.post(
        f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id), "list_id": str(practice_list.id)}
    )
    assert resp.status_code == 200

    box_entry = await get_box_entry(db, box.id, tune.id)
    list_entry = await get_list_entry(db, practice_list.id, tune.id)
    assert box_entry is not None
    assert list_entry is not None


async def test_tune_add_to_box_duplicate_conflicts(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})

    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})
    assert resp.status_code == 409


async def test_tune_add_to_box_404_for_unknown_tune(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    resp = await client.post("/tunes/9999/boxes", data={"box_id": str(box.id)})
    assert resp.status_code == 404


async def test_tune_update_box_setting(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    setting = await create_setting(
        db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ABC, instrument=Instrument.fiddle)
    )
    await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})

    resp = await client.post(
        f"/tunes/{tune.id}/boxes/{box.id}/setting", data={"setting_id": str(setting.id)}
    )
    assert resp.status_code == 200
    assert "Alt" in resp.text

    entry = await get_box_entry(db, box.id, tune.id)
    assert entry is not None
    assert entry.setting_id == setting.id


async def test_tune_update_box_setting_404_for_tune_not_in_box(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    # never added to the box
    resp = await client.post(f"/tunes/{tune.id}/boxes/{box.id}/setting", data={"setting_id": ""})
    assert resp.status_code == 404


async def test_tune_add_to_box_explicit_core_overrides_auto_pick(client: AsyncClient, db: AsyncSession) -> None:
    # The box's single fiddle instrument uniquely matches this non-core setting,
    # so add_tune()'s own heuristic would auto-select it — but the user
    # explicitly chose "Core setting" (setting_id="") in the add form, which
    # must win over that heuristic.
    await _seed_user(db)
    tune = await _seed_tune(db)
    box = await create_box(db, _STUB_USER_ID, "Session Box", [Instrument.fiddle])
    await create_setting(
        db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ABC, instrument=Instrument.fiddle)
    )

    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id), "setting_id": ""})
    assert resp.status_code == 200

    entry = await get_box_entry(db, box.id, tune.id)
    assert entry is not None
    assert entry.setting_id is None
