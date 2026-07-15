from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, KeyMode, KeyRoot, ProgressStatus, TuneType, User
from cairn.schemas import TuneCreate
from cairn.services.boxes import add_tune, create_box
from cairn.services.spaced_rep import set_status
from cairn.services.tunes import create_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|"


async def _seed_tune(db: AsyncSession, title: str = "Morning Dew"):
    return await create_tune(
        db,
        TuneCreate(
            title=title,
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
        ),
        abc_notation=_ABC,
    )


async def test_dashboard_renders_empty_state(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text
    assert "Start Practice" in resp.text
    assert "No tune box selected" in resp.text


async def test_dashboard_accepts_head_for_uptime_checks(client: AsyncClient) -> None:
    # Uptime/status checkers (e.g. shields.io's website badge) probe with
    # HEAD, not GET — the root route must accept it or they report the app
    # as down even though it's actually up.
    resp = await client.head("/")
    assert resp.status_code == 200
    assert resp.text == ""


async def test_dashboard_shows_active_box(client: AsyncClient, db: AsyncSession, user: User) -> None:
    await create_box(db, user.id, "My Session Box", [Instrument.fiddle])
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "My Session Box" in resp.text


async def test_dashboard_shows_learning_tune(client: AsyncClient, db: AsyncSession, user: User) -> None:
    box = await create_box(db, user.id, "Box", [Instrument.fiddle])
    tune = await _seed_tune(db)
    await add_tune(db, box.id, tune.id)
    await set_status(db, user.id, box.id, tune.id, ProgressStatus.just_learning)
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Morning Dew" in resp.text
    assert "Currently learning" in resp.text
    assert "Just Learning" in resp.text


async def test_dashboard_shows_retention_due(client: AsyncClient, db: AsyncSession, user: User) -> None:
    box = await create_box(db, user.id, "Box", [Instrument.fiddle])
    tune = await _seed_tune(db)
    await add_tune(db, box.id, tune.id)
    await set_status(db, user.id, box.id, tune.id, ProgressStatus.committed)
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Due for review" in resp.text
    assert "Morning Dew" in resp.text


async def test_dashboard_empty_sections_when_no_progress(client: AsyncClient, db: AsyncSession, user: User) -> None:
    await create_box(db, user.id, "Box", [Instrument.fiddle])
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Nothing due for review today" in resp.text
    assert "No tunes in active learning" in resp.text
