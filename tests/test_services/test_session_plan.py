from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    Instrument,
    KeyMode,
    KeyRoot,
    PracticeListType,
    PracticeSession,
    PracticeSessionItem,
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
from cairn.services.lists import activate_list, add_tune_to_list, create_list, set_focus
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
    last_practiced: datetime | None = None,
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
        last_practiced=last_practiced,
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


# ── focus rotation, review queue, percentage/count allocation (#241/#244) ──────


@pytest.mark.asyncio
async def test_focus_rotation_orders_least_recently_practiced_first(db: AsyncSession):
    """Among focused entries, the one practiced longest ago (or never) is prioritized,
    overriding focus order (and, if tied, proximity-to-goal)."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)

    old = datetime.now(UTC) - timedelta(days=10)
    recent = datetime.now(UTC) - timedelta(hours=1)

    stale_tune = await _tune(db, "Stale Tune")
    fresh_tune = await _tune(db, "Fresh Tune")
    await add_tune(db, box.id, stale_tune)
    await add_tune(db, box.id, fresh_tune)
    await _progress(db, user.id, stale_tune, box.id, ProgressStatus.just_learning, last_practiced=old)
    await _progress(db, user.id, fresh_tune, box.id, ProgressStatus.just_learning, last_practiced=recent)

    plist = await create_list(db, user.id, box.id, "Focus List", PracticeListType.repertoire, ProgressStatus.committed)
    # Focus the more-recently-practiced tune first, to prove rotation beats focus order.
    await add_tune_to_list(db, plist.id, fresh_tune)
    await set_focus(db, plist.id, fresh_tune, True)
    await add_tune_to_list(db, plist.id, stale_tune)
    await set_focus(db, plist.id, stale_tune, True)
    await activate_list(db, user.id, plist.id)

    # 24 min: default 50% learning budget = 12 min, exactly one just_learning tune.
    session = await build_session(db, user.id, box.id, 24)

    learning_ids = {i.tune_id for i in session.items if i.item_type == SessionItemType.learning}
    assert learning_ids == {stale_tune}


@pytest.mark.asyncio
async def test_learning_queue_falls_back_to_full_list_when_nothing_focused(db: AsyncSession):
    """Zero focused entries: learning queue falls back to every below-goal list entry, unchanged."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)

    tune_a = await _tune(db, "Tune A")
    tune_b = await _tune(db, "Tune B")
    for tid in (tune_a, tune_b):
        await add_tune(db, box.id, tid)
        await _progress(db, user.id, tid, box.id, ProgressStatus.just_learning)

    plist = await create_list(db, user.id, box.id, "List", PracticeListType.repertoire, ProgressStatus.committed)
    await add_tune_to_list(db, plist.id, tune_a)
    await add_tune_to_list(db, plist.id, tune_b)
    await activate_list(db, user.id, plist.id)

    session = await build_session(db, user.id, box.id, 60)

    learning_ids = {i.tune_id for i in session.items if i.item_type == SessionItemType.learning}
    assert learning_ids == {tune_a, tune_b}
    assert not any(i.item_type == SessionItemType.review for i in session.items)


@pytest.mark.asyncio
async def test_review_queue_prefers_recent_session_and_reaches_into_older_one(db: AsyncSession):
    """Focused tunes bumped from today's rotation are pulled into review from past
    learning-item history -- most-recent qualifying session first, but still
    reaching into an older session for a tune the recent one doesn't cover."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)

    tune_ids = []
    for title in ["Tune A", "Tune B", "Tune C", "Tune D"]:
        tid = await _tune(db, title)
        await add_tune(db, box.id, tid)
        await _progress(db, user.id, tid, box.id, ProgressStatus.just_learning)
        tune_ids.append(tid)
    tune_a, tune_b, tune_c, tune_d = tune_ids

    plist = await create_list(db, user.id, box.id, "Focus List", PracticeListType.repertoire, ProgressStatus.committed)
    for tid in tune_ids:
        await add_tune_to_list(db, plist.id, tid)
        await set_focus(db, plist.id, tid, True)
    await activate_list(db, user.id, plist.id)

    # tune_d only ever showed up as a learning item in the OLDER session;
    # tune_c only in the more RECENT one.
    older_session = PracticeSession(user_id=user.id, box_id=box.id, started_at=datetime.now(UTC) - timedelta(days=3))
    db.add(older_session)
    await db.flush()
    db.add(
        PracticeSessionItem(
            session_id=older_session.id,
            item_type=SessionItemType.learning,
            tune_id=tune_d,
            minutes_allocated=12,
            completed=True,
        )
    )
    recent_session = PracticeSession(user_id=user.id, box_id=box.id, started_at=datetime.now(UTC) - timedelta(days=1))
    db.add(recent_session)
    await db.flush()
    db.add(
        PracticeSessionItem(
            session_id=recent_session.id,
            item_type=SessionItemType.learning,
            tune_id=tune_c,
            minutes_allocated=12,
            completed=True,
        )
    )
    await db.commit()

    # 60 min: default 50% learning budget = 30 min, fits tune_a + tune_b (24 min,
    # focus order) but not a third -- tune_c/tune_d are bumped.
    session = await build_session(db, user.id, box.id, 60)

    learning_ids = {i.tune_id for i in session.items if i.item_type == SessionItemType.learning}
    assert learning_ids == {tune_a, tune_b}

    review_tune_ids = [i.tune_id for i in session.items if i.item_type == SessionItemType.review]
    assert review_tune_ids == [tune_c, tune_d]


@pytest.mark.asyncio
async def test_learning_tune_count_cap(db: AsyncSession):
    """learning_tune_count caps learning items even when the minute budget allows more."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)

    tune_ids = []
    for title in ["Tune A", "Tune B", "Tune C"]:
        tid = await _tune(db, title)
        await add_tune(db, box.id, tid)
        await _progress(db, user.id, tid, box.id, ProgressStatus.session_ready)  # 2 min each
        tune_ids.append(tid)

    plist = await create_list(db, user.id, box.id, "List", PracticeListType.repertoire, ProgressStatus.committed)
    for tid in tune_ids:
        await add_tune_to_list(db, plist.id, tid)
    plist.learning_tune_count = 1
    db.add(plist)
    await db.commit()
    await activate_list(db, user.id, plist.id)

    # 60 min: default 50% learning budget = 30 min -- would fit all 3 (6 min total)
    # if uncapped, so the count cap is the only thing limiting this to 1.
    session = await build_session(db, user.id, box.id, 60)

    learning_ids = {i.tune_id for i in session.items if i.item_type == SessionItemType.learning}
    assert len(learning_ids) == 1


@pytest.mark.asyncio
async def test_retention_tune_count_cap(db: AsyncSession):
    """retention_tune_count caps retention items even when the minute budget allows more."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)
    past = datetime.now(UTC) - timedelta(days=1)

    tune_ids = []
    for title in ["Tune A", "Tune B", "Tune C"]:
        tid = await _tune(db, title)
        await add_tune(db, box.id, tid)
        await _progress(db, user.id, tid, box.id, ProgressStatus.committed, next_suggested=past)
        tune_ids.append(tid)

    plist = await create_list(db, user.id, box.id, "List", PracticeListType.repertoire, ProgressStatus.committed)
    for tid in tune_ids:
        await add_tune_to_list(db, plist.id, tid)
    plist.retention_tune_count = 1
    db.add(plist)
    await db.commit()
    await activate_list(db, user.id, plist.id)

    # 60 min: default 30% retention budget = 18 min -- would fit all 3 (6 min
    # total) if uncapped, so the count cap is the only limiting factor.
    session = await build_session(db, user.id, box.id, 60)

    retention_ids = {i.tune_id for i in session.items if i.item_type == SessionItemType.retention}
    assert len(retention_ids) == 1


@pytest.mark.asyncio
async def test_review_tune_count_cap(db: AsyncSession):
    """review_tune_count caps review items even when more qualifying candidates exist."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)

    tune_ids = []
    for title in ["Tune A", "Tune B", "Tune C", "Tune D", "Tune E"]:
        tid = await _tune(db, title)
        await add_tune(db, box.id, tid)
        await _progress(db, user.id, tid, box.id, ProgressStatus.just_learning)
        tune_ids.append(tid)
    tune_a, tune_b, tune_c, tune_d, tune_e = tune_ids

    plist = await create_list(db, user.id, box.id, "List", PracticeListType.repertoire, ProgressStatus.committed)
    for tid in tune_ids:
        await add_tune_to_list(db, plist.id, tid)
        await set_focus(db, plist.id, tid, True)
    plist.review_tune_count = 1
    db.add(plist)
    await db.commit()
    await activate_list(db, user.id, plist.id)

    past_session = PracticeSession(user_id=user.id, box_id=box.id, started_at=datetime.now(UTC) - timedelta(days=1))
    db.add(past_session)
    await db.flush()
    db.add_all(
        [
            PracticeSessionItem(
                session_id=past_session.id,
                item_type=SessionItemType.learning,
                tune_id=tid,
                minutes_allocated=12,
                completed=True,
            )
            for tid in (tune_b, tune_c, tune_d, tune_e)
        ]
    )
    await db.commit()

    # 60 min: 50% learning budget = 30 min fits tune_a + tune_b (24 min, focus
    # order), bumping tune_c/tune_d/tune_e -- all 3 qualify for review via the
    # past session, but review_tune_count caps it to 1.
    session = await build_session(db, user.id, box.id, 60)

    review_ids = {i.tune_id for i in session.items if i.item_type == SessionItemType.review}
    assert len(review_ids) == 1


@pytest.mark.asyncio
async def test_percentage_driven_warmup_budget(db: AsyncSession):
    """warmup_minutes is total_minutes * the list's own warmup_pct override, not the
    hardcoded 10% -- checked against a couple of total_minutes values."""
    user = await _user(db)
    box = await _box(db, user.id)
    await _warmup(db)

    plist = await create_list(db, user.id, box.id, "List", PracticeListType.repertoire, ProgressStatus.committed)
    plist.warmup_pct = 25
    db.add(plist)
    await db.commit()
    await activate_list(db, user.id, plist.id)

    for total_minutes in (40, 100):
        session = await build_session(db, user.id, box.id, total_minutes)
        warmup_item = next(i for i in session.items if i.item_type == SessionItemType.warmup)
        assert warmup_item.minutes_allocated == round(total_minutes * 0.25)
