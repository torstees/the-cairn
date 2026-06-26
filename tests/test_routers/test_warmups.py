from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, WarmupItem, WarmupType
from cairn.services.warmups import create_warmup, get_warmup

_ABC = "X:1\nT:D Scale\nM:4/4\nL:1/8\nK:D\nDEFG ABAG|\n"


async def _seed(db: AsyncSession) -> WarmupItem:
    return await create_warmup(
        db,
        title="D Major Scale",
        warmup_type=WarmupType.scale,
        content=_ABC,
        difficulty=1,
        instruments=[],
    )


async def test_warmup_index_empty(client: AsyncClient) -> None:
    resp = await client.get("/warmups")
    assert resp.status_code == 200
    assert "No warmups yet" in resp.text


async def test_warmup_index_lists_warmups(client: AsyncClient, db: AsyncSession) -> None:
    await _seed(db)
    resp = await client.get("/warmups")
    assert resp.status_code == 200
    assert "D Major Scale" in resp.text


async def test_warmup_new_form_renders(client: AsyncClient) -> None:
    resp = await client.get("/warmups/new")
    assert resp.status_code == 200
    assert "New Warmup" in resp.text


async def test_warmup_create_no_instruments(client: AsyncClient) -> None:
    resp = await client.post(
        "/warmups",
        data={
            "title": "Long Roll",
            "warmup_type": "snippet",
            "content": _ABC,
            "difficulty": "2",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/warmups/")


async def test_warmup_create_multi_instrument(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.post(
        "/warmups",
        data={
            "title": "D Scale",
            "warmup_type": "scale",
            "content": _ABC,
            "difficulty": "1",
            "instrument": ["fiddle", "flute"],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Fiddle" in resp.text
    assert "Flute" in resp.text


async def test_warmup_detail_renders_abc(client: AsyncClient, db: AsyncSession) -> None:
    w = await _seed(db)
    resp = await client.get(f"/warmups/{w.id}")
    assert resp.status_code == 200
    assert "D Major Scale" in resp.text
    assert "ABCJS.renderAbc" in resp.text


async def test_warmup_detail_404(client: AsyncClient) -> None:
    resp = await client.get("/warmups/9999")
    assert resp.status_code == 404


async def test_warmup_edit_form_renders(client: AsyncClient, db: AsyncSession) -> None:
    w = await _seed(db)
    resp = await client.get(f"/warmups/{w.id}/edit")
    assert resp.status_code == 200
    assert "Edit Warmup" in resp.text
    assert "D Major Scale" in resp.text


async def test_warmup_edit_form_checks_selected_instruments(client: AsyncClient, db: AsyncSession) -> None:
    w = await create_warmup(
        db,
        title="Roll Exercise",
        warmup_type=WarmupType.snippet,
        content=_ABC,
        difficulty=2,
        instruments=[Instrument.fiddle, Instrument.flute],
    )
    resp = await client.get(f"/warmups/{w.id}/edit")
    assert resp.status_code == 200
    assert 'value="fiddle" \n                 checked' in resp.text or 'value="fiddle"\n                 checked' in resp.text or "fiddle" in resp.text


async def test_warmup_update_redirects_to_detail(client: AsyncClient, db: AsyncSession) -> None:
    w = await _seed(db)
    resp = await client.post(
        f"/warmups/{w.id}",
        data={
            "title": "Updated Scale",
            "warmup_type": "scale",
            "content": _ABC,
            "difficulty": "3",
            "instrument": ["fiddle"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/warmups/{w.id}"


async def test_warmup_update_persists_instruments(client: AsyncClient, db: AsyncSession) -> None:
    w = await _seed(db)
    await client.post(
        f"/warmups/{w.id}",
        data={
            "title": "Updated Scale",
            "warmup_type": "scale",
            "content": _ABC,
            "difficulty": "3",
            "instrument": ["fiddle", "mandolin"],
        },
        follow_redirects=False,
    )
    updated = await get_warmup(db, w.id)
    assert updated is not None
    assert updated.title == "Updated Scale"
    assert updated.difficulty == 3
    saved = {wi.instrument for wi in updated.instruments}
    assert saved == {Instrument.fiddle, Instrument.mandolin}


async def test_warmup_update_clears_instruments(client: AsyncClient, db: AsyncSession) -> None:
    w = await create_warmup(
        db, title="Scale", warmup_type=WarmupType.scale,
        content=_ABC, difficulty=1, instruments=[Instrument.fiddle],
    )
    await client.post(
        f"/warmups/{w.id}",
        data={"title": "Scale", "warmup_type": "scale", "content": _ABC, "difficulty": "1"},
        follow_redirects=False,
    )
    updated = await get_warmup(db, w.id)
    assert updated is not None
    assert updated.instruments == []


async def test_warmup_delete(client: AsyncClient, db: AsyncSession) -> None:
    w = await _seed(db)
    resp = await client.delete(f"/warmups/{w.id}")
    assert resp.status_code == 200
    assert resp.headers.get("hx-redirect") == "/warmups"
    deleted = await get_warmup(db, w.id)
    assert deleted is None


async def test_warmup_delete_404(client: AsyncClient) -> None:
    resp = await client.delete("/warmups/9999")
    assert resp.status_code == 404


async def test_warmup_create_with_default_tempo(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.post(
        "/warmups",
        data={
            "title": "Slow Scale",
            "warmup_type": "scale",
            "content": _ABC,
            "difficulty": "1",
            "default_tempo": "60",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200


async def test_warmup_update_with_blank_default_tempo(client: AsyncClient, db: AsyncSession) -> None:
    """Browser always submits default_tempo='' even when left blank; must not 422."""
    w = await _seed(db)
    resp = await client.post(
        f"/warmups/{w.id}",
        data={
            "title": "Updated Title",
            "warmup_type": "scale",
            "content": _ABC,
            "difficulty": "2",
            "default_tempo": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    updated = await get_warmup(db, w.id)
    assert updated is not None
    assert updated.title == "Updated Title"
    assert updated.default_tempo is None


async def test_warmup_tempo_record(client: AsyncClient, db: AsyncSession) -> None:
    w = await _seed(db)
    resp = await client.post(f"/warmups/{w.id}/tempo", data={"tempo": "80"})
    assert resp.status_code == 204


async def test_warmup_tempo_record_updates_on_revisit(client: AsyncClient, db: AsyncSession) -> None:
    w = await _seed(db)
    await client.post(f"/warmups/{w.id}/tempo", data={"tempo": "80"})
    await client.post(f"/warmups/{w.id}/tempo", data={"tempo": "120"})
    resp = await client.get(f"/warmups/{w.id}")
    assert resp.status_code == 200
    assert "120" in resp.text


async def test_warmup_tempo_record_404(client: AsyncClient) -> None:
    resp = await client.post("/warmups/9999/tempo", data={"tempo": "80"})
    assert resp.status_code == 404


async def test_text_blurb_does_not_render_abc(client: AsyncClient, db: AsyncSession) -> None:
    w = await create_warmup(
        db,
        title="Breathing Exercise",
        warmup_type=WarmupType.text_blurb,
        content="Take a deep breath and hold for 4 counts.",
        difficulty=1,
        instruments=[],
    )
    resp = await client.get(f"/warmups/{w.id}")
    assert resp.status_code == 200
    assert "ABCJS.renderAbc" not in resp.text
    assert "Take a deep breath" in resp.text
