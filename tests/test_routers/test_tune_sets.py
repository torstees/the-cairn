import json

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, TuneType
from cairn.schemas import TuneCreate
from cairn.services.tune_sets import create_set, get_set, get_set_tempo
from cairn.services.tunes import add_alias, create_tune


async def _tune(db: AsyncSession, title: str = "The Morning Dew"):
    return await create_tune(
        db,
        TuneCreate(
            title=title,
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
        ),
        abc_notation="|:DEFA BAFA|DEFA BAFA:|\n",
    )


async def _set(db: AsyncSession, title: str = "Morning Set"):
    return await create_set(db, title=title)


# ── index ─────────────────────────────────────────────────────────────────────


async def test_set_index_empty(client: AsyncClient) -> None:
    resp = await client.get("/sets")
    assert resp.status_code == 200
    assert "No sets yet" in resp.text


async def test_set_index_lists_sets(client: AsyncClient, db: AsyncSession) -> None:
    await _set(db, "Evening Jigs")
    resp = await client.get("/sets")
    assert resp.status_code == 200
    assert "Evening Jigs" in resp.text


# ── new form ──────────────────────────────────────────────────────────────────


async def test_set_new_form_renders(client: AsyncClient) -> None:
    resp = await client.get("/sets/new")
    assert resp.status_code == 200
    assert "New Set" in resp.text


# ── create ────────────────────────────────────────────────────────────────────


async def test_set_create_redirects_to_edit(client: AsyncClient) -> None:
    resp = await client.post(
        "/sets",
        data={"title": "Morning Reels"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/sets/" in resp.headers["location"]
    assert resp.headers["location"].endswith("/edit")


async def test_set_create_persists_metadata(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.post(
        "/sets",
        data={
            "title": "Session Favorites",
            "source": "Catskills 2023",
            "flow_difficulty": "3",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Session Favorites" in resp.text


async def test_set_create_with_members(client: AsyncClient, db: AsyncSession) -> None:
    t = await _tune(db)
    members_json = json.dumps([{"tune_id": t.id, "setting_id": None}])
    resp = await client.post(
        "/sets",
        data={"title": "With Members", "members": members_json},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    set_id = int(location.split("/sets/")[1].split("/")[0])
    s = await get_set(db, set_id)
    assert s is not None
    assert len(s.members) == 1
    assert s.members[0].tune_id == t.id


# ── edit form ─────────────────────────────────────────────────────────────────


async def test_set_edit_form_renders(client: AsyncClient, db: AsyncSession) -> None:
    s = await _set(db, "Evening Jigs")
    resp = await client.get(f"/sets/{s.id}/edit")
    assert resp.status_code == 200
    assert "Evening Jigs" in resp.text
    assert "Edit Set" in resp.text


async def test_set_edit_form_404(client: AsyncClient) -> None:
    resp = await client.get("/sets/9999/edit")
    assert resp.status_code == 404


# ── update ────────────────────────────────────────────────────────────────────


async def test_set_update_redirects_to_edit(client: AsyncClient, db: AsyncSession) -> None:
    s = await _set(db)
    resp = await client.post(
        f"/sets/{s.id}",
        data={"title": "Updated Title"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/sets/{s.id}/edit"


async def test_set_update_persists_metadata(client: AsyncClient, db: AsyncSession) -> None:
    s = await _set(db)
    await client.post(
        f"/sets/{s.id}",
        data={"title": "Renamed Set", "source": "Catskills", "flow_difficulty": "4"},
        follow_redirects=False,
    )
    updated = await get_set(db, s.id)
    assert updated is not None
    assert updated.title == "Renamed Set"
    assert updated.source == "Catskills"
    assert updated.flow_difficulty == 4


async def test_set_update_persists_members(client: AsyncClient, db: AsyncSession) -> None:
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    s = await _set(db)
    members_json = json.dumps([
        {"tune_id": t1.id, "setting_id": None},
        {"tune_id": t2.id, "setting_id": None},
    ])
    await client.post(
        f"/sets/{s.id}",
        data={"title": "My Set", "members": members_json},
        follow_redirects=False,
    )
    updated = await get_set(db, s.id)
    assert updated is not None
    assert len(updated.members) == 2
    assert updated.members[0].tune_id == t1.id
    assert updated.members[1].tune_id == t2.id


async def test_set_update_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/sets/9999",
        data={"title": "Ghost"},
        follow_redirects=False,
    )
    assert resp.status_code == 404


# ── delete ────────────────────────────────────────────────────────────────────


async def test_set_delete(client: AsyncClient, db: AsyncSession) -> None:
    s = await _set(db)
    resp = await client.delete(f"/sets/{s.id}")
    assert resp.status_code == 200
    assert resp.headers.get("hx-redirect") == "/sets"
    assert await get_set(db, s.id) is None


async def test_set_delete_404(client: AsyncClient) -> None:
    resp = await client.delete("/sets/9999")
    assert resp.status_code == 404


# ── tune-settings endpoint ────────────────────────────────────────────────────


async def test_tune_settings_endpoint_returns_json(client: AsyncClient, db: AsyncSession) -> None:
    t = await _tune(db)
    resp = await client.get(f"/sets/tune-settings/{t.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "id" in data[0]
    assert "label" in data[0]
    assert "is_core" in data[0]


async def test_tune_settings_endpoint_empty_for_unknown(client: AsyncClient) -> None:
    resp = await client.get("/sets/tune-settings/9999")
    assert resp.status_code == 200
    assert resp.json() == []


# ── index shows flow difficulty badge ────────────────────────────────────────


async def test_set_index_shows_flow_difficulty(client: AsyncClient, db: AsyncSession) -> None:
    await create_set(db, title="Hard Set", flow_difficulty=5)
    resp = await client.get("/sets")
    assert resp.status_code == 200
    assert "Flow 5/5" in resp.text


# ── detail ────────────────────────────────────────────────────────────────────


async def test_set_detail_renders(client: AsyncClient, db: AsyncSession) -> None:
    s = await _set(db, "Evening Reels")
    resp = await client.get(f"/sets/{s.id}")
    assert resp.status_code == 200
    assert "Evening Reels" in resp.text


async def test_set_detail_404(client: AsyncClient) -> None:
    resp = await client.get("/sets/9999")
    assert resp.status_code == 404


async def test_set_detail_with_members_shows_bar_controls(
    client: AsyncClient, db: AsyncSession
) -> None:
    t = await _tune(db, "The Foxhunter's")
    s = await _set(db, "Reel Set")
    members_json = json.dumps([{"tune_id": t.id, "setting_id": None}])
    await client.post(f"/sets/{s.id}", data={"title": "Reel Set", "members": members_json})
    resp = await client.get(f"/sets/{s.id}")
    assert resp.status_code == 200
    assert "set-bars-toggle" in resp.text
    assert "The Foxhunter's" in resp.text


async def test_set_detail_member_title_is_hover_trigger_when_aliased(
    client: AsyncClient, db: AsyncSession
) -> None:
    t = await _tune(db, "The Foxhunter's")
    await add_alias(db, t.id, "Sunrise Reel")
    s = await _set(db, "Reel Set")
    members_json = json.dumps([{"tune_id": t.id, "setting_id": None}])
    await client.post(f"/sets/{s.id}", data={"title": "Reel Set", "members": members_json})

    resp = await client.get(f"/sets/{s.id}")
    assert resp.status_code == 200
    assert "cursor-help border-b border-dotted border-stone-300" in resp.text
    assert "Sunrise Reel" in resp.text


async def test_set_detail_member_title_not_a_hover_trigger_without_aliases(
    client: AsyncClient, db: AsyncSession
) -> None:
    t = await _tune(db, "The Foxhunter's")
    s = await _set(db, "Reel Set")
    members_json = json.dumps([{"tune_id": t.id, "setting_id": None}])
    await client.post(f"/sets/{s.id}", data={"title": "Reel Set", "members": members_json})

    resp = await client.get(f"/sets/{s.id}")
    assert resp.status_code == 200
    assert "cursor-help" not in resp.text


async def test_set_detail_shows_set_abc(client: AsyncClient, db: AsyncSession) -> None:
    t = await _tune(db)
    s = await _set(db)
    members_json = json.dumps([{"tune_id": t.id, "setting_id": None}])
    await client.post(f"/sets/{s.id}", data={"title": s.title, "members": members_json})
    resp = await client.get(f"/sets/{s.id}")
    assert resp.status_code == 200
    assert "initSetTools" in resp.text
    assert "X:1" in resp.text


# ── tempo recording ────────────────────────────────────────────────────────────


async def test_set_tempo_record(client: AsyncClient, db: AsyncSession) -> None:
    s = await _set(db)
    resp = await client.post(f"/sets/{s.id}/tempo", data={"tempo": "92", "box_id": "1"})
    assert resp.status_code == 204
    stored = await get_set_tempo(db, 1, 1, s.id)
    assert stored == 92


async def test_set_tempo_upsert(client: AsyncClient, db: AsyncSession) -> None:
    s = await _set(db)
    await client.post(f"/sets/{s.id}/tempo", data={"tempo": "80", "box_id": "1"})
    await client.post(f"/sets/{s.id}/tempo", data={"tempo": "100", "box_id": "1"})
    stored = await get_set_tempo(db, 1, 1, s.id)
    assert stored == 100
