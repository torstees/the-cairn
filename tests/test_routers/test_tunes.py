from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    ContentVisibility,
    Instrument,
    KeyMode,
    KeyRoot,
    PracticeListType,
    Role,
    Tune,
    TuneSetting,
    TuneType,
    User,
)
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.boxes import add_tune, create_box, get_box_entry, set_display_alias, set_preferred_setting
from cairn.services.lists import add_tune_to_list, create_list, get_list_entry, update_list_entry_display_alias
from cairn.services.tune_sets import create_set, set_members
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
    assert f'<template id="tune-abc-preview-{tune.id}">' in resp.text


async def test_tune_list_hover_preview_trigger_is_preview_cell_not_row_or_title(
    client: AsyncClient, db: AsyncSession
) -> None:
    tune = await _seed_tune(db)
    resp = await client.get("/tunes/")
    assert resp.status_code == 200

    li_open = resp.text.split("<li ", 1)[1].split(">", 1)[0]
    assert "data-abc-preview-id" not in li_open

    a_open = resp.text.split(f'<a href="/tunes/{tune.id}"', 1)[1].split(">", 1)[0]
    assert "data-abc-preview-id" not in a_open

    canvas_open = resp.text.split(f'id="tune-abc-col-canvas-{tune.id}"', 1)[1].split(">", 1)[0]
    assert f'data-abc-preview-id="{tune.id}"' in canvas_open
    assert 'data-abc-preview-delay="300"' in canvas_open


async def test_tune_column_preview_is_shorter_than_popup_preview(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get("/tunes/")
    assert resp.status_code == 200

    col_marker = f'<template id="tune-abc-col-{tune.id}">'
    col = resp.text.split(col_marker, 1)[1].split("</template>", 1)[0]
    popup_marker = f'<template id="tune-abc-preview-{tune.id}">'
    popup = resp.text.split(popup_marker, 1)[1].split("</template>", 1)[0]

    assert col != popup
    assert len(col) < len(popup)
    assert "DEFA BAFA:|" in popup
    assert "DEFA BAFA:|" not in col


async def test_tune_row_has_overflow_menu_with_edit_and_delete(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get("/tunes/")
    assert resp.status_code == 200
    assert 'role="menu"' in resp.text
    assert f'href="/tunes/{tune.id}/edit"' in resp.text
    assert f'hx-delete="/tunes/{tune.id}"' in resp.text


async def test_tune_list_alias_hover_does_not_trigger_abc_preview(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    await add_alias(db, tune.id, "Sunrise Reel")
    resp = await client.get("/tunes/")
    assert resp.status_code == 200

    alias_open = resp.text.split('class="relative inline-block group"', 1)[1].split(">", 1)[0]
    assert 'data-abc-preview-id=""' in alias_open


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


async def test_tune_detail_shows_add_form_for_box_not_containing_tune(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "Session Box" in resp.text
    assert f'hx-post="/tunes/{tune.id}/boxes"' in resp.text
    assert f'<input type="hidden" name="box_id" value="{box.id}">' in resp.text


async def test_tune_detail_shows_membership_for_box_containing_tune(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})
    assert resp.status_code == 200

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "Core setting" in resp.text
    assert f'hx-post="/tunes/{tune.id}/boxes/{box.id}/setting"' not in resp.text  # no non-core settings yet
    assert f'href="/boxes/{box.id}"' in resp.text


async def test_tune_detail_shows_sets_it_belongs_to(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    tune_set = await create_set(db, title="Evening Reels")
    await set_members(db, tune_set.id, [{"tune_id": tune.id, "setting_id": None}])

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "Evening Reels" in resp.text
    assert f'href="/sets/{tune_set.id}"' in resp.text


async def test_tune_detail_no_sets_message_when_not_a_member(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "Not part of any sets yet." in resp.text


async def test_tune_detail_breadcrumbs_to_progress_when_from_progress(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}", params={"from": "progress"})
    assert resp.status_code == 200
    assert 'href="/progress"' in resp.text
    assert "&larr; Progress" in resp.text
    assert "&larr; Tunes" not in resp.text


async def test_tune_detail_box_breadcrumb_outranks_from_progress(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})

    resp = await client.get(f"/tunes/{tune.id}", params={"box_id": box.id, "from": "progress"})
    assert resp.status_code == 200
    assert f'href="/boxes/{box.id}"' in resp.text
    assert "&larr; Progress" not in resp.text


async def test_tune_detail_no_from_param_still_breadcrumbs_to_tunes(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "&larr; Tunes" in resp.text


async def test_tune_detail_breadcrumbs_to_list_when_list_id_given(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, user.id, box.id, "Weekly Session", PracticeListType.repertoire)
    await add_tune_to_list(db, practice_list.id, tune.id)

    resp = await client.get(f"/tunes/{tune.id}", params={"list_id": practice_list.id})
    assert resp.status_code == 200
    assert f'href="/lists/{practice_list.id}"' in resp.text
    assert "Weekly Session" in resp.text
    assert "&larr; Tunes" not in resp.text


async def test_tune_detail_uses_list_setting_override(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, user.id, box.id, "Weekly Session", PracticeListType.repertoire)
    setting = await create_setting(
        db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ABC, instrument=Instrument.fiddle)
    )
    await add_tune_to_list(db, practice_list.id, tune.id, setting_id=setting.id)

    resp = await client.get(f"/tunes/{tune.id}", params={"list_id": practice_list.id})
    assert resp.status_code == 200
    assert f"window.__cairnActiveSettingId = {setting.id};" in resp.text


async def test_tune_detail_list_setting_outranks_box_setting(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, user.id, box.id, "Weekly Session", PracticeListType.repertoire)
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
    assert f"window.__cairnActiveSettingId = {list_setting.id};" in resp.text


async def test_tune_detail_key_shifts_to_shortest_route(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)  # D major
    resp = await client.get(f"/tunes/{tune.id}", params={"key": "E"})
    assert resp.status_code == 200
    assert "K:E" in resp.text
    assert "EFGB" in resp.text  # D transposed +2 -> E, per the source's "DEFA" opening
    assert "transposed +2 semitones" in resp.text


async def test_tune_detail_key_picks_down_when_shorter(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)  # D major
    resp = await client.get(f"/tunes/{tune.id}", params={"key": "B"})
    assert resp.status_code == 200
    assert "K:B" in resp.text
    assert "transposed -3 semitones" in resp.text  # D -> B is shorter down (-3) than up (+9)


async def test_tune_detail_no_key_or_octave_is_untransposed(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "K:D" in resp.text
    assert "transposed" not in resp.text


async def test_tune_detail_selecting_own_key_is_untransposed(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)  # D major
    resp = await client.get(f"/tunes/{tune.id}", params={"key": "D"})
    assert resp.status_code == 200
    assert "transposed" not in resp.text


async def test_tune_detail_key_options_list_highest_root_first(client: AsyncClient, db: AsyncSession) -> None:
    # Scrolling toward the top of the dropdown should move to higher keys —
    # B (highest of the 14 roots) listed before C (lowest).
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert resp.text.index("key=B&amp;octave=0") < resp.text.index("key=C&amp;octave=0")


async def test_tune_detail_octave_up_shifts_a_full_octave_same_key(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)  # D major
    resp = await client.get(f"/tunes/{tune.id}", params={"octave": 1})
    assert resp.status_code == 200
    assert "K:D" in resp.text  # root/mode unchanged — only the octave shifted
    assert "transposed +12 semitones" in resp.text


async def test_tune_detail_octave_clamped_to_plus_minus_1(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}", params={"octave": 5})
    assert resp.status_code == 200
    assert "transposed +12 semitones" in resp.text  # clamped from 5 to 1 octave


async def test_tune_detail_key_and_octave_combine(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)  # D major
    resp = await client.get(f"/tunes/{tune.id}", params={"key": "E", "octave": 1})
    assert resp.status_code == 200
    assert "K:E" in resp.text
    assert "transposed +14 semitones" in resp.text  # +2 (key) + 12 (octave)


async def test_tune_detail_reset_link_only_shown_when_transposed(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert ">Reset<" not in resp.text

    resp = await client.get(f"/tunes/{tune.id}", params={"octave": 1})
    assert resp.status_code == 200
    assert ">Reset<" in resp.text


async def test_tune_detail_octave_links_preserve_selected_key(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)  # D major
    resp = await client.get(f"/tunes/{tune.id}", params={"key": "E", "octave": 0})
    assert resp.status_code == 200
    assert "key=E&amp;octave=1" in resp.text
    assert "key=E&amp;octave=-1" in resp.text


async def test_tune_detail_key_options_preserve_box_and_list_context(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, user.id, box.id, "Weekly Session", PracticeListType.repertoire)

    resp = await client.get(f"/tunes/{tune.id}", params={"box_id": box.id, "list_id": practice_list.id, "octave": 1})
    assert resp.status_code == 200
    assert f"box_id={box.id}&amp;list_id={practice_list.id}&amp;key=E&amp;octave=1" in resp.text


async def test_tune_add_to_box(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])

    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})
    assert resp.status_code == 200
    assert "Session Box" in resp.text

    entry = await get_box_entry(db, box.id, tune.id)
    assert entry is not None


async def test_tune_add_to_box_with_setting(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    setting = await create_setting(
        db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ABC, instrument=Instrument.fiddle)
    )

    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id), "setting_id": str(setting.id)})
    assert resp.status_code == 200

    entry = await get_box_entry(db, box.id, tune.id)
    assert entry is not None
    assert entry.setting_id == setting.id


async def test_tune_add_to_box_also_adds_to_list(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, user.id, box.id, "Weekly Session", PracticeListType.repertoire)

    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id), "list_id": str(practice_list.id)})
    assert resp.status_code == 200

    box_entry = await get_box_entry(db, box.id, tune.id)
    list_entry = await get_list_entry(db, practice_list.id, tune.id)
    assert box_entry is not None
    assert list_entry is not None


async def test_tune_add_to_box_duplicate_conflicts(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})

    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})
    assert resp.status_code == 409


async def test_tune_add_to_box_404_for_unknown_tune(client: AsyncClient, db: AsyncSession, user: User) -> None:
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    resp = await client.post("/tunes/9999/boxes", data={"box_id": str(box.id)})
    assert resp.status_code == 404


async def test_tune_update_box_setting(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    setting = await create_setting(
        db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ABC, instrument=Instrument.fiddle)
    )
    await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})

    resp = await client.post(f"/tunes/{tune.id}/boxes/{box.id}/setting", data={"setting_id": str(setting.id)})
    assert resp.status_code == 200
    assert "Alt" in resp.text

    entry = await get_box_entry(db, box.id, tune.id)
    assert entry is not None
    assert entry.setting_id == setting.id


async def test_tune_update_box_setting_404_for_tune_not_in_box(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    # never added to the box
    resp = await client.post(f"/tunes/{tune.id}/boxes/{box.id}/setting", data={"setting_id": ""})
    assert resp.status_code == 404


async def test_tune_add_to_box_with_display_alias(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])

    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id), "display_alias_id": str(alias.id)})
    assert resp.status_code == 200
    assert "Sunrise Reel" in resp.text

    entry = await get_box_entry(db, box.id, tune.id)
    assert entry is not None
    assert entry.display_alias_id == alias.id


async def test_tune_add_to_box_also_adds_to_list_with_display_alias(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    tune = await _seed_tune(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, user.id, box.id, "Weekly Session", PracticeListType.repertoire)

    resp = await client.post(
        f"/tunes/{tune.id}/boxes",
        data={"box_id": str(box.id), "list_id": str(practice_list.id), "display_alias_id": str(alias.id)},
    )
    assert resp.status_code == 200

    list_entry = await get_list_entry(db, practice_list.id, tune.id)
    assert list_entry is not None
    assert list_entry.display_alias_id == alias.id


async def test_tune_update_box_display_alias(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await _seed_tune(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})

    resp = await client.post(f"/tunes/{tune.id}/boxes/{box.id}/display-alias", data={"display_alias_id": str(alias.id)})
    assert resp.status_code == 200
    assert "Sunrise Reel" in resp.text

    entry = await get_box_entry(db, box.id, tune.id)
    assert entry is not None
    assert entry.display_alias_id == alias.id


async def test_tune_update_box_display_alias_404_for_tune_not_in_box(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    resp = await client.post(f"/tunes/{tune.id}/boxes/{box.id}/display-alias", data={"display_alias_id": ""})
    assert resp.status_code == 404


async def test_tune_detail_uses_box_display_alias_in_heading_and_score(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    tune = await _seed_tune(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    await add_tune(db, box.id, tune.id)
    await set_display_alias(db, box.id, tune.id, alias.id)

    resp = await client.get(f"/tunes/{tune.id}", params={"box_id": box.id})
    assert resp.status_code == 200
    assert "<h1" in resp.text and "Sunrise Reel" in resp.text
    assert "T:Sunrise Reel" in resp.text
    assert "Tune: The Morning Dew" in resp.text


async def test_tune_detail_list_display_alias_outranks_box_display_alias(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    tune = await _seed_tune(db)
    box_alias = await add_alias(db, tune.id, "Box Name")
    list_alias = await add_alias(db, tune.id, "List Name")
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, user.id, box.id, "Weekly Session", PracticeListType.repertoire)
    await add_tune(db, box.id, tune.id)
    await set_display_alias(db, box.id, tune.id, box_alias.id)
    await add_tune_to_list(db, practice_list.id, tune.id)
    await update_list_entry_display_alias(db, practice_list.id, tune.id, list_alias.id)

    resp = await client.get(f"/tunes/{tune.id}", params={"box_id": box.id, "list_id": practice_list.id})
    assert resp.status_code == 200
    assert "T:List Name" in resp.text
    assert "T:Box Name" not in resp.text


async def test_tune_add_to_box_explicit_core_overrides_auto_pick(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    # The box's single fiddle instrument uniquely matches this non-core setting,
    # so add_tune()'s own heuristic would auto-select it — but the user
    # explicitly chose "Core setting" (setting_id="") in the add form, which
    # must win over that heuristic.
    tune = await _seed_tune(db)
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    await create_setting(
        db, tune.id, TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ABC, instrument=Instrument.fiddle)
    )

    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id), "setting_id": ""})
    assert resp.status_code == 200

    entry = await get_box_entry(db, box.id, tune.id)
    assert entry is not None
    assert entry.setting_id is None


async def test_tune_detail_aliases_render_as_badges_with_delete_button(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "Sunrise Reel" in resp.text
    assert f'hx-delete="/tunes/{tune.id}/aliases/{alias.id}"' in resp.text
    assert 'hx-target="#aliases-section"' in resp.text


async def test_tune_detail_alias_with_notes_shows_tooltip(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    await add_alias(db, tune.id, "Sunrise Reel", "Known by this name in Clare")

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "Known by this name in Clare" in resp.text


async def test_tune_detail_alias_without_notes_has_no_tooltip_markup(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    await add_alias(db, tune.id, "Sunrise Reel")

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    chip = resp.text.split("Sunrise Reel", 1)[1].split("</span>", 1)[0]
    assert "group-hover:block" not in chip


async def test_tune_detail_shows_add_alias_control(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert 'aria-label="Add alternate name"' in resp.text
    assert f'hx-post="/tunes/{tune.id}/aliases"' in resp.text


async def test_alias_add_route_returns_updated_badges(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.post(f"/tunes/{tune.id}/aliases", data={"name": "Sunrise Reel"})
    assert resp.status_code == 200
    assert "Sunrise Reel" in resp.text
    assert 'id="aliases-section"' in resp.text


async def test_alias_remove_route_returns_updated_badges(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    resp = await client.delete(f"/tunes/{tune.id}/aliases/{alias.id}")
    assert resp.status_code == 200
    assert "Sunrise Reel" not in resp.text
    assert 'id="aliases-section"' in resp.text


async def test_tempo_record_renders_svg_point_with_bpm_label(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.post(f"/tunes/{tune.id}/tempo", data={"tempo": "100"})
    assert resp.status_code == 200
    assert "<svg" in resp.text
    assert "<circle" in resp.text
    assert "100 bpm" in resp.text


async def test_tempo_history_two_increasing_readings_shows_trending_faster(
    client: AsyncClient, db: AsyncSession
) -> None:
    tune = await _seed_tune(db)
    await client.post(f"/tunes/{tune.id}/tempo", data={"tempo": "90"})
    resp = await client.post(f"/tunes/{tune.id}/tempo", data={"tempo": "100"})
    assert resp.status_code == 200
    assert "trending faster" in resp.text
    assert "<polyline" in resp.text


async def test_tempo_history_two_decreasing_readings_shows_trending_slower(
    client: AsyncClient, db: AsyncSession
) -> None:
    tune = await _seed_tune(db)
    await client.post(f"/tunes/{tune.id}/tempo", data={"tempo": "100"})
    resp = await client.post(f"/tunes/{tune.id}/tempo", data={"tempo": "90"})
    assert resp.status_code == 200
    assert "trending slower" in resp.text


async def test_tempo_history_equal_readings_shows_steady_and_no_zero_division(
    client: AsyncClient, db: AsyncSession
) -> None:
    tune = await _seed_tune(db)
    await client.post(f"/tunes/{tune.id}/tempo", data={"tempo": "100"})
    resp = await client.post(f"/tunes/{tune.id}/tempo", data={"tempo": "100"})
    assert resp.status_code == 200
    assert "steady" in resp.text
    assert "<circle" in resp.text


async def test_tempo_history_single_reading_has_no_polyline(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.post(f"/tunes/{tune.id}/tempo", data={"tempo": "100"})
    assert resp.status_code == 200
    assert "<polyline" not in resp.text
    assert "<circle" in resp.text


async def test_tempo_history_partial_endpoint_includes_chart(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    await client.post(f"/tunes/{tune.id}/tempo", data={"tempo": "100"})
    resp = await client.get(f"/tunes/{tune.id}/tempo-history")
    assert resp.status_code == 200
    assert "<svg" in resp.text
    assert "100 bpm" in resp.text


async def test_tune_detail_page_includes_tempo_chart(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    await client.post(f"/tunes/{tune.id}/tempo", data={"tempo": "100"})
    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    assert "<svg" in resp.text
    assert "100 bpm" in resp.text


# ── cross-account ownership (#193) ──────────────────────────────────────────


async def _seed_other_owner_box(db: AsyncSession):
    """A box owned by a different user than the `user` fixture's logged-in user."""
    other = User(username="other-fiddler", email="other@example.com", google_sub="google-sub-other", role=Role.student)
    db.add(other)
    await db.flush()
    return await create_box(db, other.id, "Someone Else's Box", [Instrument.fiddle])


async def test_tune_add_to_box_404_for_another_users_box(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    box = await _seed_other_owner_box(db)
    resp = await client.post(f"/tunes/{tune.id}/boxes", data={"box_id": str(box.id)})
    assert resp.status_code == 404


async def test_tune_update_box_setting_404_for_another_users_box(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    box = await _seed_other_owner_box(db)
    resp = await client.post(f"/tunes/{tune.id}/boxes/{box.id}/setting", data={"setting_id": ""})
    assert resp.status_code == 404


async def test_tune_update_box_display_alias_404_for_another_users_box(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    box = await _seed_other_owner_box(db)
    resp = await client.post(f"/tunes/{tune.id}/boxes/{box.id}/display-alias", data={"display_alias_id": ""})
    assert resp.status_code == 404


async def test_tune_detail_drops_another_users_box_context(client: AsyncClient, db: AsyncSession) -> None:
    # box_id is just view context (which box's setting/alias to show) — it
    # should be silently dropped, not leak the other user's box name/entry
    # into the response or 404 the whole (otherwise-public) tune page.
    tune = await _seed_tune(db)
    box = await _seed_other_owner_box(db)
    resp = await client.get(f"/tunes/{tune.id}", params={"box_id": str(box.id)})
    assert resp.status_code == 200
    assert "Someone Else's Box" not in resp.text


# ── tune/setting visibility (#197) ──────────────────────────────────────────


async def _seed_other_users_private_tune(db: AsyncSession, title: str = "Someone Else's Secret Tune"):
    other = User(
        username="other-owner", email="other-owner@example.com", google_sub="google-sub-other-owner", role=Role.student
    )
    db.add(other)
    await db.flush()
    return await create_tune(
        db,
        TuneCreate(
            title=title,
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
            created_by=other.id,
            visibility=ContentVisibility.private,
        ),
        abc_notation=_ABC,
    )


async def test_tune_list_excludes_another_users_private_tune(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_other_users_private_tune(db)
    resp = await client.get("/tunes/")
    assert resp.status_code == 200
    assert "Someone Else's Secret Tune" not in resp.text


async def test_tune_list_includes_own_private_tune(client: AsyncClient, db: AsyncSession, user: User) -> None:
    await create_tune(
        db,
        TuneCreate(
            title="My Secret Tune",
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
            created_by=user.id,
            visibility=ContentVisibility.private,
        ),
        abc_notation=_ABC,
    )
    resp = await client.get("/tunes/")
    assert resp.status_code == 200
    assert "My Secret Tune" in resp.text


async def test_tune_detail_404_for_another_users_private_tune(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_other_users_private_tune(db)
    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 404


async def test_tune_create_with_is_private_sets_visibility_and_owner(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    resp = await client.post(
        "/tunes/",
        data={
            "title": "My New Private Tune",
            "tune_type": "reel",
            "key_root": "D",
            "key_mode": "major",
            "time_signature": "4/4",
            "abc_notation": _ABC,
            "is_private": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    tune_id = int(resp.headers["location"].rsplit("/", 1)[-1])

    # visible to its own creator
    resp = await client.get(f"/tunes/{tune_id}")
    assert resp.status_code == 200

    result = await db.execute(select(Tune).where(Tune.id == tune_id))
    tune = result.scalar_one()
    assert tune.visibility == ContentVisibility.private
    assert tune.created_by == user.id


async def test_tune_update_toggles_visibility(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tune = await create_tune(
        db,
        TuneCreate(
            title="Toggle Me",
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
            created_by=user.id,
        ),
        abc_notation=_ABC,
    )
    assert tune.visibility == ContentVisibility.public

    resp = await client.post(
        f"/tunes/{tune.id}",
        data={
            "title": tune.title,
            "tune_type": "reel",
            "key_root": "D",
            "key_mode": "major",
            "time_signature": "4/4",
            "is_private": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    await db.refresh(tune)
    assert tune.visibility == ContentVisibility.private


async def test_setting_create_with_is_private_sets_visibility(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.post(
        f"/tunes/{tune.id}/settings",
        data={
            "label": "Private Arrangement",
            "abc_notation": _ABC,
            "is_private": "true",
        },
    )
    assert resp.status_code == 200

    result = await db.execute(select(TuneSetting).where(TuneSetting.label == "Private Arrangement"))
    setting = result.scalar_one()
    assert setting.visibility == ContentVisibility.private
