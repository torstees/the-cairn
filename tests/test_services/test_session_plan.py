from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    Instrument,
    KeyMode,
    KeyRoot,
    PracticeListType,
    ProgressStatus,
    Role,
    SessionItemType,
    StudentProgress,
    TuneBox,
    TuneType,
    User,
    WarmupItem,
    WarmupType,
)
from cairn.schemas import TuneCreate
from cairn.services.boxes import add_tune, create_box
from cairn.services.lists import activate_list, add_tune_to_list, create_list
from cairn.services.session_plan import build_session
from cairn.services.tunes import create_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|"


# ── fixtures ────────────────────────────────────────────────────────────────


async def _user(db: AsyncSession) -> User:
    u = User(username="fiddler", email="fiddler@example.com", google_sub="google-sub-fiddler", role=Role.student)
    db.add(u)
    await db.flush()
    return u


async def _box(db: AsyncSession, user_id: int) -> TuneBox:
    return await create_box(db, user_id, "Session Box", [Instrument.fiddle])


async def _tune(db: AsyncSession, title: str) -> int:
    t = await create_tune(
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
    return t.id


async def _warmup(db: AsyncSession) -> WarmupItem:
    w = WarmupItem(title="D major scale", warmup_type=WarmupType.scale, content=_ABC, difficulty=1)
    db.add(w)
    await db.flush()
    return w


async def _progress(
    db: AsyncSession,
    user_id: int,
    tune_id: int,
    box_id: int,
    status: ProgressStatus,
    next_suggested: datetime | None = None,
) -> StudentProgress:
    p = StudentProgress(
        user_id=user_id,
        tune_id=tune_id,
        box_id=box_id,
        status=status,
        confidence=3,
        interval_days=1.0,
        ease_factor=2.5,
        next_suggested=next_suggested,
    )
    db.add(p)
    await db.flush()
    return p


# ── tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_short_session_15_min(db: AsyncSession):
    """15 min: 2 min warmup + one just_learning tune (12 min); total ≤ 15."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)
    tid = await _tune(db, "Morning Dew")
    await add_tune(db, box.id, tid)
    await _progress(db, user.id, tid, box.id, ProgressStatus.just_learning)

    session = await build_session(db, user.id, box.id, 15)

    types = [i.item_type for i in session.items]
    assert SessionItemType.warmup in types
    assert SessionItemType.learning in types
    assert sum(i.minutes_allocated for i in session.items) <= 15


@pytest.mark.asyncio
async def test_standard_session_45_min(db: AsyncSession):
    """45 min: warmup + multiple learning tunes + retention items."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)
    past = datetime.now(UTC) - timedelta(days=1)

    titles = ["Drowsy Maggie", "The Morning Dew", "Lark in the Morning", "Coleraine"]
    statuses = [
        ProgressStatus.just_learning,
        ProgressStatus.getting_there,
        ProgressStatus.committed,
        ProgressStatus.committed,
    ]
    for title, status in zip(titles, statuses, strict=True):
        tid = await _tune(db, title)
        await add_tune(db, box.id, tid)
        ns = past if status == ProgressStatus.committed else None
        await _progress(db, user.id, tid, box.id, status, next_suggested=ns)

    session = await build_session(db, user.id, box.id, 45)

    types = [i.item_type for i in session.items]
    assert SessionItemType.warmup in types
    assert SessionItemType.learning in types
    assert SessionItemType.retention in types
    assert sum(i.minutes_allocated for i in session.items) <= 45


@pytest.mark.asyncio
async def test_repertoire_list_restricts_learning_to_list_tunes(db: AsyncSession):
    """Repertoire list: only list tunes appear in the learning queue."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)

    list_tune = await _tune(db, "The Maid Behind the Bar")
    other_tune = await _tune(db, "The Silver Spear")
    for tid in [list_tune, other_tune]:
        await add_tune(db, box.id, tid)
        await _progress(db, user.id, tid, box.id, ProgressStatus.just_learning)

    plist = await create_list(
        db, user.id, box.id, "Current Tunes", PracticeListType.repertoire, ProgressStatus.committed
    )
    await add_tune_to_list(db, plist.id, list_tune)
    await activate_list(db, user.id, plist.id)

    session = await build_session(db, user.id, box.id, 30)

    learning_ids = {i.tune_id for i in session.items if i.item_type == SessionItemType.learning}
    assert list_tune in learning_ids
    assert other_tune not in learning_ids


@pytest.mark.asyncio
async def test_woodshed_list_bypasses_sm2_for_retention(db: AsyncSession):
    """Woodshed tunes at/above goal appear in retention even when SM-2 says not due."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)
    future = datetime.now(UTC) + timedelta(days=10)

    woodshed_tune = await _tune(db, "The Kesh Jig")
    await add_tune(db, box.id, woodshed_tune)
    await _progress(db, user.id, woodshed_tune, box.id, ProgressStatus.committed, next_suggested=future)

    plist = await create_list(db, user.id, box.id, "Deep Work", PracticeListType.woodshed, ProgressStatus.committed)
    await add_tune_to_list(db, plist.id, woodshed_tune)
    await activate_list(db, user.id, plist.id)

    session = await build_session(db, user.id, box.id, 30)

    retention_ids = {i.tune_id for i in session.items if i.item_type == SessionItemType.retention}
    assert woodshed_tune in retention_ids


@pytest.mark.asyncio
async def test_no_active_list_uses_full_box(db: AsyncSession):
    """Without an active list, all box tunes below committed enter the learning queue."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)

    tunes = []
    for title in ["The Connaughtman's Rambles", "The Star of Munster"]:
        tid = await _tune(db, title)
        await add_tune(db, box.id, tid)
        await _progress(db, user.id, tid, box.id, ProgressStatus.getting_there)
        tunes.append(tid)

    session = await build_session(db, user.id, box.id, 30)

    learning_ids = {i.tune_id for i in session.items if i.item_type == SessionItemType.learning}
    assert all(tid in learning_ids for tid in tunes)


@pytest.mark.asyncio
async def test_no_tunes_due_for_retention(db: AsyncSession):
    """When no tunes are due for review the retention queue is empty."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)
    future = datetime.now(UTC) + timedelta(days=7)

    tid = await _tune(db, "The Bucks of Oranmore")
    await add_tune(db, box.id, tid)
    await _progress(db, user.id, tid, box.id, ProgressStatus.committed, next_suggested=future)

    session = await build_session(db, user.id, box.id, 30)

    assert not any(i.item_type == SessionItemType.retention for i in session.items)


@pytest.mark.asyncio
async def test_all_tunes_committed_produces_retention_only(db: AsyncSession):
    """When every box tune is committed and due, the session has no learning items."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)
    past = datetime.now(UTC) - timedelta(days=1)

    for title in ["Cooley's", "Gusty's Frolics"]:
        tid = await _tune(db, title)
        await add_tune(db, box.id, tid)
        await _progress(db, user.id, tid, box.id, ProgressStatus.committed, next_suggested=past)

    session = await build_session(db, user.id, box.id, 30)

    assert not any(i.item_type == SessionItemType.learning for i in session.items)
    assert any(i.item_type == SessionItemType.retention for i in session.items)
