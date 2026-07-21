from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, KeyMode, KeyRoot, PracticeListType, Role, TuneType, User
from cairn.schemas import TuneCreate, TuneDifficultyCreate, TuneSettingCreate
from cairn.services.boxes import create_box
from cairn.services.lists import (
    add_tune_to_list,
    create_list,
    get_list_entry,
    set_focus,
    update_list_entry_setting,
    update_list_entry_transpose,
)
from cairn.services.tune_sets import add_list_set, create_set, set_members
from cairn.services.tunes import add_alias, create_setting, create_tune, set_difficulty

_ABC = "X:1\nT:x\nK:D\n|:DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA:|"
_ALT_ABC = "X:1\nT:x\nK:D\n|:GABc defg|GABc defg|GABc defg|GABc defg|GABc defg|GABc defg:|"


async def _seed(db: AsyncSession, user: User):
    """Create a box, a practice list, and one tune with a core setting for the given user."""
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, user.id, box.id, "My Repertoire", PracticeListType.repertoire)
    tune = await create_tune(
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
    await add_tune_to_list(db, practice_list.id, tune.id)
    return practice_list, tune


async def test_list_detail_includes_abc_hover_preview(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert f'data-abc-preview-id="{tune.id}"' in resp.text
    assert f'<template id="tune-abc-preview-{tune.id}">' in resp.text


async def test_list_detail_hover_preview_trigger_is_preview_cell_not_row_or_title(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200

    row_open = resp.text.split(f'id="entry-row-{tune.id}"', 1)[1].split(">", 1)[0]
    assert "data-abc-preview-id" not in row_open

    a_open = resp.text.split(f'<a href="/tunes/{tune.id}?list_id={practice_list.id}"', 1)[1].split(">", 1)[0]
    assert "data-abc-preview-id" not in a_open

    canvas_open = resp.text.split(f'id="tune-abc-col-canvas-{tune.id}"', 1)[1].split(">", 1)[0]
    assert f'data-abc-preview-id="{tune.id}"' in canvas_open
    assert 'data-abc-preview-delay="300"' in canvas_open


async def test_list_detail_shows_tune_aliases(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    await add_alias(db, tune.id, "Sunrise Reel")
    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert "Also known as: Sunrise Reel" in resp.text


async def test_list_add_tune_response_includes_abc_hover_preview(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, user.id, box.id, "My Repertoire", PracticeListType.repertoire)
    tune = await create_tune(
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
    resp = await client.post(f"/lists/{practice_list.id}/tunes", data={"tune_id": str(tune.id)})
    assert resp.status_code == 200
    assert f'data-abc-preview-id="{tune.id}"' in resp.text
    assert f'<template id="tune-abc-preview-{tune.id}">' in resp.text


async def test_list_set_entry_setting_response_includes_abc_hover_preview(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.post(f"/lists/{practice_list.id}/tunes/{tune.id}/setting", data={"setting_id": ""})
    assert resp.status_code == 200
    assert f'data-abc-preview-id="{tune.id}"' in resp.text
    assert f'<template id="tune-abc-preview-{tune.id}">' in resp.text


async def test_list_add_tune_with_display_alias(client: AsyncClient, db: AsyncSession, user: User) -> None:
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])
    practice_list = await create_list(db, user.id, box.id, "My Repertoire", PracticeListType.repertoire)
    tune = await create_tune(
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
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    resp = await client.post(
        f"/lists/{practice_list.id}/tunes",
        data={"tune_id": str(tune.id), "display_alias_id": str(alias.id)},
    )
    assert resp.status_code == 200
    a_open_to_close = resp.text.split(f'<a href="/tunes/{tune.id}?list_id={practice_list.id}"', 1)[1].split("</a>", 1)[
        0
    ]
    assert "Sunrise Reel" in a_open_to_close
    assert "The Morning Dew" not in a_open_to_close


async def test_list_set_entry_display_alias_updates_row(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    alias = await add_alias(db, tune.id, "Sunrise Reel")

    resp = await client.post(
        f"/lists/{practice_list.id}/tunes/{tune.id}/display-alias", data={"display_alias_id": str(alias.id)}
    )
    assert resp.status_code == 200
    a_open_to_close = resp.text.split(f'<a href="/tunes/{tune.id}?list_id={practice_list.id}"', 1)[1].split("</a>", 1)[
        0
    ]
    assert "Sunrise Reel" in a_open_to_close


async def test_list_set_entry_display_alias_missing_entry_404(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.post(f"/lists/{practice_list.id}/tunes/9999/display-alias", data={"display_alias_id": ""})
    assert resp.status_code == 404


async def test_list_row_data_title_follows_display_alias(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    await client.post(
        f"/lists/{practice_list.id}/tunes/{tune.id}/display-alias", data={"display_alias_id": str(alias.id)}
    )

    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert 'data-title="sunrise reel"' in resp.text
    assert 'data-title="the morning dew"' not in resp.text


async def test_list_hover_preview_is_notes_only_regardless_of_display_alias(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    await client.post(
        f"/lists/{practice_list.id}/tunes/{tune.id}/display-alias", data={"display_alias_id": str(alias.id)}
    )

    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    marker = f'<template id="tune-abc-preview-{tune.id}">'
    preview = resp.text.split(marker, 1)[1].split("</template>", 1)[0]
    assert "T:" not in preview

    a_open_to_close = resp.text.split(f'<a href="/tunes/{tune.id}?list_id={practice_list.id}"', 1)[1].split("</a>", 1)[
        0
    ]
    assert "Sunrise Reel" in a_open_to_close


async def test_list_preview_uses_preferred_setting_not_core(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    alt = await create_setting(
        db,
        tune.id,
        TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ALT_ABC, instrument=Instrument.fiddle),
    )
    await update_list_entry_setting(db, practice_list.id, tune.id, alt.id)

    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    marker = f'<template id="tune-abc-preview-{tune.id}">'
    preview = resp.text.split(marker, 1)[1].split("</template>", 1)[0]
    assert "GABc defg" in preview
    assert "DEFA BAFA" not in preview


# ── transpose popup (#158) ───────────────────────────────────────────────────


async def test_list_row_shows_transpose_button_default_label(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert "Transpose" in resp.text


async def test_list_transpose_popup_key_options_exclude_tunes_own_key(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.get(f"/lists/{practice_list.id}/tunes/{tune.id}/transpose")
    assert resp.status_code == 200
    assert resp.text.count("D Major") == 1


async def test_list_transpose_popup_get_seeds_from_saved_entry(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    await update_list_entry_transpose(db, practice_list.id, tune.id, KeyRoot.E, 1)

    resp = await client.get(f"/lists/{practice_list.id}/tunes/{tune.id}/transpose")
    assert resp.status_code == 200
    assert "cairn-modal-backdrop" in resp.text
    assert '<option value="E" selected>' in resp.text
    assert '<input type="hidden" name="octave" value="1">' in resp.text


async def test_list_transpose_popup_get_reflects_pending_query_params(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.get(
        f"/lists/{practice_list.id}/tunes/{tune.id}/transpose", params={"key_root": "G", "octave": "-1"}
    )
    assert resp.status_code == 200
    assert '<option value="G" selected>' in resp.text
    assert '<input type="hidden" name="octave" value="-1">' in resp.text


async def test_list_transpose_popup_404_for_missing_entry(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, _tune = await _seed(db, user)
    resp = await client.get(f"/lists/{practice_list.id}/tunes/9999/transpose")
    assert resp.status_code == 404


async def test_list_set_transpose_updates_row_and_closes_modal(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.post(
        f"/lists/{practice_list.id}/tunes/{tune.id}/transpose", data={"key_root": "E", "octave": "1"}
    )
    assert resp.status_code == 200
    assert "E" in resp.text
    assert "+8ve" in resp.text
    assert '<div id="list-transpose-modal" hx-swap-oob="true"></div>' in resp.text


async def test_list_set_transpose_persists(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    await client.post(f"/lists/{practice_list.id}/tunes/{tune.id}/transpose", data={"key_root": "E", "octave": "1"})

    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert "+8ve" in resp.text


async def test_list_set_transpose_can_clear(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    await update_list_entry_transpose(db, practice_list.id, tune.id, KeyRoot.E, 1)

    resp = await client.post(
        f"/lists/{practice_list.id}/tunes/{tune.id}/transpose", data={"key_root": "", "octave": "0"}
    )
    assert resp.status_code == 200
    assert "+8ve" not in resp.text


async def test_list_set_transpose_404_for_missing_entry(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, _tune = await _seed(db, user)
    resp = await client.post(f"/lists/{practice_list.id}/tunes/9999/transpose", data={"key_root": "E", "octave": "0"})
    assert resp.status_code == 404


async def test_list_hover_preview_reflects_saved_transpose(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    await update_list_entry_transpose(db, practice_list.id, tune.id, KeyRoot.E, 0)

    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    marker = f'<template id="tune-abc-preview-{tune.id}">'
    preview = resp.text.split(marker, 1)[1].split("</template>", 1)[0]
    assert "K:E" in preview


# ── tunes-table redesign (#164) ─────────────────────────────────────────────


async def test_list_row_shows_type_badge(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert "Reel" in resp.text


async def test_list_column_preview_is_shorter_than_popup_preview(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200

    col_marker = f'<template id="tune-abc-col-{tune.id}">'
    col = resp.text.split(col_marker, 1)[1].split("</template>", 1)[0]
    popup_marker = f'<template id="tune-abc-preview-{tune.id}">'
    popup = resp.text.split(popup_marker, 1)[1].split("</template>", 1)[0]

    assert col != popup
    assert len(col) < len(popup)
    assert "DEFA BAFA:|" in popup
    assert "DEFA BAFA:|" not in col


async def test_list_row_has_overflow_menu_with_transpose_and_remove(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert 'role="menu"' in resp.text
    assert f'hx-get="/lists/{practice_list.id}/tunes/{tune.id}/transpose"' in resp.text


async def test_list_row_has_cairn_row_class(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    row_open = resp.text.split(f'id="entry-row-{tune.id}"', 1)[1].split(">", 1)[0]
    assert "cairn-row" in row_open


async def test_list_header_keeps_type_sort_control(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert "sortListTable('type')" in resp.text


async def test_list_row_shows_transposed_key_with_tooltip(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    await update_list_entry_transpose(db, practice_list.id, tune.id, KeyRoot.E, 1)

    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert "E Major, +8ve" in resp.text
    assert "own key" in resp.text
    assert "D Major" in resp.text


async def test_list_detail_shows_sets_section_and_addable_sets(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    list_id, tune_id = practice_list.id, tune.id
    tune_set = await create_set(db, title="Morning Medley")
    set_id = tune_set.id
    await set_members(db, set_id, [{"tune_id": tune_id}])

    resp = await client.get(f"/lists/{list_id}")
    assert resp.status_code == 200
    assert "Sets" in resp.text
    assert "Morning Medley" in resp.text  # in the addable-sets combobox data


async def test_list_add_set(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    list_id, tune_id = practice_list.id, tune.id
    tune_set = await create_set(db, title="Morning Medley")
    set_id = tune_set.id
    await set_members(db, set_id, [{"tune_id": tune_id}])

    resp = await client.post(f"/lists/{list_id}/sets", data={"set_id": str(set_id)})
    assert resp.status_code == 200
    assert "Morning Medley" in resp.text
    assert f'id="list-set-{set_id}"' in resp.text


async def test_list_add_set_duplicate_conflicts(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    list_id, tune_id = practice_list.id, tune.id
    tune_set = await create_set(db, title="Morning Medley")
    set_id = tune_set.id
    await set_members(db, set_id, [{"tune_id": tune_id}])
    await add_list_set(db, list_id, set_id)

    resp = await client.post(f"/lists/{list_id}/sets", data={"set_id": str(set_id)})
    assert resp.status_code == 409


async def test_list_remove_set(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    list_id, tune_id = practice_list.id, tune.id
    tune_set = await create_set(db, title="Morning Medley")
    set_id = tune_set.id
    await set_members(db, set_id, [{"tune_id": tune_id}])
    await add_list_set(db, list_id, set_id)

    resp = await client.delete(f"/lists/{list_id}/sets/{set_id}")
    assert resp.status_code == 200

    resp = await client.get(f"/lists/{list_id}")
    assert f'id="list-set-{set_id}"' not in resp.text


async def test_list_set_difficulty_shows_computed_default(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    list_id, tune_id = practice_list.id, tune.id
    await set_difficulty(db, tune_id, TuneDifficultyCreate(tune_id=tune_id, instrument=Instrument.fiddle, difficulty=3))
    tune_set = await create_set(db, title="Morning Medley")
    set_id = tune_set.id
    await set_members(db, set_id, [{"tune_id": tune_id}])
    await add_list_set(db, list_id, set_id)

    resp = await client.get(f"/lists/{list_id}")
    assert resp.status_code == 200
    assert "3/5" in resp.text
    assert "(default)" in resp.text


async def test_list_set_difficulty_override_persists_and_replaces_default(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    list_id, tune_id = practice_list.id, tune.id
    await set_difficulty(db, tune_id, TuneDifficultyCreate(tune_id=tune_id, instrument=Instrument.fiddle, difficulty=3))
    tune_set = await create_set(db, title="Morning Medley")
    set_id = tune_set.id
    await set_members(db, set_id, [{"tune_id": tune_id}])
    await add_list_set(db, list_id, set_id)

    resp = await client.post(f"/lists/{list_id}/sets/{set_id}/difficulty", data={"difficulty": "5"})
    assert resp.status_code == 200
    assert "5/5" in resp.text
    assert "(default)" not in resp.text

    # persists across a fresh page load, not just the immediate response
    resp = await client.get(f"/lists/{list_id}")
    assert "5/5" in resp.text


async def test_list_set_difficulty_reset_reverts_to_default(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    list_id, tune_id = practice_list.id, tune.id
    await set_difficulty(db, tune_id, TuneDifficultyCreate(tune_id=tune_id, instrument=Instrument.fiddle, difficulty=3))
    tune_set = await create_set(db, title="Morning Medley")
    set_id = tune_set.id
    await set_members(db, set_id, [{"tune_id": tune_id}])
    await add_list_set(db, list_id, set_id)
    await client.post(f"/lists/{list_id}/sets/{set_id}/difficulty", data={"difficulty": "5"})

    resp = await client.post(f"/lists/{list_id}/sets/{set_id}/difficulty/reset")
    assert resp.status_code == 200
    assert "3/5" in resp.text
    assert "(default)" in resp.text


# ── cross-account ownership (#193) ──────────────────────────────────────────


async def _seed_other_owner_list(db: AsyncSession) -> object:
    """A practice list owned by a different user than the `user` fixture's logged-in user."""
    other = User(username="other-fiddler", email="other@example.com", google_sub="google-sub-other", role=Role.student)
    db.add(other)
    await db.flush()
    box = await create_box(db, other.id, "Someone Else's Box", [Instrument.fiddle])
    return await create_list(db, other.id, box.id, "Someone Else's List", PracticeListType.repertoire)


async def test_list_detail_404_for_another_users_list(client: AsyncClient, db: AsyncSession) -> None:
    practice_list = await _seed_other_owner_list(db)
    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 404


async def test_list_add_tune_404_for_another_users_list(client: AsyncClient, db: AsyncSession) -> None:
    practice_list = await _seed_other_owner_list(db)
    tune = await create_tune(
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
    resp = await client.post(f"/lists/{practice_list.id}/tunes", data={"tune_id": str(tune.id)})
    assert resp.status_code == 404


async def test_list_delete_404_for_another_users_list(client: AsyncClient, db: AsyncSession) -> None:
    practice_list = await _seed_other_owner_list(db)
    resp = await client.delete(f"/lists/{practice_list.id}")
    assert resp.status_code == 404


# ── focus toggle and goal-reached prompt (#245) ─────────────────────────────


def _checkbox_open_tag(html: str, list_id: int, tune_id: int) -> str:
    marker = f'hx-post="/lists/{list_id}/tunes/{tune_id}/focus"'
    idx = html.index(marker)
    tag_start = html.rfind("<input", 0, idx)
    tag_end = html.index(">", idx)
    return html[tag_start:tag_end]


async def test_list_toggle_entry_focus_persists(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)

    resp = await client.post(f"/lists/{practice_list.id}/tunes/{tune.id}/focus")
    assert resp.status_code == 200
    assert "checked" in _checkbox_open_tag(resp.text, practice_list.id, tune.id)

    resp = await client.get(f"/lists/{practice_list.id}")
    assert "checked" in _checkbox_open_tag(resp.text, practice_list.id, tune.id)

    resp = await client.post(f"/lists/{practice_list.id}/tunes/{tune.id}/focus")
    resp = await client.get(f"/lists/{practice_list.id}")
    assert "checked" not in _checkbox_open_tag(resp.text, practice_list.id, tune.id)


async def test_list_toggle_entry_focus_404_for_missing_entry(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, _tune = await _seed(db, user)
    resp = await client.post(f"/lists/{practice_list.id}/tunes/9999/focus")
    assert resp.status_code == 404


async def test_goal_reached_prompt_shows_for_focused_entry_with_pending_prompt(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    entry = await get_list_entry(db, practice_list.id, tune.id)
    await set_focus(db, practice_list.id, tune.id, True)
    entry.focus_goal_reached_at = datetime.now(UTC)
    db.add(entry)
    await db.commit()

    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert f'id="focus-prompt-{tune.id}"' in resp.text
    assert "reached its goal" in resp.text
    assert "Remove from focus" in resp.text
    assert "Keep focused" in resp.text


async def test_goal_reached_prompt_absent_without_pending_prompt(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    practice_list, tune = await _seed(db, user)
    await set_focus(db, practice_list.id, tune.id, True)

    resp = await client.get(f"/lists/{practice_list.id}")
    assert resp.status_code == 200
    assert f'id="focus-prompt-{tune.id}"' not in resp.text


async def test_remove_from_focus_clears_prompt_and_unfocuses(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    entry = await get_list_entry(db, practice_list.id, tune.id)
    await set_focus(db, practice_list.id, tune.id, True)
    entry.focus_goal_reached_at = datetime.now(UTC)
    db.add(entry)
    await db.commit()

    resp = await client.post(f"/lists/{practice_list.id}/tunes/{tune.id}/focus")
    assert resp.status_code == 200
    assert f'<div id="focus-prompt-{tune.id}" hx-swap-oob="true"></div>' in resp.text

    resp = await client.get(f"/lists/{practice_list.id}")
    assert f'id="focus-prompt-{tune.id}"' not in resp.text
    assert "checked" not in _checkbox_open_tag(resp.text, practice_list.id, tune.id)


async def test_keep_focused_clears_prompt_without_unfocusing(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, tune = await _seed(db, user)
    entry = await get_list_entry(db, practice_list.id, tune.id)
    await set_focus(db, practice_list.id, tune.id, True)
    entry.focus_goal_reached_at = datetime.now(UTC)
    db.add(entry)
    await db.commit()

    resp = await client.post(f"/lists/{practice_list.id}/tunes/{tune.id}/focus/keep")
    assert resp.status_code == 200
    assert f'<div id="focus-prompt-{tune.id}" hx-swap-oob="true"></div>' in resp.text

    resp = await client.get(f"/lists/{practice_list.id}")
    assert f'id="focus-prompt-{tune.id}"' not in resp.text
    assert "checked" in _checkbox_open_tag(resp.text, practice_list.id, tune.id)


async def test_keep_focused_404_for_missing_entry(client: AsyncClient, db: AsyncSession, user: User) -> None:
    practice_list, _tune = await _seed(db, user)
    resp = await client.post(f"/lists/{practice_list.id}/tunes/9999/focus/keep")
    assert resp.status_code == 404
