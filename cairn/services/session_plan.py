import logging
import math
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import (
    PracticeList,
    PracticeListType,
    PracticeSession,
    PracticeSessionItem,
    ProgressStatus,
    SessionItemType,
    StudentProgress,
    Tune,
    TuneBoxEntry,
    WarmupItem,
)
from cairn.services.lists import get_active_list
from cairn.services.spaced_rep import advance_status_one, get_effective_status, record_practice

logger = logging.getLogger(__name__)

_STATUS_ORDER = list(ProgressStatus)

# Minutes to allocate per learning item, by effective status.
_LEARNING_MINUTES: dict[ProgressStatus, int] = {
    ProgressStatus.just_learning: 12,
    ProgressStatus.getting_there: 7,
    ProgressStatus.nearly_there: 4,
    ProgressStatus.session_ready: 2,
}

_RETENTION_MINUTES = 2

# Bars shown per status in the practice session view.
# None  → title + key only (no music rendered)
# -1    → full tune
# N > 0 → first N bars
_BARS_BY_STATUS: dict[ProgressStatus, int | None] = {
    ProgressStatus.just_learning: -1,
    ProgressStatus.getting_there: -1,
    ProgressStatus.nearly_there: 8,
    ProgressStatus.session_ready: 4,
    ProgressStatus.committed: None,
    ProgressStatus.performance_ready: None,
    ProgressStatus.solo_ready: None,
}


def bars_for_status(status: ProgressStatus) -> int | None:
    """Bars to display for a status.  None = title only, -1 = full tune."""
    return _BARS_BY_STATUS.get(status, -1)


def _is_due(next_suggested: datetime | None, now: datetime) -> bool:
    """True when next_suggested is in the past or has never been set.

    SQLite may return naive datetimes even when values were stored as tz-aware;
    strip timezone info before comparing so both sides are always comparable.
    """
    if next_suggested is None:
        return True
    return next_suggested.replace(tzinfo=None) <= now.replace(tzinfo=None)


async def _pick_warmup(db: AsyncSession) -> WarmupItem | None:
    result = await db.execute(select(WarmupItem).limit(1))
    return result.scalar_one_or_none()


async def _load_box_progress(
    db: AsyncSession,
    user_id: int,
    box_id: int,
) -> tuple[list[TuneBoxEntry], dict[int, StudentProgress]]:
    """Return all box entries and a tune_id → StudentProgress map for the user."""
    entries = list((await db.execute(select(TuneBoxEntry).where(TuneBoxEntry.box_id == box_id))).scalars().all())
    rows = list(
        (
            await db.execute(
                select(StudentProgress).where(
                    StudentProgress.user_id == user_id,
                    StudentProgress.box_id == box_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return entries, {p.tune_id: p for p in rows}


async def _build_list_learning_queue(
    db: AsyncSession,
    user_id: int,
    box_id: int,
    active_list: PracticeList,
) -> list[tuple[int, ProgressStatus, int | None]]:
    """Learning queue for list-based sessions: entries where effective_status < goal.

    Ordered closest-to-goal first so the most-advanced tunes get time when
    the session is short.
    """
    goal_idx = _STATUS_ORDER.index(active_list.progress_goal)
    scored: list[tuple[int, ProgressStatus, int | None, int]] = []
    for entry in active_list.entries:
        status = await get_effective_status(db, user_id, entry.tune_id, box_id, entry.setting_id)
        idx = _STATUS_ORDER.index(status)
        if idx < goal_idx:
            scored.append((entry.tune_id, status, entry.setting_id, idx))
    scored.sort(key=lambda x: -x[3])
    return [(t, s, sid) for t, s, sid, _ in scored]


async def _build_no_list_learning_queue(
    db: AsyncSession,
    user_id: int,
    box_id: int,
) -> list[tuple[int, ProgressStatus, int | None]]:
    """Learning queue without an active list: box tunes below committed, closest first."""
    committed_idx = _STATUS_ORDER.index(ProgressStatus.committed)
    entries, progress_map = await _load_box_progress(db, user_id, box_id)
    scored: list[tuple[int, ProgressStatus, int | None, int]] = []
    for entry in entries:
        progress = progress_map.get(entry.tune_id)
        status = progress.status if progress else ProgressStatus.just_learning
        idx = _STATUS_ORDER.index(status)
        if idx < committed_idx:
            scored.append((entry.tune_id, status, entry.setting_id, idx))
    scored.sort(key=lambda x: -x[3])
    return [(t, s, sid) for t, s, sid, _ in scored]


async def _build_repertoire_retention(
    db: AsyncSession,
    user_id: int,
    box_id: int,
    learning_ids: set[int],
    goal: ProgressStatus,
    now: datetime,
) -> list[tuple[int, int | None]]:
    """Retention for Repertoire sessions: box tunes at/above goal and due for review."""
    goal_idx = _STATUS_ORDER.index(goal)
    entries, progress_map = await _load_box_progress(db, user_id, box_id)
    result = []
    for entry in entries:
        if entry.tune_id in learning_ids:
            continue
        progress = progress_map.get(entry.tune_id)
        if progress is None:
            continue
        if _STATUS_ORDER.index(progress.status) < goal_idx:
            continue
        if not _is_due(progress.next_suggested, now):
            continue
        result.append((entry.tune_id, entry.setting_id))
    return result


async def _build_woodshed_retention(
    db: AsyncSession,
    user_id: int,
    box_id: int,
    learning_ids: set[int],
    goal: ProgressStatus,
    woodshed_tune_ids: set[int],
    now: datetime,
) -> list[tuple[int, int | None]]:
    """Retention for Woodshed sessions.

    Tunes tagged in the Woodshed list bypass the SM-2 gate and are listed first.
    Non-tagged tunes follow normal SM-2 scheduling.
    """
    goal_idx = _STATUS_ORDER.index(goal)
    entries, progress_map = await _load_box_progress(db, user_id, box_id)
    woodshed_ready: list[tuple[int, int | None]] = []
    sm2_ready: list[tuple[int, int | None]] = []
    for entry in entries:
        if entry.tune_id in learning_ids:
            continue
        progress = progress_map.get(entry.tune_id)
        if progress is None:
            continue
        if _STATUS_ORDER.index(progress.status) < goal_idx:
            continue
        if entry.tune_id in woodshed_tune_ids:
            woodshed_ready.append((entry.tune_id, entry.setting_id))
        elif _is_due(progress.next_suggested, now):
            sm2_ready.append((entry.tune_id, entry.setting_id))
    return woodshed_ready + sm2_ready


async def _build_no_list_retention(
    db: AsyncSession,
    user_id: int,
    box_id: int,
    learning_ids: set[int],
    now: datetime,
) -> list[tuple[int, int | None]]:
    """Retention without an active list: committed-or-above tunes due for review."""
    committed_idx = _STATUS_ORDER.index(ProgressStatus.committed)
    entries, progress_map = await _load_box_progress(db, user_id, box_id)
    result = []
    for entry in entries:
        if entry.tune_id in learning_ids:
            continue
        progress = progress_map.get(entry.tune_id)
        if progress is None:
            continue
        if _STATUS_ORDER.index(progress.status) < committed_idx:
            continue
        if not _is_due(progress.next_suggested, now):
            continue
        result.append((entry.tune_id, entry.setting_id))
    return result


async def build_session(
    db: AsyncSession,
    user_id: int,
    box_id: int,
    total_minutes: int,
) -> PracticeSession:
    """Build and persist a practice session plan.

    Allocates ~10 % to warmup (minimum 1 minute), then fills remaining time
    with learning items (ordered closest-to-goal first) followed by retention
    items (due for spaced-repetition review).

    Queue strategy depends on whether an active PracticeList exists for this box:
      Repertoire list → only list tunes in learning; box tunes at/above goal + due for retention
      Woodshed list   → same learning rule; woodshed tunes bypass SM-2 in retention
      No active list  → all box tunes below committed for learning; committed+ due for retention

    Returns the persisted PracticeSession with its items relationship loaded.
    """
    now = datetime.now(UTC)
    warmup_minutes = max(1, math.ceil(total_minutes * 0.10))
    remaining = total_minutes - warmup_minutes

    session = PracticeSession(user_id=user_id, box_id=box_id, started_at=now)
    db.add(session)
    await db.flush()

    items: list[PracticeSessionItem] = []

    # ── warmup ─────────────────────────────────────────────────────────────
    warmup = await _pick_warmup(db)
    if warmup:
        items.append(
            PracticeSessionItem(
                session_id=session.id,
                item_type=SessionItemType.warmup,
                warmup_id=warmup.id,
                minutes_allocated=warmup_minutes,
                completed=False,
            )
        )

    # ── resolve queue strategy ──────────────────────────────────────────────
    active_list = await get_active_list(db, user_id)
    if active_list is not None and active_list.box_id != box_id:
        active_list = None

    if active_list is not None:
        learning_queue = await _build_list_learning_queue(db, user_id, box_id, active_list)
        learning_ids = {t for t, _, _ in learning_queue}

        if active_list.list_type == PracticeListType.woodshed:
            woodshed_ids = {e.tune_id for e in active_list.entries}
            retention_queue = await _build_woodshed_retention(
                db, user_id, box_id, learning_ids, active_list.progress_goal, woodshed_ids, now
            )
        else:
            retention_queue = await _build_repertoire_retention(
                db, user_id, box_id, learning_ids, active_list.progress_goal, now
            )
    else:
        learning_queue = await _build_no_list_learning_queue(db, user_id, box_id)
        learning_ids = {t for t, _, _ in learning_queue}
        retention_queue = await _build_no_list_retention(db, user_id, box_id, learning_ids, now)

    # ── learning items ──────────────────────────────────────────────────────
    for tune_id, status, _setting_id in learning_queue:
        minutes = _LEARNING_MINUTES.get(status, _RETENTION_MINUTES)
        if remaining < minutes:
            break
        items.append(
            PracticeSessionItem(
                session_id=session.id,
                item_type=SessionItemType.learning,
                tune_id=tune_id,
                minutes_allocated=minutes,
                completed=False,
            )
        )
        remaining -= minutes

    # ── retention items ─────────────────────────────────────────────────────
    for tune_id, _setting_id in retention_queue:
        if remaining < _RETENTION_MINUTES:
            break
        items.append(
            PracticeSessionItem(
                session_id=session.id,
                item_type=SessionItemType.retention,
                tune_id=tune_id,
                minutes_allocated=_RETENTION_MINUTES,
                completed=False,
            )
        )
        remaining -= _RETENTION_MINUTES

    for item in items:
        db.add(item)
    await db.commit()

    result = await db.execute(
        select(PracticeSession).where(PracticeSession.id == session.id).options(selectinload(PracticeSession.items))
    )
    return result.scalar_one()


async def get_session(db: AsyncSession, session_id: int) -> PracticeSession | None:
    result = await db.execute(
        select(PracticeSession)
        .where(PracticeSession.id == session_id)
        .options(
            selectinload(PracticeSession.items).selectinload(PracticeSessionItem.tune).selectinload(Tune.settings),
            selectinload(PracticeSession.items).selectinload(PracticeSessionItem.warmup),
        )
    )
    return result.scalar_one_or_none()


async def _load_progress_map(
    db: AsyncSession,
    user_id: int,
    box_id: int,
    tune_ids: set[int],
) -> dict[int, ProgressStatus]:
    """Single query: tune_id → ProgressStatus for all tune_ids in a box."""
    if not tune_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(StudentProgress).where(
                    StudentProgress.user_id == user_id,
                    StudentProgress.tune_id.in_(tune_ids),
                    StudentProgress.box_id == box_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return {p.tune_id: p.status for p in rows}


async def complete_item(db: AsyncSession, session_id: int, item_id: int) -> PracticeSessionItem | None:
    session = await db.get(PracticeSession, session_id)
    if session is None:
        return None
    result = await db.execute(
        select(PracticeSessionItem).where(
            PracticeSessionItem.id == item_id,
            PracticeSessionItem.session_id == session_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None

    now = datetime.now(UTC)
    elapsed_total = (now.replace(tzinfo=None) - session.started_at.replace(tzinfo=None)).total_seconds() / 60
    already_spent_result = await db.execute(
        select(PracticeSessionItem.actual_minutes).where(
            PracticeSessionItem.session_id == session_id,
            PracticeSessionItem.actual_minutes.isnot(None),
        )
    )
    already_spent = sum(m for (m,) in already_spent_result.all())
    item.completed = True
    item.actual_minutes = max(1, round(elapsed_total - already_spent))
    await db.commit()
    result = await db.execute(
        select(PracticeSessionItem)
        .where(PracticeSessionItem.id == item_id)
        .options(selectinload(PracticeSessionItem.tune), selectinload(PracticeSessionItem.warmup))
    )
    return result.scalar_one_or_none()


async def rate_item(
    db: AsyncSession,
    session_id: int,
    item_id: int,
    user_id: int,
    confidence: int,
) -> PracticeSessionItem | None:
    """Complete a tune item, record the practice rating, and store the rating choice."""
    session = await db.get(PracticeSession, session_id)
    if session is None:
        return None

    item = await complete_item(db, session_id, item_id)
    if item is None:
        return None

    if item.tune_id and session.box_id:
        await record_practice(db, user_id, session.box_id, item.tune_id, confidence)
        if confidence >= 4:
            await advance_status_one(db, user_id, session.box_id, item.tune_id)

    result = await db.execute(
        select(PracticeSessionItem).where(PracticeSessionItem.id == item_id)
    )
    db_item = result.scalar_one_or_none()
    if db_item is not None:
        db_item.rating_given = confidence
        await db.commit()

    return item


async def finish_session(db: AsyncSession, session_id: int) -> PracticeSession | None:
    session = await db.get(PracticeSession, session_id)
    if session is None:
        return None
    now = datetime.now(UTC)
    session.ended_at = now
    elapsed = (now.replace(tzinfo=None) - session.started_at.replace(tzinfo=None)).total_seconds()
    session.total_minutes = max(1, int(elapsed / 60))
    await db.commit()
    return session
