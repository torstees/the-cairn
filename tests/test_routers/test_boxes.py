from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, KeyMode, KeyRoot, Role, TuneType, User
from cairn.routers.boxes import _STUB_USER_ID
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.boxes import add_tune, create_box, set_display_alias, set_preferred_setting
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


async def test_box_detail_hover_preview_trigger_is_row_not_title(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200

    tr_open = resp.text.split(f'<tr id="box-tune-{tune.id}"', 1)[1].split(">", 1)[0]
    assert f'data-abc-preview-id="{tune.id}"' in tr_open

    a_open = resp.text.split(f'<a href="/tunes/{tune.id}?box_id={box.id}"', 1)[1].split(">", 1)[0]
    assert "data-abc-preview-id" not in a_open


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


async def test_box_hover_preview_uses_display_alias_in_title(client: AsyncClient, db: AsyncSession) -> None:
    box, tune = await _seed(db)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    await set_display_alias(db, box.id, tune.id, alias.id)

    resp = await client.get(f"/boxes/{box.id}")
    assert resp.status_code == 200
    marker = f'<template id="tune-abc-preview-{tune.id}">'
    preview = resp.text.split(marker, 1)[1].split("</template>", 1)[0]
    assert "T:Sunrise Reel" in preview


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
