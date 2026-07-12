from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, KeyMode, KeyRoot, Role, TuneType, User
from cairn.routers.boxes import _STUB_USER_ID
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.boxes import add_tune, create_box, set_display_alias, set_preferred_setting, set_transpose
from cairn.services.tunes import add_alias, create_setting, create_tune

_ABC = "X:1\nT:x\nK:D\n|:DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA:|"
_ALT_ABC = "X:1\nT:x\nK:D\n|:GABc defg|GABc defg|GABc defg|GABc defg|GABc defg|GABc defg:|"


async def _seed(db: AsyncSession):
    """Create stub user (id=1), a TuneBox, and one tune with a core setting."""
    u = User(username="tester", email="t@example.com", hashed_password="x", role=Role.student)
    db.add(u)
    await db.flush()
    assert u.id == _STUB_USER_ID

    box = await create_box(db, u.id, "Session Box", [Instrument.fiddle])
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
    await add_tune(db, box.id, tune.id)
    return box, tune


async def test_box_detail_includes_abc_hover_preview(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    assert f'data-abc-preview-id="{tune.id}"' in resp.text
    assert f'<template id="tune-abc-preview-{tune.id}">' in resp.text


async def test_box_detail_hover_preview_trigger_is_preview_cell_not_row_or_title(
    client: AsyncClient, db: AsyncSession
) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200

    row_open = resp.text.split(f'id="box-tune-{tune.id}"', 1)[1].split(">", 1)[0]
    assert "data-abc-preview-id" not in row_open

    a_open = resp.text.split(f'<a href="/tunes/{tune.id}?box_id={box.id}"', 1)[1].split(">", 1)[0]
    assert "data-abc-preview-id" not in a_open

    canvas_open = resp.text.split(f'id="tune-abc-col-canvas-{tune.id}"', 1)[1].split(">", 1)[0]
    assert f'data-abc-preview-id="{tune.id}"' in canvas_open
    assert 'data-abc-preview-delay="300"' in canvas_open


async def test_box_detail_shows_tune_aliases(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    await add_alias(db, tune.id, "Sunrise Reel")
    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    assert "Also known as: Sunrise Reel" in resp.text


async def test_box_add_tune_response_includes_abc_hover_preview(client: AsyncClient, db: AsyncSession) -> None:
    u = User(username="tester", email="t@example.com", hashed_password="x", role=Role.student)
    db.add(u)
    await db.flush()
    box = await create_box(db, u.id, "Session Box", [Instrument.fiddle])
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
    resp = await client.post(f"/boxes/{box.id}/tunes", data={"tune_id": str(tune.id)})
    assert resp.status_code == 200
    assert f'data-abc-preview-id="{tune.id}"' in resp.text
    assert f'<template id="tune-abc-preview-{tune.id}">' in resp.text


async def test_box_set_setting_response_includes_abc_hover_preview(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.post(f"/boxes/{box.id}/tunes/{tune.id}/setting", data={"setting_id": ""})
    assert resp.status_code == 200
    assert f'data-abc-preview-id="{tune.id}"' in resp.text
    assert f'<template id="tune-abc-preview-{tune.id}">' in resp.text


async def test_box_row_shows_display_alias_name(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    await set_display_alias(db, box.id, tune.id, alias.id)

    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    a_open_to_close = resp.text.split(f'<a href="/tunes/{tune.id}?box_id={box.id}"', 1)[1].split("</a>", 1)[0]
    assert "Sunrise Reel" in a_open_to_close
    assert "The Morning Dew" not in a_open_to_close


async def test_box_set_display_alias_updates_row(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")

    resp = await client.post(f"/boxes/{box.id}/tunes/{tune.id}/display-alias", data={"display_alias_id": str(alias.id)})
    assert resp.status_code == 200
    a_open_to_close = resp.text.split(f'<a href="/tunes/{tune.id}?box_id={box.id}"', 1)[1].split("</a>", 1)[0]
    assert "Sunrise Reel" in a_open_to_close


async def test_box_set_display_alias_can_clear_back_to_title(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    await set_display_alias(db, box.id, tune.id, alias.id)

    resp = await client.post(f"/boxes/{box.id}/tunes/{tune.id}/display-alias", data={"display_alias_id": ""})
    assert resp.status_code == 200
    a_open_to_close = resp.text.split(f'<a href="/tunes/{tune.id}?box_id={box.id}"', 1)[1].split("</a>", 1)[0]
    assert "The Morning Dew" in a_open_to_close


async def test_box_set_display_alias_404_for_tune_not_in_box(client: AsyncClient, db: AsyncSession) -> None:
    u = User(username="tester", email="t@example.com", hashed_password="x", role=Role.student)
    db.add(u)
    await db.flush()
    box = await create_box(db, u.id, "Session Box", [Instrument.fiddle])
    resp = await client.post(f"/boxes/{box.id}/tunes/9999/display-alias", data={"display_alias_id": ""})
    assert resp.status_code == 404


async def test_box_row_data_title_follows_display_alias(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    await set_display_alias(db, box.id, tune.id, alias.id)

    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    assert 'data-title="sunrise reel"' in resp.text
    assert 'data-title="the morning dew"' not in resp.text


async def test_box_hover_preview_is_notes_only_regardless_of_display_alias(
    client: AsyncClient, db: AsyncSession
) -> None:
    box, tune = await _seed(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    await set_display_alias(db, box.id, tune.id, alias.id)

    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    marker = f'<template id="tune-abc-preview-{tune.id}">'
    preview = resp.text.split(marker, 1)[1].split("</template>", 1)[0]
    assert "T:" not in preview

    a_open_to_close = resp.text.split(f'<a href="/tunes/{tune.id}?box_id={box.id}"', 1)[1].split("</a>", 1)[0]
    assert "Sunrise Reel" in a_open_to_close


async def test_box_preview_uses_preferred_setting_not_core(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    alt = await create_setting(
        db,
        tune.id,
        TuneSettingCreate(tune_id=tune.id, label="Alt", abc_notation=_ALT_ABC, instrument=Instrument.fiddle),
    )
    await set_preferred_setting(db, box.id, tune.id, alt.id)

    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    marker = f'<template id="tune-abc-preview-{tune.id}">'
    preview = resp.text.split(marker, 1)[1].split("</template>", 1)[0]
    assert "GABc defg" in preview
    assert "DEFA BAFA" not in preview


# ── transpose popup (#158) ───────────────────────────────────────────────────


async def test_box_row_shows_transpose_button_default_label(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    assert "Transpose" in resp.text


async def test_box_transpose_popup_key_options_exclude_tunes_own_key(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}/tunes/{tune.id}/transpose")
    assert resp.status_code == 200
    assert resp.text.count("D Major") == 1


async def test_box_transpose_popup_get_seeds_from_saved_entry(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    await set_transpose(db, box.id, tune.id, KeyRoot.E, 1)

    resp = await client.get(f"/boxes/{box.id}/tunes/{tune.id}/transpose")
    assert resp.status_code == 200
    assert "cairn-modal-backdrop" in resp.text
    assert '<option value="E" selected>' in resp.text
    assert '<input type="hidden" name="octave" value="1">' in resp.text


async def test_box_transpose_popup_get_reflects_pending_query_params(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}/tunes/{tune.id}/transpose", params={"key_root": "G", "octave": "-1"})
    assert resp.status_code == 200
    assert '<option value="G" selected>' in resp.text
    assert '<input type="hidden" name="octave" value="-1">' in resp.text


async def test_box_transpose_popup_get_includes_live_preview(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}/tunes/{tune.id}/transpose", params={"key_root": "E", "octave": "0"})
    assert resp.status_code == 200
    assert '<template id="transpose-preview-abc">' in resp.text
    marker = '<template id="transpose-preview-abc">'
    preview = resp.text.split(marker, 1)[1].split("</template>", 1)[0]
    assert "K:E" in preview


async def test_box_transpose_popup_404_for_tune_not_in_box(client: AsyncClient, db: AsyncSession) -> None:
    box, _tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}/tunes/9999/transpose")
    assert resp.status_code == 404


async def test_box_set_transpose_updates_row_and_closes_modal(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.post(f"/boxes/{box.id}/tunes/{tune.id}/transpose", data={"key_root": "E", "octave": "1"})
    assert resp.status_code == 200
    assert "E" in resp.text
    assert "+8ve" in resp.text
    assert '<div id="box-transpose-modal" hx-swap-oob="true"></div>' in resp.text


async def test_box_set_transpose_persists(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    await client.post(f"/boxes/{box.id}/tunes/{tune.id}/transpose", data={"key_root": "E", "octave": "1"})

    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    assert "+8ve" in resp.text


async def test_box_set_transpose_can_clear(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    await set_transpose(db, box.id, tune.id, KeyRoot.E, 1)

    resp = await client.post(f"/boxes/{box.id}/tunes/{tune.id}/transpose", data={"key_root": "", "octave": "0"})
    assert resp.status_code == 200
    assert "+8ve" not in resp.text


async def test_box_set_transpose_404_for_tune_not_in_box(client: AsyncClient, db: AsyncSession) -> None:
    box, _tune = await _seed(db)
    resp = await client.post(f"/boxes/{box.id}/tunes/9999/transpose", data={"key_root": "E", "octave": "0"})
    assert resp.status_code == 404


async def test_box_hover_preview_reflects_saved_transpose(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    await set_transpose(db, box.id, tune.id, KeyRoot.E, 0)

    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    marker = f'<template id="tune-abc-preview-{tune.id}">'
    preview = resp.text.split(marker, 1)[1].split("</template>", 1)[0]
    assert "K:E" in preview


# ── tunes-table redesign (#164) ─────────────────────────────────────────────


async def test_box_row_shows_type_badge(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    assert "Reel" in resp.text


async def test_box_column_preview_is_shorter_than_popup_preview(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200

    col_marker = f'<template id="tune-abc-col-{tune.id}">'
    col = resp.text.split(col_marker, 1)[1].split("</template>", 1)[0]
    popup_marker = f'<template id="tune-abc-preview-{tune.id}">'
    popup = resp.text.split(popup_marker, 1)[1].split("</template>", 1)[0]

    assert col != popup
    assert len(col) < len(popup)
    assert "DEFA BAFA:|" in popup
    assert "DEFA BAFA:|" not in col


async def test_box_row_has_overflow_menu_with_transpose_and_remove(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    assert 'role="menu"' in resp.text
    assert f'hx-get="/boxes/{box.id}/tunes/{tune.id}/transpose"' in resp.text
    assert f'hx-delete="/boxes/{box.id}/tunes/{tune.id}"' in resp.text


async def test_box_row_has_cairn_row_class(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    row_open = resp.text.split(f'id="box-tune-{tune.id}"', 1)[1].split(">", 1)[0]
    assert "cairn-row" in row_open


async def test_box_header_keeps_type_sort_control(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    assert "sortBoxTable('type')" in resp.text


async def test_box_row_shows_transposed_key_with_tooltip(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    await set_transpose(db, box.id, tune.id, KeyRoot.E, 1)

    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    assert "E Major, +8ve" in resp.text
    assert "own key" in resp.text
    assert "D Major" in resp.text
