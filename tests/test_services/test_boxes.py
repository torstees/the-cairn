import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, KeyMode, KeyRoot, Role, TuneType, User
from cairn.schemas import TuneCreate
from cairn.services.boxes import (
    add_tune,
    create_box,
    get_box,
    get_box_entry,
    get_display_names_for_tunes,
    get_transposes_for_tunes,
    list_boxes,
    remove_tune,
    set_display_alias,
    set_preferred_setting,
    set_transpose,
)
from cairn.services.tunes import add_alias, create_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|"


# ── helpers ────────────────────────────────────────────────────────────────────


async def _user(db: AsyncSession, username: str = "alice") -> User:
    u = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password="x",
        role=Role.student,
    )
    db.add(u)
    await db.flush()
    return u


async def _tune(db: AsyncSession, title: str = "The Morning Dew") -> object:
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


# ── create_box ────────────────────────────────────────────────────────────────


async def test_create_box_returns_box_with_id(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Flute Box", [Instrument.flute])
    assert box.id is not None
    assert box.name == "Flute Box"
    assert box.user_id == u.id


async def test_create_box_multi_instrument(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Wind Box", [Instrument.flute, Instrument.tin_whistle])
    assert box.id is not None


async def test_create_box_requires_at_least_one_instrument(db: AsyncSession) -> None:
    u = await _user(db)
    with pytest.raises(ValueError, match="instrument"):
        await create_box(db, u.id, "Empty Box", [])


# ── add_tune ──────────────────────────────────────────────────────────────────


async def test_add_tune_creates_entry(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    entry = await add_tune(db, box.id, t.id)
    assert entry.id is not None
    assert entry.box_id == box.id
    assert entry.tune_id == t.id


async def test_add_tune_no_setting_when_core_only(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    # Core setting has instrument=None — not a match for fiddle
    entry = await add_tune(db, box.id, t.id)
    assert entry.setting_id is None


async def test_add_tune_auto_sets_setting_when_exactly_one_match(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    from cairn.models import OrnamentationLevel, TuneSetting

    fs = TuneSetting(
        tune_id=t.id,
        label="Fiddle arrangement",
        abc_notation=_ABC,
        is_core=False,
        instrument=Instrument.fiddle,
        ornamentation_level=OrnamentationLevel.none,
    )
    db.add(fs)
    await db.commit()

    entry = await add_tune(db, box.id, t.id)
    assert entry.setting_id == fs.id


async def test_add_tune_no_setting_when_multiple_instrument_matches(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    from cairn.models import OrnamentationLevel, TuneSetting

    for label in ("Arrangement A", "Arrangement B"):
        db.add(
            TuneSetting(
                tune_id=t.id,
                label=label,
                abc_notation=_ABC,
                is_core=False,
                instrument=Instrument.fiddle,
                ornamentation_level=OrnamentationLevel.none,
            )
        )
    await db.commit()

    entry = await add_tune(db, box.id, t.id)
    assert entry.setting_id is None


# ── set_preferred_setting ─────────────────────────────────────────────────────


async def test_set_preferred_setting_updates_entry(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    entry = await add_tune(db, box.id, t.id)
    assert entry.setting_id is None

    from cairn.models import OrnamentationLevel, TuneSetting

    fs = TuneSetting(
        tune_id=t.id,
        label="Fiddle ornamented",
        abc_notation=_ABC,
        is_core=False,
        instrument=Instrument.fiddle,
        ornamentation_level=OrnamentationLevel.minimal,
    )
    db.add(fs)
    await db.commit()

    updated = await set_preferred_setting(db, box.id, t.id, fs.id)
    assert updated.setting_id == fs.id
    assert updated.id == entry.id


# ── display alias ─────────────────────────────────────────────────────────────


async def test_add_tune_stores_display_alias_id(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    alias = await add_alias(db, t.id, "Sunrise Reel")

    entry = await add_tune(db, box.id, t.id, display_alias_id=alias.id)
    assert entry.display_alias_id == alias.id


async def test_add_tune_display_alias_defaults_to_none(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)

    entry = await add_tune(db, box.id, t.id)
    assert entry.display_alias_id is None


async def test_set_display_alias_updates_entry(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    alias = await add_alias(db, t.id, "Sunrise Reel")
    entry = await add_tune(db, box.id, t.id)
    assert entry.display_alias_id is None

    updated = await set_display_alias(db, box.id, t.id, alias.id)
    assert updated.display_alias_id == alias.id
    assert updated.id == entry.id

    reloaded = await get_box_entry(db, box.id, t.id)
    assert reloaded is not None
    assert reloaded.display_alias is not None
    assert reloaded.display_alias.name == "Sunrise Reel"


async def test_set_display_alias_can_clear_back_to_title(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    alias = await add_alias(db, t.id, "Sunrise Reel")
    await add_tune(db, box.id, t.id, display_alias_id=alias.id)

    updated = await set_display_alias(db, box.id, t.id, None)
    assert updated.display_alias_id is None


async def test_get_display_names_for_tunes_only_includes_entries_with_alias_chosen(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    alias = await add_alias(db, t1.id, "Sunrise Reel")
    await add_tune(db, box.id, t1.id, display_alias_id=alias.id)
    await add_tune(db, box.id, t2.id)

    names = await get_display_names_for_tunes(db, box.id, {t1.id, t2.id})
    assert names == {t1.id: "Sunrise Reel"}


async def test_get_display_names_for_tunes_empty_tune_ids(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    assert await get_display_names_for_tunes(db, box.id, set()) == {}


# ── transpose (#158) ─────────────────────────────────────────────────────────


async def test_set_transpose_updates_entry(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    entry = await add_tune(db, box.id, t.id)
    assert entry.transpose_key_root is None
    assert entry.transpose_octave == 0

    updated = await set_transpose(db, box.id, t.id, KeyRoot.E, 1)
    assert updated.transpose_key_root == KeyRoot.E
    assert updated.transpose_octave == 1
    assert updated.id == entry.id


async def test_set_transpose_can_clear_back_to_default(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    await add_tune(db, box.id, t.id)
    await set_transpose(db, box.id, t.id, KeyRoot.E, 1)

    cleared = await set_transpose(db, box.id, t.id, None, 0)
    assert cleared.transpose_key_root is None
    assert cleared.transpose_octave == 0


async def test_get_transposes_for_tunes_only_includes_entries_with_transpose_set(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    await add_tune(db, box.id, t1.id)
    await add_tune(db, box.id, t2.id)
    await set_transpose(db, box.id, t1.id, KeyRoot.E, 0)

    transposes = await get_transposes_for_tunes(db, box.id, {t1.id, t2.id})
    assert transposes == {t1.id: (KeyRoot.E, 0)}


async def test_get_transposes_for_tunes_octave_only_counts_as_set(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    await add_tune(db, box.id, t.id)
    await set_transpose(db, box.id, t.id, None, 1)

    transposes = await get_transposes_for_tunes(db, box.id, {t.id})
    assert transposes == {t.id: (None, 1)}


async def test_get_transposes_for_tunes_empty_tune_ids(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    assert await get_transposes_for_tunes(db, box.id, set()) == {}


async def test_get_transposes_for_tunes_list_overrides_box(db: AsyncSession) -> None:
    from cairn.models import PracticeListType
    from cairn.services.lists import add_tune_to_list, create_list, update_list_entry_transpose

    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    await add_tune(db, box.id, t.id)
    await set_transpose(db, box.id, t.id, KeyRoot.E, 0)

    practice_list = await create_list(db, u.id, box.id, "Session List", PracticeListType.repertoire)
    await add_tune_to_list(db, practice_list.id, t.id)
    await update_list_entry_transpose(db, practice_list.id, t.id, KeyRoot.G, 1)

    transposes = await get_transposes_for_tunes(db, box.id, {t.id}, list_id=practice_list.id)
    assert transposes == {t.id: (KeyRoot.G, 1)}


async def test_get_transposes_for_tunes_list_entry_without_transpose_leaves_box_value(db: AsyncSession) -> None:
    from cairn.models import PracticeListType
    from cairn.services.lists import add_tune_to_list, create_list

    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    await add_tune(db, box.id, t.id)
    await set_transpose(db, box.id, t.id, KeyRoot.E, 0)

    practice_list = await create_list(db, u.id, box.id, "Session List", PracticeListType.repertoire)
    await add_tune_to_list(db, practice_list.id, t.id)

    transposes = await get_transposes_for_tunes(db, box.id, {t.id}, list_id=practice_list.id)
    assert transposes == {t.id: (KeyRoot.E, 0)}


# ── remove_tune ───────────────────────────────────────────────────────────────


async def test_remove_tune_returns_true_and_deletes_entry(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)
    await add_tune(db, box.id, t.id)

    result = await remove_tune(db, box.id, t.id)
    assert result is True

    # Confirm gone
    from sqlalchemy import select

    from cairn.models import TuneBoxEntry

    count_result = await db.execute(
        select(TuneBoxEntry).where(
            TuneBoxEntry.box_id == box.id,
            TuneBoxEntry.tune_id == t.id,
        )
    )
    assert count_result.scalar_one_or_none() is None


async def test_remove_tune_returns_false_when_not_in_box(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, u.id, "Fiddle Box", [Instrument.fiddle])
    t = await _tune(db)

    result = await remove_tune(db, box.id, t.id)
    assert result is False


# ── list_boxes ────────────────────────────────────────────────────────────────


async def test_list_boxes_returns_boxes_for_user(db: AsyncSession) -> None:
    u = await _user(db)
    await create_box(db, u.id, "Banjo Box", [Instrument.banjo])
    await create_box(db, u.id, "Flute Box", [Instrument.flute])

    boxes = await list_boxes(db, u.id)
    assert len(boxes) == 2


async def test_list_boxes_ordered_by_name(db: AsyncSession) -> None:
    u = await _user(db)
    await create_box(db, u.id, "Zither Box", [Instrument.fiddle])
    await create_box(db, u.id, "Accordion Box", [Instrument.accordion])

    boxes = await list_boxes(db, u.id)
    assert boxes[0].name == "Accordion Box"
    assert boxes[1].name == "Zither Box"


async def test_list_boxes_excludes_other_users_boxes(db: AsyncSession) -> None:
    u1 = await _user(db, "alice")
    u2 = await _user(db, "bob")
    await create_box(db, u1.id, "Alice Box", [Instrument.fiddle])
    await create_box(db, u2.id, "Bob Box", [Instrument.flute])

    boxes = await list_boxes(db, u1.id)
    assert len(boxes) == 1
    assert boxes[0].name == "Alice Box"


async def test_list_boxes_empty_for_new_user(db: AsyncSession) -> None:
    u = await _user(db)
    boxes = await list_boxes(db, u.id)
    assert boxes == []


# ── get_box ───────────────────────────────────────────────────────────────────


async def test_get_box_returns_box(db: AsyncSession) -> None:
    u = await _user(db)
    created = await create_box(db, u.id, "Concertina Box", [Instrument.concertina])
    found = await get_box(db, created.id)
    assert found is not None
    assert found.id == created.id
    assert found.name == "Concertina Box"


async def test_get_box_returns_none_for_unknown_id(db: AsyncSession) -> None:
    found = await get_box(db, 9999)
    assert found is None
