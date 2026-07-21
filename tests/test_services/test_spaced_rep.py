import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    Instrument,
    KeyMode,
    KeyRoot,
    PracticeListType,
    ProgressStatus,
    Role,
    SettingProgress,
    StudentProgress,
    TuneBox,
    TuneType,
    User,
)
from cairn.schemas import TuneCreate
from cairn.services.boxes import create_box
from cairn.services.lists import activate_list, add_tune_to_list, create_list, set_focus
from cairn.services.spaced_rep import (
    _INITIAL_EASE_FACTOR,
    MIN_EASE_FACTOR,
    advance_status_one,
    get_effective_status,
    get_user_progress,
    next_review,
    record_practice,
    retire_setting_progress,
    set_status,
)
from cairn.services.tunes import create_tune, get_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|"


# ── helpers ────────────────────────────────────────────────────────────────────


async def _user(db: AsyncSession) -> User:
    u = User(username="tester", email="tester@example.com", google_sub="google-sub-tester", role=Role.student)
    db.add(u)
    await db.flush()
    return u


async def _box(db: AsyncSession, user_id: int) -> TuneBox:
    return await create_box(db, user_id, "Session Box", [Instrument.fiddle])


async def _tune(db: AsyncSession):
    return await create_tune(
        db,
        TuneCreate(
            title="Morning Dew",
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
        ),
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
    b = await _box(db, u.id)
    t = await _tune(db)
    rec = await record_practice(db, u.id, b.id, t.id, confidence=4)
    assert rec.id is not None
    assert rec.user_id == u.id
    assert rec.tune_id == t.id


async def test_record_practice_first_call_sets_just_learning(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    rec = await record_practice(db, u.id, b.id, t.id, confidence=5)
    assert rec.status == ProgressStatus.just_learning


async def test_record_practice_first_call_interval_is_one_day(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    rec = await record_practice(db, u.id, b.id, t.id, confidence=5)
    assert rec.interval_days == 1.0


async def test_record_practice_first_call_sets_last_practiced(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    rec = await record_practice(db, u.id, b.id, t.id, confidence=4)
    assert rec.last_practiced is not None
    assert rec.next_suggested is not None


async def test_record_practice_next_suggested_is_interval_ahead(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    rec = await record_practice(db, u.id, b.id, t.id, confidence=4)
    delta = (rec.next_suggested - rec.last_practiced).total_seconds()
    assert abs(delta - rec.interval_days * 86400) < 2  # within 2 seconds


async def test_record_practice_second_call_interval_is_six_days(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await record_practice(db, u.id, b.id, t.id, confidence=4)
    rec = await record_practice(db, u.id, b.id, t.id, confidence=4)
    assert rec.interval_days == 6.0


async def test_record_practice_interval_grows_over_time(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    rec = await record_practice(db, u.id, b.id, t.id, confidence=5)
    assert rec.interval_days > 6.0


async def test_record_practice_low_confidence_resets_interval(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    # Build up interval
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    # Then fail
    rec = await record_practice(db, u.id, b.id, t.id, confidence=2)
    assert rec.interval_days == 1.0


async def test_record_practice_does_not_duplicate_rows(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await record_practice(db, u.id, b.id, t.id, confidence=4)
    await record_practice(db, u.id, b.id, t.id, confidence=4)
    count = (
        await db.execute(
            select(func.count()).where(
                StudentProgress.user_id == u.id,
                StudentProgress.tune_id == t.id,
            )
        )
    ).scalar()
    assert count == 1


async def test_record_practice_updates_confidence(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await record_practice(db, u.id, b.id, t.id, confidence=3)
    rec = await record_practice(db, u.id, b.id, t.id, confidence=5)
    assert rec.confidence == 5


async def test_record_practice_status_unchanged_on_update(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    rec = await record_practice(db, u.id, b.id, t.id, confidence=5)
    # Status stays just_learning — manual advancement via separate route
    assert rec.status == ProgressStatus.just_learning


async def test_record_practice_ease_factor_decreases_on_poor_recall(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    rec1 = await record_practice(db, u.id, b.id, t.id, confidence=1)
    assert rec1.ease_factor < _INITIAL_EASE_FACTOR


async def test_record_practice_ease_factor_respects_floor(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    for _ in range(10):
        rec = await record_practice(db, u.id, b.id, t.id, confidence=1)
    assert rec.ease_factor >= MIN_EASE_FACTOR


# ── get_user_progress ─────────────────────────────────────────────────────────


async def test_get_user_progress_returns_all_tunes(db: AsyncSession) -> None:
    u = await _user(db)
    t1 = await _tune(db)
    t2 = await create_tune(
        db,
        TuneCreate(
            title="Swallowtail Jig",
            tune_type=TuneType.jig,
            key_root=KeyRoot.G,
            key_mode=KeyMode.major,
            time_signature="6/8",
        ),
        abc_notation=_ABC,
    )
    pairs = await get_user_progress(db, u.id, 1)
    tune_ids = [t.id for t, _ in pairs]
    assert t1.id in tune_ids
    assert t2.id in tune_ids


async def test_get_user_progress_none_before_first_practice(db: AsyncSession) -> None:
    u = await _user(db)
    await _tune(db)
    pairs = await get_user_progress(db, u.id, 1)
    assert all(p is None for _, p in pairs)


async def test_get_user_progress_shows_existing_record(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await record_practice(db, u.id, b.id, t.id, confidence=4)
    pairs = await get_user_progress(db, u.id, b.id)
    by_id = {tune.id: progress for tune, progress in pairs}
    assert by_id[t.id] is not None
    assert by_id[t.id].confidence == 4


async def test_get_user_progress_empty_library(db: AsyncSession) -> None:
    u = await _user(db)
    pairs = await get_user_progress(db, u.id, 1)
    assert pairs == []


async def test_get_user_progress_ordered_by_sort_title(db: AsyncSession) -> None:
    u = await _user(db)
    await create_tune(
        db,
        TuneCreate(
            title="The Merry Blacksmith",
            tune_type=TuneType.reel,
            key_root=KeyRoot.A,
            key_mode=KeyMode.major,
            time_signature="4/4",
        ),
        abc_notation=_ABC,
    )
    await create_tune(
        db,
        TuneCreate(
            title="Ashokan Farewell",
            tune_type=TuneType.waltz,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="3/4",
        ),
        abc_notation=_ABC,
    )
    pairs = await get_user_progress(db, u.id, 1)
    titles = [t.title for t, _ in pairs]
    # "Ashokan Farewell" sorts before "The Merry Blacksmith" (article stripped)
    assert titles.index("Ashokan Farewell") < titles.index("The Merry Blacksmith")


# ── set_status ────────────────────────────────────────────────────────────────


async def test_set_status_creates_record_when_none_exists(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    rec = await set_status(db, u.id, b.id, t.id, ProgressStatus.session_ready)
    assert rec.status == ProgressStatus.session_ready
    assert rec.user_id == u.id
    assert rec.tune_id == t.id


async def test_set_status_updates_existing_record(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    rec = await set_status(db, u.id, b.id, t.id, ProgressStatus.committed)
    assert rec.status == ProgressStatus.committed


async def test_set_status_preserves_spaced_rep_fields(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    original = await record_practice(db, u.id, b.id, t.id, confidence=5)
    rec = await set_status(db, u.id, b.id, t.id, ProgressStatus.nearly_there)
    # SR fields must not be touched by a manual status change
    assert rec.interval_days == original.interval_days
    assert rec.ease_factor == original.ease_factor


async def test_set_status_new_record_has_sensible_defaults(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    rec = await set_status(db, u.id, b.id, t.id, ProgressStatus.getting_there)
    assert rec.confidence == 3
    assert rec.interval_days == 1.0
    assert rec.ease_factor == _INITIAL_EASE_FACTOR


# ── helpers for SettingProgress tests ─────────────────────────────────────────


async def _setting_id(db: AsyncSession) -> tuple:
    """Return (tune, setting_id) for a freshly created tune."""
    t = await _tune(db)
    loaded = await get_tune(db, t.id)
    return t, loaded.settings[0].id


async def _active_list_with_setting(db, user_id, box_id, tune_id, setting_id):
    pl = await create_list(db, user_id, box_id, "Test List", PracticeListType.repertoire)
    await add_tune_to_list(db, pl.id, tune_id, setting_id=setting_id)
    await activate_list(db, user_id, pl.id)
    return pl


# ── get_effective_status ───────────────────────────────────────────────────────


async def test_get_effective_status_returns_just_learning_when_no_records(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    status = await get_effective_status(db, u.id, t.id, b.id, None)
    assert status == ProgressStatus.just_learning


async def test_get_effective_status_returns_student_progress_status(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.session_ready)
    status = await get_effective_status(db, u.id, t.id, b.id, None)
    assert status == ProgressStatus.session_ready


async def test_get_effective_status_returns_setting_progress_when_present(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t, sid = await _setting_id(db)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.committed)
    sp = SettingProgress(user_id=u.id, setting_id=sid, box_id=b.id, status=ProgressStatus.getting_there)
    db.add(sp)
    await db.commit()
    status = await get_effective_status(db, u.id, t.id, b.id, sid)
    assert status == ProgressStatus.getting_there


async def test_get_effective_status_falls_back_to_student_when_no_setting_record(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t, sid = await _setting_id(db)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.nearly_there)
    status = await get_effective_status(db, u.id, t.id, b.id, sid)
    assert status == ProgressStatus.nearly_there


# ── retire_setting_progress ────────────────────────────────────────────────────


async def test_retire_setting_progress_deletes_record(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t, sid = await _setting_id(db)
    sp = SettingProgress(user_id=u.id, setting_id=sid, box_id=b.id, status=ProgressStatus.just_learning)
    db.add(sp)
    await db.commit()
    await retire_setting_progress(db, u.id, sid, b.id)
    result = await db.execute(
        __import__("sqlalchemy", fromlist=["select"])
        .select(SettingProgress)
        .where(
            SettingProgress.user_id == u.id,
            SettingProgress.setting_id == sid,
            SettingProgress.box_id == b.id,
        )
    )
    assert result.scalar_one_or_none() is None


async def test_retire_setting_progress_noop_when_no_record(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t, sid = await _setting_id(db)
    await retire_setting_progress(db, u.id, sid, b.id)  # must not raise


# ── record_practice + SettingProgress ─────────────────────────────────────────


async def test_record_practice_creates_setting_progress_when_active_list_has_setting(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t, sid = await _setting_id(db)
    # StudentProgress must be above just_learning so _advance_setting_progress has room
    await set_status(db, u.id, b.id, t.id, ProgressStatus.session_ready)
    await _active_list_with_setting(db, u.id, b.id, t.id, sid)
    await record_practice(db, u.id, b.id, t.id, confidence=4)
    from sqlalchemy import select as sa_select

    result = await db.execute(
        sa_select(SettingProgress).where(
            SettingProgress.user_id == u.id,
            SettingProgress.setting_id == sid,
            SettingProgress.box_id == b.id,
        )
    )
    sp = result.scalar_one_or_none()
    assert sp is not None
    assert sp.status == ProgressStatus.getting_there


async def test_record_practice_advances_setting_progress_on_high_confidence(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    u = await _user(db)
    b = await _box(db, u.id)
    t, sid = await _setting_id(db)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.session_ready)
    await _active_list_with_setting(db, u.id, b.id, t.id, sid)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    result = await db.execute(
        sa_select(SettingProgress).where(
            SettingProgress.user_id == u.id,
            SettingProgress.setting_id == sid,
            SettingProgress.box_id == b.id,
        )
    )
    sp = result.scalar_one_or_none()
    assert sp is not None
    assert sp.status == ProgressStatus.nearly_there


async def test_record_practice_drops_setting_progress_on_low_confidence(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    u = await _user(db)
    b = await _box(db, u.id)
    t, sid = await _setting_id(db)
    # Set StudentProgress high enough that nearly_there is well below ceiling
    await set_status(db, u.id, b.id, t.id, ProgressStatus.committed)
    await _active_list_with_setting(db, u.id, b.id, t.id, sid)
    sp = SettingProgress(user_id=u.id, setting_id=sid, box_id=b.id, status=ProgressStatus.nearly_there)
    db.add(sp)
    await db.commit()
    await record_practice(db, u.id, b.id, t.id, confidence=1)
    result = await db.execute(
        sa_select(SettingProgress).where(
            SettingProgress.user_id == u.id,
            SettingProgress.setting_id == sid,
            SettingProgress.box_id == b.id,
        )
    )
    sp = result.scalar_one_or_none()
    assert sp is not None
    assert sp.status == ProgressStatus.getting_there


async def test_record_practice_retires_setting_progress_when_caught_up(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    u = await _user(db)
    b = await _box(db, u.id)
    t, sid = await _setting_id(db)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.getting_there)
    await _active_list_with_setting(db, u.id, b.id, t.id, sid)
    sp = SettingProgress(user_id=u.id, setting_id=sid, box_id=b.id, status=ProgressStatus.just_learning)
    db.add(sp)
    await db.commit()
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    result = await db.execute(
        sa_select(SettingProgress).where(
            SettingProgress.user_id == u.id,
            SettingProgress.setting_id == sid,
            SettingProgress.box_id == b.id,
        )
    )
    assert result.scalar_one_or_none() is None


async def test_record_practice_no_setting_progress_without_active_list(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    u = await _user(db)
    b = await _box(db, u.id)
    t, sid = await _setting_id(db)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    result = await db.execute(sa_select(SettingProgress).where(SettingProgress.user_id == u.id))
    assert result.scalar_one_or_none() is None


async def test_record_practice_no_setting_progress_when_list_entry_has_no_setting(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    pl = await create_list(db, u.id, b.id, "Test List", PracticeListType.repertoire)
    await add_tune_to_list(db, pl.id, t.id)  # no setting_id
    await activate_list(db, u.id, pl.id)
    await record_practice(db, u.id, b.id, t.id, confidence=5)
    result = await db.execute(sa_select(SettingProgress).where(SettingProgress.user_id == u.id))
    assert result.scalar_one_or_none() is None


# ── Repertoire goal-reached (focus prompt, #241/#243) ──────────────────────────


async def test_set_status_survives_in_repertoire_list_when_goal_met_and_not_focused(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    from cairn.models import TuneListEntry

    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    pl = await create_list(
        db, u.id, b.id, "Repertoire", PracticeListType.repertoire, progress_goal=ProgressStatus.committed
    )
    await add_tune_to_list(db, pl.id, t.id)
    await activate_list(db, u.id, pl.id)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.committed)
    result = await db.execute(
        sa_select(TuneListEntry).where(TuneListEntry.list_id == pl.id, TuneListEntry.tune_id == t.id)
    )
    entry = result.scalar_one_or_none()
    assert entry is not None
    assert entry.focus_goal_reached_at is None


async def test_set_status_sets_focus_goal_reached_when_focused_and_goal_met(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    from cairn.models import TuneListEntry

    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    pl = await create_list(
        db, u.id, b.id, "Repertoire", PracticeListType.repertoire, progress_goal=ProgressStatus.committed
    )
    await add_tune_to_list(db, pl.id, t.id)
    await set_focus(db, pl.id, t.id, True)
    await activate_list(db, u.id, pl.id)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.committed)
    result = await db.execute(
        sa_select(TuneListEntry).where(TuneListEntry.list_id == pl.id, TuneListEntry.tune_id == t.id)
    )
    entry = result.scalar_one_or_none()
    assert entry is not None
    assert entry.focus_goal_reached_at is not None


async def test_set_status_does_not_rebump_focus_goal_reached_on_later_practice(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    from cairn.models import TuneListEntry

    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    pl = await create_list(
        db, u.id, b.id, "Repertoire", PracticeListType.repertoire, progress_goal=ProgressStatus.committed
    )
    await add_tune_to_list(db, pl.id, t.id)
    await set_focus(db, pl.id, t.id, True)
    await activate_list(db, u.id, pl.id)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.committed)
    result = await db.execute(
        sa_select(TuneListEntry).where(TuneListEntry.list_id == pl.id, TuneListEntry.tune_id == t.id)
    )
    first_timestamp = result.scalar_one().focus_goal_reached_at
    assert first_timestamp is not None

    await set_status(db, u.id, b.id, t.id, ProgressStatus.committed)
    result = await db.execute(
        sa_select(TuneListEntry).where(TuneListEntry.list_id == pl.id, TuneListEntry.tune_id == t.id)
    )
    assert result.scalar_one().focus_goal_reached_at == first_timestamp


async def test_set_status_does_not_remove_when_below_goal(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    from cairn.models import TuneListEntry

    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    pl = await create_list(
        db, u.id, b.id, "Repertoire", PracticeListType.repertoire, progress_goal=ProgressStatus.committed
    )
    await add_tune_to_list(db, pl.id, t.id)
    await activate_list(db, u.id, pl.id)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.nearly_there)
    result = await db.execute(
        sa_select(TuneListEntry).where(TuneListEntry.list_id == pl.id, TuneListEntry.tune_id == t.id)
    )
    assert result.scalar_one_or_none() is not None


async def test_set_status_does_not_remove_from_woodshed_list(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    from cairn.models import TuneListEntry

    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    pl = await create_list(
        db, u.id, b.id, "Woodshed", PracticeListType.woodshed, progress_goal=ProgressStatus.committed
    )
    await add_tune_to_list(db, pl.id, t.id)
    await activate_list(db, u.id, pl.id)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.committed)
    result = await db.execute(
        sa_select(TuneListEntry).where(TuneListEntry.list_id == pl.id, TuneListEntry.tune_id == t.id)
    )
    assert result.scalar_one_or_none() is not None


async def test_advance_status_one_moves_up_one_step(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.just_learning)
    result = await advance_status_one(db, u.id, b.id, t.id)
    assert result is not None
    assert result.status == ProgressStatus.getting_there


async def test_advance_status_one_does_not_exceed_top(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    await set_status(db, u.id, b.id, t.id, ProgressStatus.solo_ready)
    result = await advance_status_one(db, u.id, b.id, t.id)
    assert result is not None
    assert result.status == ProgressStatus.solo_ready


async def test_advance_status_one_returns_none_when_no_record(db: AsyncSession) -> None:
    u = await _user(db)
    b = await _box(db, u.id)
    t = await _tune(db)
    result = await advance_status_one(db, u.id, b.id, t.id)
    assert result is None
