from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, KeyMode, KeyRoot, PracticeListType, ProgressStatus, Role, TuneType, User, WarmupItem, WarmupType
from cairn.routers.practice import _STUB_USER_ID
from cairn.schemas import TuneCreate
from cairn.services.boxes import add_tune, create_box
from cairn.services.lists import get_active_list
from cairn.services.lists import create_list
from cairn.services.session_plan import build_session
from cairn.services.tunes import create_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|"


async def _seed(db: AsyncSession):
    """Create stub user (id=1), a TuneBox, and one just_learning tune."""
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

    warmup = WarmupItem(title="D Major Scale", warmup_type=WarmupType.scale, content=_ABC, difficulty=1)
    db.add(warmup)
    await db.flush()

    return u, box, tune, warmup


async def test_plan_form_renders(client: AsyncClient) -> None:
    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    assert "Plan a Practice Session" in resp.text


async def test_plan_form_shows_no_boxes_message(client: AsyncClient) -> None:
    # No user/box seeded — list_boxes returns empty
    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    assert "don't have any tune boxes" in resp.text


async def test_plan_form_shows_boxes(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    assert box.name in resp.text


async def test_plan_create_redirects_to_session(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    resp = await client.post(
        "/practice/plan", data={"box_id": str(box.id), "total_minutes": "30"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/practice/session/")


async def test_session_detail_shows_items(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    session = await build_session(db, _STUB_USER_ID, box.id, 30)
    resp = await client.get(f"/practice/session/{session.id}")
    assert resp.status_code == 200
    assert "Practice Session" in resp.text
    assert "Finish Session" in resp.text


async def test_session_detail_404_for_unknown(client: AsyncClient) -> None:
    resp = await client.get("/practice/session/9999")
    assert resp.status_code == 404


async def test_item_complete_returns_done_indicator(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    session = await build_session(db, _STUB_USER_ID, box.id, 30)
    item = session.items[0]
    resp = await client.post(f"/practice/session/{session.id}/item/{item.id}/complete")
    assert resp.status_code == 200
    assert "Done" in resp.text


async def test_item_complete_404_for_wrong_session(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    session = await build_session(db, _STUB_USER_ID, box.id, 30)
    item = session.items[0]
    resp = await client.post(f"/practice/session/9999/item/{item.id}/complete")
    assert resp.status_code == 404


async def test_session_finish_redirects(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    session = await build_session(db, _STUB_USER_ID, box.id, 30)
    resp = await client.post(f"/practice/session/{session.id}/finish", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/practice/session/{session.id}"


async def test_item_rate_moving_on_returns_done_indicator(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    session = await build_session(db, _STUB_USER_ID, box.id, 30)
    # Find the first tune item
    tune_item = next(i for i in session.items if i.tune_id)
    resp = await client.post(
        f"/practice/session/{session.id}/item/{tune_item.id}/rate",
        data={"confidence": "5"},
    )
    assert resp.status_code == 200
    assert "Done" in resp.text


async def test_item_rate_keep_working_returns_done_indicator(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    session = await build_session(db, _STUB_USER_ID, box.id, 30)
    tune_item = next(i for i in session.items if i.tune_id)
    resp = await client.post(
        f"/practice/session/{session.id}/item/{tune_item.id}/rate",
        data={"confidence": "2"},
    )
    assert resp.status_code == 200
    assert "Done" in resp.text


async def test_item_rate_404_for_wrong_session(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    session = await build_session(db, _STUB_USER_ID, box.id, 30)
    tune_item = next(i for i in session.items if i.tune_id)
    resp = await client.post(
        f"/practice/session/9999/item/{tune_item.id}/rate",
        data={"confidence": "5"},
    )
    assert resp.status_code == 404


async def test_plan_form_shows_lists_for_box(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    await create_list(db, _STUB_USER_ID, box.id, "Woodshed", PracticeListType.woodshed)
    resp = await client.get("/practice/plan")
    assert resp.status_code == 200
    assert "Woodshed" in resp.text
    assert "Active List" in resp.text


async def test_plan_create_activates_list(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    pl = await create_list(db, _STUB_USER_ID, box.id, "My List", PracticeListType.repertoire)
    await client.post(
        "/practice/plan",
        data={"box_id": str(box.id), "total_minutes": "30", "list_id": str(pl.id)},
        follow_redirects=False,
    )
    active = await get_active_list(db, _STUB_USER_ID)
    assert active is not None
    assert active.id == pl.id


async def test_plan_create_deactivates_list_when_none_chosen(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    pl = await create_list(db, _STUB_USER_ID, box.id, "My List", PracticeListType.repertoire)
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
    active = await get_active_list(db, _STUB_USER_ID)
    assert active is None


async def test_session_finish_shows_finished_state(client: AsyncClient, db: AsyncSession) -> None:
    _, box, _, _ = await _seed(db)
    session = await build_session(db, _STUB_USER_ID, box.id, 30)
    await client.post(f"/practice/session/{session.id}/finish", follow_redirects=False)
    resp = await client.get(f"/practice/session/{session.id}")
    assert resp.status_code == 200
    assert "Finished" in resp.text
    assert "Finish Session" not in resp.text
