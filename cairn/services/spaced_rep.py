from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import (
    PracticeListType,
    ProgressStatus,
    SettingProgress,
    StudentProgress,
    Tune,
)

MIN_EASE_FACTOR = 1.3
_INITIAL_EASE_FACTOR = 2.5
_STATUS_ORDER = list(ProgressStatus)


def next_review(
    confidence: int,
    interval_days: float,
    ease_factor: float,
) -> tuple[float, float]:
    """Simplified SM-2: compute the next interval and updated ease factor.

    confidence: 1 (complete blackout) to 5 (perfect recall)
    interval_days: days since last review; pass 0.0 for first-ever practice
    ease_factor: current ease factor (floor MIN_EASE_FACTOR)

    Returns (new_interval_days, new_ease_factor).

    Interval schedule for good recall (confidence >= 3):
        first practice  → 1 day
        second practice → 6 days
        subsequent      → prev_interval * new_ef  (minimum 1 day)

    Poor recall (confidence < 3) resets the interval to 1 day; the ease
    factor is still updated (decreased) so forgetting has a lasting cost.
    """
    delta = 0.1 - (5 - confidence) * (0.08 + (5 - confidence) * 0.02)
    new_ef = max(MIN_EASE_FACTOR, ease_factor + delta)

    if confidence < 3:
        new_interval = 1.0
    elif interval_days <= 0:
        new_interval = 1.0
    elif interval_days < 6:
        new_interval = 6.0
    else:
        new_interval = max(1.0, round(interval_days * new_ef, 1))

    return (new_interval, new_ef)


async def get_effective_status(
    db: AsyncSession,
    user_id: int,
    tune_id: int,
    box_id: int,
    setting_id: int | None,
) -> ProgressStatus:
    """Return the most specific progress status available.

    Checks SettingProgress first (if setting_id given), then StudentProgress,
    then defaults to just_learning.
    """
    if setting_id is not None:
        result = await db.execute(
            select(SettingProgress).where(
                SettingProgress.user_id == user_id,
                SettingProgress.setting_id == setting_id,
                SettingProgress.box_id == box_id,
            )
        )
        sp = result.scalar_one_or_none()
        if sp is not None:
            return sp.status

    result = await db.execute(
        select(StudentProgress).where(
            StudentProgress.user_id == user_id,
            StudentProgress.tune_id == tune_id,
            StudentProgress.box_id == box_id,
        )
    )
    progress = result.scalar_one_or_none()
    if progress is not None:
        return progress.status

    return ProgressStatus.just_learning


async def retire_setting_progress(
    db: AsyncSession,
    user_id: int,
    setting_id: int,
    box_id: int,
) -> None:
    """Delete a SettingProgress record, if it exists."""
    result = await db.execute(
        select(SettingProgress).where(
            SettingProgress.user_id == user_id,
            SettingProgress.setting_id == setting_id,
            SettingProgress.box_id == box_id,
        )
    )
    sp = result.scalar_one_or_none()
    if sp is not None:
        await db.delete(sp)
        await db.commit()


async def _advance_setting_progress(
    db: AsyncSession,
    user_id: int,
    setting_id: int,
    box_id: int,
    confidence: int,
    ceiling: ProgressStatus,
) -> None:
    """Upsert a SettingProgress record and advance/drop its status based on confidence.

    confidence >= 4 advances status one step (capped below ceiling).
    confidence < 3 drops status one step (floor: just_learning).
    Retires the record if status reaches or exceeds ceiling.

    No-ops when ceiling is just_learning — there is no room to track below the floor.
    """
    ceiling_idx = _STATUS_ORDER.index(ceiling)
    if ceiling_idx == 0:
        return

    result = await db.execute(
        select(SettingProgress).where(
            SettingProgress.user_id == user_id,
            SettingProgress.setting_id == setting_id,
            SettingProgress.box_id == box_id,
        )
    )
    sp = result.scalar_one_or_none()

    if sp is None:
        sp = SettingProgress(
            user_id=user_id,
            setting_id=setting_id,
            box_id=box_id,
            status=ProgressStatus.just_learning,
        )
        db.add(sp)
        await db.flush()  # assign id before potential delete

    current_idx = _STATUS_ORDER.index(sp.status)

    if confidence >= 4 and current_idx < ceiling_idx:
        sp.status = _STATUS_ORDER[current_idx + 1]
    elif confidence < 3 and current_idx > 0:
        sp.status = _STATUS_ORDER[current_idx - 1]

    if _STATUS_ORDER.index(sp.status) >= ceiling_idx:
        await db.delete(sp)

    await db.commit()


async def _check_repertoire_removal(
    db: AsyncSession,
    user_id: int,
    tune_id: int,
    box_id: int,
) -> None:
    """Remove a tune from the active Repertoire list if its effective status meets the goal."""
    from cairn.services.lists import get_active_list, remove_tune_from_list

    active_list = await get_active_list(db, user_id)
    if active_list is None or active_list.box_id != box_id or active_list.list_type != PracticeListType.repertoire:
        return

    list_entry = next((e for e in active_list.entries if e.tune_id == tune_id), None)
    if list_entry is None:
        return

    effective = await get_effective_status(db, user_id, tune_id, box_id, list_entry.setting_id)
    goal_idx = _STATUS_ORDER.index(active_list.progress_goal)
    if _STATUS_ORDER.index(effective) >= goal_idx:
        await remove_tune_from_list(db, active_list.id, tune_id)


async def record_practice(
    db: AsyncSession,
    user_id: int,
    box_id: int,
    tune_id: int,
    confidence: int,
) -> StudentProgress:
    """Record a practice rating and update the spaced-repetition schedule.

    Creates a StudentProgress row on first practice (status = just_learning)
    and updates it on all subsequent calls.  Status advancement is intentionally
    left to the manual route (POST /progress/{tune_id}/status) — this function
    only manages the spaced-repetition fields.

    Also advances SettingProgress when the active list has a setting entry for
    this tune, and checks Repertoire auto-removal.
    """
    result = await db.execute(
        select(StudentProgress).where(
            StudentProgress.user_id == user_id,
            StudentProgress.box_id == box_id,
            StudentProgress.tune_id == tune_id,
        )
    )
    record = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if record is None:
        new_interval, new_ef = next_review(confidence, 0.0, _INITIAL_EASE_FACTOR)
        record = StudentProgress(
            user_id=user_id,
            box_id=box_id,
            tune_id=tune_id,
            status=ProgressStatus.just_learning,
            confidence=confidence,
            interval_days=new_interval,
            ease_factor=new_ef,
            last_practiced=now,
            next_suggested=now + timedelta(days=new_interval),
        )
        db.add(record)
    else:
        new_interval, new_ef = next_review(confidence, record.interval_days, record.ease_factor)
        record.confidence = confidence
        record.interval_days = new_interval
        record.ease_factor = new_ef
        record.last_practiced = now
        record.next_suggested = now + timedelta(days=new_interval)

    await db.commit()
    await db.refresh(record)

    # Advance SettingProgress if the active list has a setting entry for this tune
    from cairn.services.lists import get_active_list

    active_list = await get_active_list(db, user_id)
    if active_list is not None and active_list.box_id == box_id:
        list_entry = next(
            (e for e in active_list.entries if e.tune_id == tune_id and e.setting_id is not None),
            None,
        )
        if list_entry is not None:
            await _advance_setting_progress(db, user_id, list_entry.setting_id, box_id, confidence, record.status)

        await _check_repertoire_removal(db, user_id, tune_id, box_id)

    return record


async def get_user_progress(
    db: AsyncSession,
    user_id: int,
    box_id: int,
) -> list[tuple[Tune, StudentProgress | None]]:
    """Return every tune paired with the user's progress for a specific box.

    Ordered alphabetically by sort_title.
    """
    tunes_result = await db.execute(
        select(Tune).order_by(Tune.sort_title).options(selectinload(Tune.settings))
    )
    tunes = list(tunes_result.scalars().all())
    if not tunes:
        return []
    progress_result = await db.execute(
        select(StudentProgress).where(
            StudentProgress.user_id == user_id,
            StudentProgress.box_id == box_id,
        )
    )
    progress_by_tune_id: dict[int, StudentProgress] = {p.tune_id: p for p in progress_result.scalars().all()}
    return [(tune, progress_by_tune_id.get(tune.id)) for tune in tunes]


async def advance_status_one(
    db: AsyncSession,
    user_id: int,
    box_id: int,
    tune_id: int,
) -> StudentProgress | None:
    """Advance a student's status by exactly one step.

    No-op if the record doesn't exist or is already at the top level.
    """
    result = await db.execute(
        select(StudentProgress).where(
            StudentProgress.user_id == user_id,
            StudentProgress.box_id == box_id,
            StudentProgress.tune_id == tune_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        return None

    current_idx = _STATUS_ORDER.index(record.status)
    if current_idx < len(_STATUS_ORDER) - 1:
        record.status = _STATUS_ORDER[current_idx + 1]
        await db.commit()
        await db.refresh(record)
        await _check_repertoire_removal(db, user_id, tune_id, box_id)

    return record


async def set_status(
    db: AsyncSession,
    user_id: int,
    box_id: int,
    tune_id: int,
    status: ProgressStatus,
) -> StudentProgress:
    """Manually set the ProgressStatus for a (user, box, tune) triple.

    Creates a StudentProgress row with sensible defaults if one doesn't exist yet.
    Checks Repertoire auto-removal after updating.
    """
    result = await db.execute(
        select(StudentProgress).where(
            StudentProgress.user_id == user_id,
            StudentProgress.box_id == box_id,
            StudentProgress.tune_id == tune_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        record = StudentProgress(
            user_id=user_id,
            box_id=box_id,
            tune_id=tune_id,
            status=status,
            confidence=3,
            interval_days=1.0,
            ease_factor=_INITIAL_EASE_FACTOR,
        )
        db.add(record)
    else:
        record.status = status
    await db.commit()
    await db.refresh(record)

    await _check_repertoire_removal(db, user_id, tune_id, box_id)

    return record
