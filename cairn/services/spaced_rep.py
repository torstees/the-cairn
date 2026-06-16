from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import ProgressStatus, StudentProgress

MIN_EASE_FACTOR = 1.3
_INITIAL_EASE_FACTOR = 2.5


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


async def record_practice(
    db: AsyncSession,
    user_id: int,
    tune_id: int,
    confidence: int,
) -> StudentProgress:
    """Record a practice rating and update the spaced-repetition schedule.

    Creates a StudentProgress row on first practice (status = just_learning)
    and updates it on all subsequent calls.  Status advancement is intentionally
    left to the manual route (POST /progress/{tune_id}/status) — this function
    only manages the spaced-repetition fields.
    """
    result = await db.execute(
        select(StudentProgress).where(
            StudentProgress.user_id == user_id,
            StudentProgress.tune_id == tune_id,
        )
    )
    record = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if record is None:
        new_interval, new_ef = next_review(confidence, 0.0, _INITIAL_EASE_FACTOR)
        record = StudentProgress(
            user_id=user_id,
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
    return record
