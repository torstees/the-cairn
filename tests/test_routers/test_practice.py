import json

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    Instrument,
    KeyMode,
    KeyRoot,
    PracticeListType,
    Role,
    TuneType,
    User,
    WarmupItem,
    WarmupType,
)
from cairn.schemas import TuneCreate
from cairn.services.boxes import add_tune, create_box, set_display_alias, set_transpose
from cairn.services.lists import (
    activate_list,
    add_tune_to_list,
    create_list,
    get_active_list,
    get_list,
    update_list_entry_transpose,
    update_list_preferences,
)
from cairn.services.session_plan import build_session
from cairn.services.tunes import add_alias, create_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|"


async def _seed(db: AsyncSession, user: User):
    """Create a TuneBox and one just_learning tune for the given user."""
    box = await create_box(db, user.id, "Session Box", [Instrument.fiddle])

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

    warmup = WarmupItem(title="D Major Scale", warmup_type=WarmupType.scale, content=_ABC, difficulty=1)
    db.add(warmup)
    await db.flush()

    return user, box, tune, warmup


async def test_plan_form_renders(client: AsyncClient) -> None:
    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    assert "Plan a Practice Session" in resp.text


async def test_plan_form_shows_no_boxes_message(client: AsyncClient) -> None:
    # No user/box seeded — list_boxes returns empty
    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    assert "don't have any tune boxes" in resp.text


async def test_plan_form_shows_boxes(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    assert box.name in resp.text


async def test_plan_create_redirects_to_session(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    resp = await client.post(
        "/practice/plan", data={"box_id": str(box.id), "total_minutes": "30"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/practice/session/")


# ── session-shape preferences (#246) ─────────────────────────────────────────


async def test_plan_form_prefills_list_preferences(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    plist = await create_list(db, user.id, box.id, "List A", PracticeListType.repertoire)
    await update_list_preferences(
        db,
        plist.id,
        warmup_pct=20,
        review_pct=15,
        learning_pct=45,
        retention_pct=20,
        learning_tune_count=5,
        review_tune_count=None,
        retention_tune_count=None,
    )

    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    marker = "window.__cairnListsByBox = "
    blob = resp.text.split(marker, 1)[1].split(";", 1)[0]
    entry = json.loads(blob)[str(box.id)][0]
    assert entry["warmup_pct"] == 20
    assert entry["review_pct"] == 15
    assert entry["learning_pct"] == 45
    assert entry["retention_pct"] == 20
    assert entry["learning_tune_count"] == 5
    assert entry["review_tune_count"] is None
    assert entry["retention_tune_count"] is None


async def test_plan_form_prefills_defaults_when_list_has_no_overrides(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    _, box, _, _ = await _seed(db, user)
    await create_list(db, user.id, box.id, "List A", PracticeListType.repertoire)

    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    marker = "window.__cairnListsByBox = "
    blob = resp.text.split(marker, 1)[1].split(";", 1)[0]
    entry = json.loads(blob)[str(box.id)][0]
    assert entry["warmup_pct"] == 10
    assert entry["review_pct"] == 10
    assert entry["learning_pct"] == 50
    assert entry["retention_pct"] == 30
    assert entry["learning_tune_count"] is None


async def test_plan_create_save_as_default_persists_preferences(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    _, box, _, _ = await _seed(db, user)
    plist = await create_list(db, user.id, box.id, "List A", PracticeListType.repertoire)

    resp = await client.post(
        "/practice/plan",
        data={
            "box_id": str(box.id),
            "total_minutes": "60",
            "list_id": str(plist.id),
            "warmup_pct": "15",
            "review_pct": "15",
            "learning_pct": "40",
            "retention_pct": "30",
            "learning_tune_count": "4",
            "save_as_default": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    saved = await get_list(db, plist.id)
    assert saved is not None
    assert saved.warmup_pct == 15
    assert saved.review_pct == 15
    assert saved.learning_pct == 40
    assert saved.retention_pct == 30
    assert saved.learning_tune_count == 4


async def test_plan_create_without_save_as_default_applies_but_does_not_persist(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    _, box, _, _ = await _seed(db, user)
    plist = await create_list(db, user.id, box.id, "List A", PracticeListType.repertoire)

    resp = await client.post(
        "/practice/plan",
        data={
            "box_id": str(box.id),
            "total_minutes": "100",
            "list_id": str(plist.id),
            "warmup_pct": "40",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    session_id = resp.headers["location"].rsplit("/", 1)[-1]

    # The submitted value shaped this session...
    session_resp = await client.get(f"/practice/session/{session_id}")
    marker = "window.__cairnSessionItems = "
    blob = session_resp.text.split(marker, 1)[1].split(";", 1)[0]
    items = json.loads(blob)
    warmup_item = next(i for i in items if i["itemType"] == "warmup")
    assert warmup_item["minutesAllocated"] == 40

    # ...but the list's own stored preference was never touched.
    saved = await get_list(db, plist.id)
    assert saved is not None
    assert saved.warmup_pct is None


async def test_plan_create_404_for_another_users_list(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    other = User(
        username="other-fiddler", email="other2@example.com", google_sub="google-sub-other2", role=Role.student
    )
    db.add(other)
    await db.flush()
    other_box = await create_box(db, other.id, "Someone Else's Box", [Instrument.fiddle])
    other_list = await create_list(db, other.id, other_box.id, "Someone Else's List", PracticeListType.repertoire)

    resp = await client.post(
        "/practice/plan",
        data={"box_id": str(box.id), "total_minutes": "30", "list_id": str(other_list.id)},
        follow_redirects=False,
    )
    assert resp.status_code == 404


async def test_session_detail_shows_items(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    session = await build_session(db, user.id, box.id, 30)
    resp = await client.get(f"/practice/session/{session.id}")
    assert resp.status_code == 200
    assert "Practice Session" in resp.text
    assert "Finish Session" in resp.text


async def test_session_detail_404_for_unknown(client: AsyncClient) -> None:
    resp = await client.get("/practice/session/9999")
    assert resp.status_code == 404


async def test_session_detail_shows_box_display_alias(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, tune, _ = await _seed(db, user)
    alias = await add_alias(db, tune.id, "Sunrise Reel")
    await set_display_alias(db, box.id, tune.id, alias.id)

    session = await build_session(db, user.id, box.id, 30)
    resp = await client.get(f"/practice/session/{session.id}")
    assert resp.status_code == 200
    assert '"title": "Sunrise Reel"' in resp.text
    assert '"title": "The Morning Dew"' not in resp.text
    assert "T:Sunrise Reel" in resp.text


async def test_session_detail_shows_box_transpose(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, tune, _ = await _seed(db, user)
    await set_transpose(db, box.id, tune.id, KeyRoot.E, 0)

    session = await build_session(db, user.id, box.id, 30)
    resp = await client.get(f"/practice/session/{session.id}")
    assert resp.status_code == 200
    assert '"keyLabel": "E Major"' in resp.text
    assert "K:E" in resp.text


async def test_session_detail_list_transpose_overrides_box_transpose(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    _, box, tune, _ = await _seed(db, user)
    await set_transpose(db, box.id, tune.id, KeyRoot.E, 0)

    practice_list = await create_list(db, user.id, box.id, "Session List", PracticeListType.repertoire)
    await add_tune_to_list(db, practice_list.id, tune.id)
    await update_list_entry_transpose(db, practice_list.id, tune.id, KeyRoot.G, 0)
    await activate_list(db, user.id, practice_list.id)

    session = await build_session(db, user.id, box.id, 30)
    resp = await client.get(f"/practice/session/{session.id}")
    assert resp.status_code == 200
    assert '"keyLabel": "G Major"' in resp.text
    assert "K:G" in resp.text


async def test_item_complete_returns_done_indicator(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    session = await build_session(db, user.id, box.id, 30)
    item = session.items[0]
    resp = await client.post(f"/practice/session/{session.id}/item/{item.id}/complete")
    assert resp.status_code == 200
    assert "Done" in resp.text


async def test_item_complete_404_for_wrong_session(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    session = await build_session(db, user.id, box.id, 30)
    item = session.items[0]
    resp = await client.post(f"/practice/session/9999/item/{item.id}/complete")
    assert resp.status_code == 404


async def test_session_finish_redirects(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    session = await build_session(db, user.id, box.id, 30)
    resp = await client.post(f"/practice/session/{session.id}/finish", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/practice/session/{session.id}"


async def test_item_rate_moving_on_returns_done_indicator(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    session = await build_session(db, user.id, box.id, 30)
    # Find the first tune item
    tune_item = next(i for i in session.items if i.tune_id)
    resp = await client.post(
        f"/practice/session/{session.id}/item/{tune_item.id}/rate",
        data={"confidence": "5"},
    )
    assert resp.status_code == 200
    assert "Done" in resp.text


async def test_item_rate_keep_working_returns_done_indicator(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    session = await build_session(db, user.id, box.id, 30)
    tune_item = next(i for i in session.items if i.tune_id)
    resp = await client.post(
        f"/practice/session/{session.id}/item/{tune_item.id}/rate",
        data={"confidence": "2"},
    )
    assert resp.status_code == 200
    assert "Done" in resp.text


async def test_item_rate_404_for_wrong_session(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    session = await build_session(db, user.id, box.id, 30)
    tune_item = next(i for i in session.items if i.tune_id)
    resp = await client.post(
        f"/practice/session/9999/item/{tune_item.id}/rate",
        data={"confidence": "5"},
    )
    assert resp.status_code == 404


async def test_plan_form_shows_lists_for_box(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    pl = await create_list(db, user.id, box.id, "Woodshed", PracticeListType.woodshed)
    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    assert "Active List" in resp.text
    # list data must be in the global, not buried in an HTML-attribute (double-quote breakage)
    assert "__cairnListsByBox" in resp.text
    assert "Woodshed" in resp.text
    assert str(pl.id) in resp.text


async def test_plan_create_activates_list(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    pl = await create_list(db, user.id, box.id, "My List", PracticeListType.repertoire)
    await client.post(
        "/practice/plan",
        data={"box_id": str(box.id), "total_minutes": "30", "list_id": str(pl.id)},
        follow_redirects=False,
    )
    active = await get_active_list(db, user.id)
    assert active is not None
    assert active.id == pl.id


async def test_plan_form_defaults_box_to_active_list_box(client: AsyncClient, db: AsyncSession, user: User) -> None:
    # Reproduce the bug: active list is under a non-first box; the form must
    # initialise boxId to that box so the list dropdown is populated.
    u, box, _, _ = await _seed(db, user)
    # Create a second box that sorts first alphabetically.
    box2 = await create_box(db, u.id, "AAA Box", [Instrument.fiddle])
    pl = await create_list(db, user.id, box.id, "My List", PracticeListType.repertoire)
    # Activate the list so active_list.box_id == box.id (not box2.id).
    await client.post(
        "/practice/plan",
        data={"box_id": str(box.id), "total_minutes": "30", "list_id": str(pl.id)},
        follow_redirects=False,
    )
    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    # The default_box_id in the rendered page must match the active list's box,
    # not the alphabetically-first box (box2).
    assert f"boxId: {box.id}" in resp.text
    assert f"boxId: {box2.id}" not in resp.text


async def test_plan_create_deactivates_list_when_none_chosen(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    pl = await create_list(db, user.id, box.id, "My List", PracticeListType.repertoire)
    await client.post(
        "/practice/plan",
        data={"box_id": str(box.id), "total_minutes": "30", "list_id": str(pl.id)},
        follow_redirects=False,
    )
    await client.post(
        "/practice/plan",
        data={"box_id": str(box.id), "total_minutes": "30", "list_id": ""},
        follow_redirects=False,
    )
    active = await get_active_list(db, user.id)
    assert active is None


async def test_session_finish_shows_finished_state(client: AsyncClient, db: AsyncSession, user: User) -> None:
    _, box, _, _ = await _seed(db, user)
    session = await build_session(db, user.id, box.id, 30)
    await client.post(f"/practice/session/{session.id}/finish", follow_redirects=False)
    resp = await client.get(f"/practice/session/{session.id}")
    assert resp.status_code == 200
    assert "Finished" in resp.text
    assert "Finish Session" not in resp.text


# ── cross-account ownership (#193) ──────────────────────────────────────────


async def _seed_other_owner_session(db: AsyncSession):
    """A practice session (with at least one item) owned by a different user
    than the `user` fixture's logged-in user."""
    other = User(username="other-fiddler", email="other@example.com", google_sub="google-sub-other", role=Role.student)
    db.add(other)
    await db.flush()
    box = await create_box(db, other.id, "Someone Else's Box", [Instrument.fiddle])
    tune = await create_tune(
        db,
        TuneCreate(
            title="Someone Else's Tune",
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
        ),
        abc_notation=_ABC,
    )
    await add_tune(db, box.id, tune.id)
    return await build_session(db, other.id, box.id, 30)


async def test_session_detail_404_for_another_users_session(client: AsyncClient, db: AsyncSession) -> None:
    session = await _seed_other_owner_session(db)
    resp = await client.get(f"/practice/session/{session.id}")
    assert resp.status_code == 404


async def test_item_complete_404_for_another_users_session(client: AsyncClient, db: AsyncSession) -> None:
    session = await _seed_other_owner_session(db)
    item = session.items[0]
    resp = await client.post(f"/practice/session/{session.id}/item/{item.id}/complete")
    assert resp.status_code == 404


async def test_item_rate_404_for_another_users_session(client: AsyncClient, db: AsyncSession) -> None:
    session = await _seed_other_owner_session(db)
    item = session.items[0]
    resp = await client.post(f"/practice/session/{session.id}/item/{item.id}/rate", data={"confidence": "5"})
    assert resp.status_code == 404


async def test_session_finish_404_for_another_users_session(client: AsyncClient, db: AsyncSession) -> None:
    session = await _seed_other_owner_session(db)
    resp = await client.post(f"/practice/session/{session.id}/finish")
    assert resp.status_code == 404


async def test_plan_create_404_for_another_users_box(client: AsyncClient, db: AsyncSession) -> None:
    other = User(
        username="other-fiddler2", email="other2@example.com", google_sub="google-sub-other2", role=Role.student
    )
    db.add(other)
    await db.flush()
    other_box = await create_box(db, other.id, "Someone Else's Box", [Instrument.fiddle])

    resp = await client.post(
        "/practice/plan", data={"box_id": str(other_box.id), "total_minutes": "30"}, follow_redirects=False
    )
    assert resp.status_code == 404
