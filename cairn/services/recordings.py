import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import Recording, RecordingReference
from cairn.models_thesession_community import TheSessionRecording


async def create_recording(db: AsyncSession, artist: str, title: str, links: dict | None = None) -> Recording:
    recording = Recording(artist=artist, title=title, links=links or None)
    db.add(recording)
    await db.commit()
    await db.refresh(recording)
    return recording


async def list_recordings(db: AsyncSession) -> list[Recording]:
    result = await db.execute(select(Recording).order_by(Recording.artist, Recording.title))
    return list(result.scalars().all())


def recordings_to_json(recordings: list[Recording]) -> str:
    """Serialize for window.__cairnRecordings — the client-side "pick an
    existing recording" search box on recordings/_manage.html."""
    return json.dumps(
        [{"id": r.id, "artist": r.artist, "title": r.title, "label": f"{r.artist} — {r.title}"} for r in recordings]
    )


# A well-known session tune can have hundreds of TheSessionRecording rows
# (one per track it appears on across many albums). The client-side search
# box filters the full list by artist/title, so this is a defensive sanity
# cap only (guards against a truly pathological case), not a UX-visibility
# cap -- the real-world max seen so far is ~281 rows for one very popular reel.
_MAX_THESESSION_SUGGESTIONS = 500


async def thesession_suggestions_json(db: AsyncSession, thesession_tune_id: int | None) -> str:
    """JSON blob of TheSession-sourced recording suggestions (TODO 9.2) to
    pre-fill the "add new recording" form — a pre-fill, not an auto-import.
    Empty if the tune isn't linked to TheSession.org, or has none. Ordered
    by artist so the (usually short, occasionally very long) list is at
    least browsable/searchable in a sensible order rather than arbitrary
    insertion order.

    recordings.csv's `artist` column holds the artist's actual name in the
    near-universal case (verified during #185/8.4's import), but a small
    legacy fraction still holds a bare numeric id never backfilled with a
    name — left blank for the user to fill in rather than suggesting a
    meaningless number.
    """
    if thesession_tune_id is None:
        return "[]"
    result = await db.execute(
        select(TheSessionRecording)
        .where(TheSessionRecording.tune_id == thesession_tune_id)
        .order_by(TheSessionRecording.artist, TheSessionRecording.track_number)
        .limit(_MAX_THESESSION_SUGGESTIONS)
    )
    suggestions = result.scalars().all()
    items = []
    for r in suggestions:
        artist_display = "" if r.artist.strip().isdigit() else r.artist
        tooltip = (
            f"{artist_display or 'Unknown artist'} — {r.recording_name}\n"
            f"Track {r.track_number}, position {r.position}\n"
            f'Listed on TheSession.org as "{r.tune_name}"'
        )
        items.append(
            {
                "artist": artist_display,
                "title": r.recording_name,
                "track_number": r.track_number,
                "position": r.position,
                "label": f"{r.recording_name} (track {r.track_number})",
                "tooltip": tooltip,
            }
        )
    return json.dumps(items)


async def add_reference(
    db: AsyncSession,
    recording_id: int,
    *,
    setting_id: int | None = None,
    set_id: int | None = None,
    track_number: int | None = None,
    position: int | None = None,
) -> RecordingReference:
    """Link a Recording to one TuneSetting or one TuneSet — exactly one of
    setting_id/set_id must be given."""
    if (setting_id is None) == (set_id is None):
        raise ValueError("Exactly one of setting_id/set_id must be set")
    reference = RecordingReference(
        recording_id=recording_id,
        setting_id=setting_id,
        set_id=set_id,
        track_number=track_number,
        position=position,
    )
    db.add(reference)
    await db.commit()
    await db.refresh(reference)
    return reference


async def update_recording(
    db: AsyncSession, recording_id: int, artist: str, title: str, links: dict | None = None
) -> Recording | None:
    """Edit a Recording's own facts — applies everywhere it's referenced,
    since it's entered once and shared across every tune/set it's tagged on."""
    recording = await db.get(Recording, recording_id)
    if recording is None:
        return None
    recording.artist = artist
    recording.title = title
    recording.links = links or None
    await db.commit()
    await db.refresh(recording)
    return recording


async def update_reference(
    db: AsyncSession,
    reference_id: int,
    *,
    setting_id: int | None = None,
    track_number: int | None = None,
    position: int | None = None,
) -> RecordingReference | None:
    """Edit a reference's own fields — track_number/position always, and
    setting_id only for a setting-scoped reference (re-pointing it at a
    different setting of the same tune; never changes set_id/setting_id's
    presence, just which one)."""
    reference = await db.get(RecordingReference, reference_id)
    if reference is None:
        return None
    if reference.setting_id is not None and setting_id is not None:
        reference.setting_id = setting_id
    reference.track_number = track_number
    reference.position = position
    await db.commit()
    await db.refresh(reference)
    return reference


async def list_recordings_for_setting(db: AsyncSession, setting_id: int) -> list[RecordingReference]:
    result = await db.execute(
        select(RecordingReference)
        .where(RecordingReference.setting_id == setting_id)
        .options(selectinload(RecordingReference.recording))
    )
    return list(result.scalars().all())


async def list_recordings_for_tune(db: AsyncSession, setting_ids: list[int]) -> list[RecordingReference]:
    """Every RecordingReference across any of a tune's settings — tune_detail
    shows one combined Recordings section, not one per setting card."""
    if not setting_ids:
        return []
    result = await db.execute(
        select(RecordingReference)
        .where(RecordingReference.setting_id.in_(setting_ids))
        .options(selectinload(RecordingReference.recording), selectinload(RecordingReference.setting))
    )
    return list(result.scalars().all())


async def list_recordings_for_set(db: AsyncSession, set_id: int) -> list[RecordingReference]:
    result = await db.execute(
        select(RecordingReference)
        .where(RecordingReference.set_id == set_id)
        .options(selectinload(RecordingReference.recording))
    )
    return list(result.scalars().all())


async def remove_reference(db: AsyncSession, reference_id: int) -> bool:
    reference = await db.get(RecordingReference, reference_id)
    if reference is None:
        return False
    await db.delete(reference)
    await db.commit()
    return True
