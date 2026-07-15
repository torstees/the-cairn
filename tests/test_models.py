from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    Instrument,
    KeyMode,
    KeyRoot,
    OrnamentationLevel,
    PracticeSession,
    PracticeSessionItem,
    ProgressStatus,
    Role,
    SessionItemType,
    StudentProgress,
    Tune,
    TuneDifficulty,
    TuneSet,
    TuneSetMember,
    TuneSetting,
    TuneType,
    User,
    WarmupItem,
    WarmupType,
)
from cairn.services.boxes import create_box


def _user(**kwargs) -> User:
    defaults = dict(
        username="alice",
        email="alice@example.com",
        google_sub="google-sub-alice",
        role=Role.student,
    )
    return User(**{**defaults, **kwargs})


def _tune(**kwargs) -> Tune:
    defaults = dict(
        title="The Morning Dew",
        sort_title="Morning Dew",
        tune_type=TuneType.reel,
        key_root=KeyRoot.D,
        key_mode=KeyMode.major,
        time_signature="4/4",
    )
    return Tune(**{**defaults, **kwargs})


async def test_user(db: AsyncSession) -> None:
    user = _user()
    db.add(user)
    await db.commit()
    await db.refresh(user)
    assert user.id is not None
    assert user.created_at is not None


async def test_tune(db: AsyncSession) -> None:
    tune = _tune()
    db.add(tune)
    await db.commit()
    await db.refresh(tune)
    assert tune.id is not None
    assert tune.created_at is not None


async def test_tune_setting(db: AsyncSession) -> None:
    tune = _tune()
    db.add(tune)
    await db.flush()

    setting = TuneSetting(
        tune_id=tune.id,
        label="Standard",
        abc_notation="X:1\nT:The Morning Dew\nM:4/4\nK:D\n|:ABcd|efga:|\n",
        is_core=True,
        ornamentation_level=OrnamentationLevel.none,
    )
    db.add(setting)
    await db.commit()
    await db.refresh(setting)
    assert setting.id is not None
    assert setting.created_at is not None


async def test_tune_difficulty(db: AsyncSession) -> None:
    tune = _tune()
    db.add(tune)
    await db.flush()

    diff = TuneDifficulty(tune_id=tune.id, instrument=Instrument.fiddle, difficulty=3)
    db.add(diff)
    await db.commit()
    await db.refresh(diff)
    assert diff.id is not None
    assert diff.created_at is not None


async def test_tune_set(db: AsyncSession) -> None:
    tune_set = TuneSet(title="Session Opener Set")
    db.add(tune_set)
    await db.commit()
    await db.refresh(tune_set)
    assert tune_set.id is not None
    assert tune_set.created_at is not None


async def test_tune_set_member(db: AsyncSession) -> None:
    tune = _tune()
    tune_set = TuneSet(title="Session Opener Set")
    db.add_all([tune, tune_set])
    await db.flush()

    member = TuneSetMember(set_id=tune_set.id, tune_id=tune.id, order=1)
    db.add(member)
    await db.commit()
    await db.refresh(member)
    assert member.id is not None
    assert member.created_at is not None


async def test_warmup_item(db: AsyncSession) -> None:
    warmup = WarmupItem(
        title="D Major Scale",
        warmup_type=WarmupType.scale,
        content="X:1\nT:D Major Scale\nM:4/4\nK:D\n|DEFGABcd|\n",
        difficulty=1,
    )
    db.add(warmup)
    await db.commit()
    await db.refresh(warmup)
    assert warmup.id is not None
    assert warmup.created_at is not None


async def test_student_progress(db: AsyncSession) -> None:
    user = _user()
    tune = _tune()
    db.add_all([user, tune])
    await db.flush()

    box = await create_box(db, user.id, "Session Box", [Instrument.flute])

    progress = StudentProgress(
        user_id=user.id,
        tune_id=tune.id,
        box_id=box.id,
        status=ProgressStatus.just_learning,
        confidence=3,
        interval_days=1.0,
        ease_factor=2.5,
        teacher_approved=False,
    )
    db.add(progress)
    await db.commit()
    await db.refresh(progress)
    assert progress.id is not None
    assert progress.created_at is not None


async def test_practice_session(db: AsyncSession) -> None:
    user = _user()
    db.add(user)
    await db.flush()

    session = PracticeSession(
        user_id=user.id,
        started_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    assert session.id is not None
    assert session.created_at is not None


async def test_practice_session_item(db: AsyncSession) -> None:
    user = _user()
    tune = _tune()
    db.add_all([user, tune])
    await db.flush()

    session = PracticeSession(user_id=user.id, started_at=datetime.now(timezone.utc))
    db.add(session)
    await db.flush()

    item = PracticeSessionItem(
        session_id=session.id,
        item_type=SessionItemType.learning,
        tune_id=tune.id,
        minutes_allocated=10,
        completed=False,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    assert item.id is not None
    assert item.created_at is not None
