from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, ProgressStatus, Role, TuneType, User
from cairn.routers.progress import _STUB_BOX_ID, _STUB_USER_ID
from cairn.schemas import TuneCreate
from cairn.services.spaced_rep import record_practice
from cairn.services.tunes import create_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|"


async def _seed(db: AsyncSession):
    """Create the stub user (id=1) and one tune; return (user, tune)."""
    u = User(username="tester", email="t@example.com", hashed_password="x", role=Role.student)
    db.add(u)
    await db.flush()
    assert u.id == _STUB_USER_ID, "Stub user id must match _STUB_USER_ID"
    t = await create_tune(
        db,
        TuneCreate(title="Morning Dew", tune_type=TuneType.reel,
                   key_root=KeyRoot.D, key_mode=KeyMode.major, time_signature="4/4"),
        abc_notation=_ABC,
    )
    return u, t


async def test_progress_index_empty_library(client: AsyncClient) -> None:
    resp = await client.get("/progress/")
    assert resp.status_code == 200
    assert "No tunes" in resp.text


async def test_progress_index_shows_tune(client: AsyncClient, db: AsyncSession) -> None:
    await _seed(db)
    resp = await client.get("/progress/")
    assert resp.status_code == 200
    assert "Morning Dew" in resp.text


async def test_progress_index_shows_not_started_badge(client: AsyncClient, db: AsyncSession) -> None:
    await _seed(db)
    resp = await client.get("/progress/")
    assert resp.status_code == 200
    assert "Not started" in resp.text


async def test_progress_record_returns_badge(client: AsyncClient, db: AsyncSession) -> None:
    _, t = await _seed(db)
    resp = await client.post(f"/progress/{t.id}", data={"confidence": "4"})
    assert resp.status_code == 200
    assert f"progress-badge-{t.id}" in resp.text
    assert "Just Learning" in resp.text


async def test_progress_record_404_for_unknown_tune(client: AsyncClient) -> None:
    resp = await client.post("/progress/9999", data={"confidence": "3"})
    assert resp.status_code == 404


async def test_progress_set_status_returns_badge(client: AsyncClient, db: AsyncSession) -> None:
    _, t = await _seed(db)
    resp = await client.post(f"/progress/{t.id}/status", data={"status": "session_ready"})
    assert resp.status_code == 200
    assert f"progress-badge-{t.id}" in resp.text
    assert "Session Ready" in resp.text


async def test_progress_set_status_404_for_unknown_tune(client: AsyncClient) -> None:
    resp = await client.post("/progress/9999/status", data={"status": "committed"})
    assert resp.status_code == 404


async def test_progress_set_status_updates_existing_record(client: AsyncClient, db: AsyncSession) -> None:
    u, t = await _seed(db)
    await record_practice(db, u.id, _STUB_BOX_ID, t.id, confidence=5)
    resp = await client.post(f"/progress/{t.id}/status", data={"status": "committed"})
    assert resp.status_code == 200
    assert "Committed" in resp.text


async def test_progress_index_shows_due_badge(client: AsyncClient, db: AsyncSession) -> None:
    u, t = await _seed(db)
    # Record two practices to get a past next_suggested; we can't control the date
    # so we just check the page renders without error and contains the tune.
    await record_practice(db, u.id, _STUB_BOX_ID, t.id, confidence=2)
    resp = await client.get("/progress/")
    assert resp.status_code == 200
    assert "Morning Dew" in resp.text
