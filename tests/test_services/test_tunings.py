import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, Role, User
from cairn.services.tunings import create_tuning, delete_tuning, list_tunings


async def _user(db: AsyncSession, username: str = "alice") -> User:
    u = User(username=username, email=f"{username}@example.com", google_sub=f"google-sub-{username}", role=Role.student)
    db.add(u)
    await db.flush()
    return u


async def test_create_tuning(db: AsyncSession) -> None:
    user = await _user(db)
    tuning = await create_tuning(db, user.id, Instrument.guitar, "DADGAD", ["D,", "A,", "D", "G", "A", "d"])
    assert tuning.user_id == user.id
    assert tuning.instrument == Instrument.guitar
    assert tuning.name == "DADGAD"
    assert tuning.strings == ["D,", "A,", "D", "G", "A", "d"]


async def test_list_tunings_scoped_to_user(db: AsyncSession) -> None:
    user = await _user(db, "alice")
    other = await _user(db, "bob")
    await create_tuning(db, user.id, Instrument.guitar, "DADGAD", ["D,", "A,", "D", "G", "A", "d"])
    await create_tuning(db, other.id, Instrument.guitar, "Drop D", ["D,", "A,", "D", "G", "B", "e"])

    result = await list_tunings(db, user.id)
    assert len(result) == 1
    assert result[0].name == "DADGAD"


async def test_list_tunings_ordered_by_instrument_then_name(db: AsyncSession) -> None:
    user = await _user(db)
    await create_tuning(db, user.id, Instrument.mandolin, "Standard", ["G,", "D", "A", "e"])
    await create_tuning(db, user.id, Instrument.guitar, "DADGAD", ["D,", "A,", "D", "G", "A", "d"])
    await create_tuning(db, user.id, Instrument.guitar, "Drop D", ["D,", "A,", "D", "G", "B", "e"])

    result = await list_tunings(db, user.id)
    assert [(t.instrument, t.name) for t in result] == [
        (Instrument.guitar, "DADGAD"),
        (Instrument.guitar, "Drop D"),
        (Instrument.mandolin, "Standard"),
    ]


async def test_create_tuning_duplicate_name_raises_integrity_error(db: AsyncSession) -> None:
    user = await _user(db)
    await create_tuning(db, user.id, Instrument.guitar, "DADGAD", ["D,", "A,", "D", "G", "A", "d"])
    with pytest.raises(IntegrityError):
        await create_tuning(db, user.id, Instrument.guitar, "DADGAD", ["D,", "A,", "D", "G", "A", "d"])


async def test_delete_tuning_by_owner(db: AsyncSession) -> None:
    user = await _user(db)
    tuning = await create_tuning(db, user.id, Instrument.guitar, "DADGAD", ["D,", "A,", "D", "G", "A", "d"])
    assert await delete_tuning(db, tuning.id, user.id) is True
    assert await list_tunings(db, user.id) == []


async def test_delete_tuning_by_non_owner_returns_false(db: AsyncSession) -> None:
    user = await _user(db, "alice")
    other = await _user(db, "bob")
    tuning = await create_tuning(db, user.id, Instrument.guitar, "DADGAD", ["D,", "A,", "D", "G", "A", "d"])
    assert await delete_tuning(db, tuning.id, other.id) is False
    assert len(await list_tunings(db, user.id)) == 1


async def test_delete_tuning_unknown_id_returns_false(db: AsyncSession) -> None:
    user = await _user(db)
    assert await delete_tuning(db, 9999, user.id) is False
