from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, Role, User
from cairn.services.tunings import create_tuning


async def test_tuning_create_shows_in_partial(client: AsyncClient) -> None:
    resp = await client.post(
        "/tunings",
        data={"instrument": Instrument.guitar.value, "name": "DADGAD", "strings_raw": "D, A, D G A d"},
    )
    assert resp.status_code == 200
    assert "DADGAD" in resp.text
    assert "D, A, D G A d" in resp.text


async def test_tuning_create_rejects_invalid_pitch_tokens(client: AsyncClient) -> None:
    resp = await client.post(
        "/tunings",
        data={"instrument": Instrument.guitar.value, "name": "Bad", "strings_raw": "D, X, D G A d"},
    )
    assert resp.status_code == 200
    assert "Enter a name and a space-separated tuning" in resp.text
    assert "Bad" not in resp.text


async def test_tuning_create_rejects_non_fretted_instrument(client: AsyncClient) -> None:
    resp = await client.post(
        "/tunings",
        data={"instrument": Instrument.fiddle.value, "name": "Standard", "strings_raw": "G, D A e"},
    )
    assert resp.status_code == 200
    assert "Enter a name and a space-separated tuning" in resp.text


async def test_tuning_create_duplicate_name_shows_inline_error(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    await create_tuning(db, user.id, Instrument.guitar, "DADGAD", ["D,", "A,", "D", "G", "A", "d"])
    resp = await client.post(
        "/tunings",
        data={"instrument": Instrument.guitar.value, "name": "DADGAD", "strings_raw": "D, A, D G A d"},
    )
    assert resp.status_code == 200
    assert "already have a" in resp.text


async def test_tuning_delete(client: AsyncClient, db: AsyncSession, user: User) -> None:
    tuning = await create_tuning(db, user.id, Instrument.guitar, "DADGAD", ["D,", "A,", "D", "G", "A", "d"])
    resp = await client.delete(f"/tunings/{tuning.id}")
    assert resp.status_code == 200
    # "DADGAD" still legitimately appears in the add-form's placeholder text,
    # so check for the emptied list message rather than the name's absence.
    assert "No saved tunings yet" in resp.text


async def test_tuning_delete_404_for_another_users_tuning(client: AsyncClient, db: AsyncSession) -> None:
    other = User(username="other", email="other@example.com", google_sub="google-sub-other", role=Role.student)
    db.add(other)
    await db.flush()
    tuning = await create_tuning(db, other.id, Instrument.guitar, "DADGAD", ["D,", "A,", "D", "G", "A", "d"])
    resp = await client.delete(f"/tunings/{tuning.id}")
    assert resp.status_code == 404


async def test_unauthenticated_create_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.post(
        "/tunings",
        data={"instrument": Instrument.guitar.value, "name": "DADGAD", "strings_raw": "D, A, D G A d"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("/auth/login")


async def test_unauthenticated_delete_redirects_to_login(unauthenticated_client: AsyncClient) -> None:
    resp = await unauthenticated_client.delete("/tunings/1", follow_redirects=False)
    assert resp.status_code == 307
