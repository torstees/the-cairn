import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, ProgressStatus, Role, StudentProgress, TuneType, User
from cairn.schemas import TuneCreate
from cairn.services.spaced_rep import MIN_EASE_FACTOR, _INITIAL_EASE_FACTOR, next_review, record_practice
from cairn.services.tunes import create_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|"


# ── helpers ────────────────────────────────────────────────────────────────────

async def _user(db: AsyncSession) -> User:
    u = User(username="tester", email="tester@example.com", hashed_password="x", role=Role.student)
    db.add(u)
    await db.flush()
    return u


async def _tune(db: AsyncSession):
    return await create_tune(
        db,
        TuneCreate(title="Morning Dew", tune_type=TuneType.reel,
                   key_root=KeyRoot.D, key_mode=KeyMode.major, time_signature="4/4"),
        abc_notation=_ABC,
    )


# ── next_review — pure unit tests (no DB) ─────────────────────────────────────

def test_first_practice_interval_is_one_day():
    interval, _ = next_review(5, 0.0, _INITIAL_EASE_FACTOR)
    assert interval == 1.0


def test_second_practice_good_recall_interval_is_six_days():
    interval, _ = next_review(4, 1.0, _INITIAL_EASE_FACTOR)
    assert interval == 6.0


def test_interval_grows_after_six_days_confidence_five():
    interval, _ = next_review(5, 6.0, _INITIAL_EASE_FACTOR)
    expected = round(6.0 * (_INITIAL_EASE_FACTOR + 0.1), 1)
    assert interval == pytest.approx(expected)


def test_interval_grows_after_six_days_confidence_four():
    interval, _ = next_review(4, 6.0, _INITIAL_EASE_FACTOR)
    expected = round(6.0 * _INITIAL_EASE_FACTOR, 1)
    assert interval == pytest.approx(expected)


def test_interval_grows_after_six_days_confidence_three():
    interval, _ = next_review(3, 6.0, _INITIAL_EASE_FACTOR)
    new_ef = _INITIAL_EASE_FACTOR - 0.14
    expected = round(6.0 * new_ef, 1)
    assert interval == pytest.approx(expected)


def test_confidence_two_resets_interval_to_one():
    interval, _ = next_review(2, 30.0, _INITIAL_EASE_FACTOR)
    assert interval == 1.0


def test_confidence_one_resets_interval_to_one():
    interval, _ = next_review(1, 30.0, _INITIAL_EASE_FACTOR)
    assert interval == 1.0


def test_confidence_five_increases_ease_factor():
    _, ef = next_review(5, 6.0, _INITIAL_EASE_FACTOR)
    assert ef == pytest.approx(_INITIAL_EASE_FACTOR + 0.1)


def test_confidence_four_leaves_ease_factor_unchanged():
    _, ef = next_review(4, 6.0, _INITIAL_EASE_FACTOR)
    assert ef == pytest.approx(_INITIAL_EASE_FACTOR)


def test_confidence_three_decreases_ease_factor():
    _, ef = next_review(3, 6.0, _INITIAL_EASE_FACTOR)
    assert ef == pytest.approx(_INITIAL_EASE_FACTOR - 0.14)


def test_confidence_two_decreases_ease_factor_more_than_three():
    _, ef2 = next_review(2, 6.0, _INITIAL_EASE_FACTOR)
    _, ef3 = next_review(3, 6.0, _INITIAL_EASE_FACTOR)
    assert ef2 < ef3


def test_confidence_one_decreases_ease_factor_more_than_two():
    _, ef1 = next_review(1, 6.0, _INITIAL_EASE_FACTOR)
    _, ef2 = next_review(2, 6.0, _INITIAL_EASE_FACTOR)
    assert ef1 < ef2


def test_ease_factor_floor_is_respected():
    # Feed confidence=1 from an already-low EF; result must not go below MIN.
    _, ef = next_review(1, 1.0, MIN_EASE_FACTOR + 0.1)
    assert ef >= MIN_EASE_FACTOR


def test_ease_factor_cannot_go_below_minimum_even_after_many_resets():
    ef = _INITIAL_EASE_FACTOR
    for _ in range(20):
        _, ef = next_review(1, 1.0, ef)
    assert ef >= MIN_EASE_FACTOR


def test_interval_minimum_is_one_day():
    # Pathological case: tiny interval * low EF could underflow; must floor at 1.
    interval, _ = next_review(4, 0.5, MIN_EASE_FACTOR)
    assert interval >= 1.0


def test_all_confidence_values_produce_valid_outputs():
    for c in range(1, 6):
        interval, ef = next_review(c, 10.0, _INITIAL_EASE_FACTOR)
        assert interval >= 1.0
        assert ef >= MIN_EASE_FACTOR


# ── record_practice — integration tests ───────────────────────────────────────

async def test_record_practice_creates_record_on_first_call(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    rec = await record_practice(db, u.id, t.id, confidence=4)
    assert rec.id is not None
    assert rec.user_id == u.id
    assert rec.tune_id == t.id


async def test_record_practice_first_call_sets_just_learning(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    rec = await record_practice(db, u.id, t.id, confidence=5)
    assert rec.status == ProgressStatus.just_learning


async def test_record_practice_first_call_interval_is_one_day(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    rec = await record_practice(db, u.id, t.id, confidence=5)
    assert rec.interval_days == 1.0


async def test_record_practice_first_call_sets_last_practiced(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    rec = await record_practice(db, u.id, t.id, confidence=4)
    assert rec.last_practiced is not None
    assert rec.next_suggested is not None


async def test_record_practice_next_suggested_is_interval_ahead(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    rec = await record_practice(db, u.id, t.id, confidence=4)
    delta = (rec.next_suggested - rec.last_practiced).total_seconds()
    assert abs(delta - rec.interval_days * 86400) < 2  # within 2 seconds


async def test_record_practice_second_call_interval_is_six_days(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    await record_practice(db, u.id, t.id, confidence=4)
    rec = await record_practice(db, u.id, t.id, confidence=4)
    assert rec.interval_days == 6.0


async def test_record_practice_interval_grows_over_time(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    await record_practice(db, u.id, t.id, confidence=5)
    await record_practice(db, u.id, t.id, confidence=5)
    rec = await record_practice(db, u.id, t.id, confidence=5)
    assert rec.interval_days > 6.0


async def test_record_practice_low_confidence_resets_interval(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    # Build up interval
    await record_practice(db, u.id, t.id, confidence=5)
    await record_practice(db, u.id, t.id, confidence=5)
    await record_practice(db, u.id, t.id, confidence=5)
    # Then fail
    rec = await record_practice(db, u.id, t.id, confidence=2)
    assert rec.interval_days == 1.0


async def test_record_practice_does_not_duplicate_rows(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    await record_practice(db, u.id, t.id, confidence=4)
    await record_practice(db, u.id, t.id, confidence=4)
    count = (await db.execute(
        select(func.count()).where(
            StudentProgress.user_id == u.id,
            StudentProgress.tune_id == t.id,
        )
    )).scalar()
    assert count == 1


async def test_record_practice_updates_confidence(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    await record_practice(db, u.id, t.id, confidence=3)
    rec = await record_practice(db, u.id, t.id, confidence=5)
    assert rec.confidence == 5


async def test_record_practice_status_unchanged_on_update(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    await record_practice(db, u.id, t.id, confidence=5)
    rec = await record_practice(db, u.id, t.id, confidence=5)
    # Status stays just_learning — manual advancement via separate route
    assert rec.status == ProgressStatus.just_learning


async def test_record_practice_ease_factor_decreases_on_poor_recall(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    rec1 = await record_practice(db, u.id, t.id, confidence=1)
    assert rec1.ease_factor < _INITIAL_EASE_FACTOR


async def test_record_practice_ease_factor_respects_floor(db: AsyncSession) -> None:
    u = await _user(db)
    t = await _tune(db)
    for _ in range(10):
        rec = await record_practice(db, u.id, t.id, confidence=1)
    assert rec.ease_factor >= MIN_EASE_FACTOR
