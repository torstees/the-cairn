from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_current_user, get_db
from cairn.models import Recording, RecordingReference, TuneSetting, User
from cairn.services.recordings import (
    add_reference,
    create_recording,
    list_recordings,
    list_recordings_for_set,
    list_recordings_for_tune,
    recordings_to_json,
    remove_reference,
    update_recording,
    update_reference,
)
from cairn.services.tune_sets import get_set
from cairn.services.tunes import get_tune
from cairn.templating import templates

router = APIRouter(prefix="/recordings", tags=["recordings"])


async def _tune_recordings_ctx(db: AsyncSession, tune) -> dict:
    setting_ids = [s.id for s in tune.settings]
    return {
        "owner_kind": "tune",
        "tune": tune,
        "references": await list_recordings_for_tune(db, setting_ids),
        "recordings_json": recordings_to_json(await list_recordings(db)),
    }


async def _set_recordings_ctx(db: AsyncSession, tune_set) -> dict:
    return {
        "owner_kind": "set",
        "tune_set": tune_set,
        "references": await list_recordings_for_set(db, tune_set.id),
        "recordings_json": recordings_to_json(await list_recordings(db)),
    }


async def _resolve_recording(
    db: AsyncSession, recording_id_raw: str, artist: str, title: str, links: dict
) -> Recording | None:
    """Either look up the picked existing Recording, or create a new one
    from artist+title — returns None if neither was validly given."""
    if recording_id_raw.strip():
        try:
            recording_id = int(recording_id_raw)
        except ValueError:
            return None
        return await db.get(Recording, recording_id)
    artist, title = artist.strip(), title.strip()
    if not artist or not title:
        return None
    return await create_recording(db, artist, title, links or None)


def _parse_int(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _links_from_form(link_youtube: str, link_spotify: str, link_bandcamp: str) -> dict:
    links = {}
    if link_youtube.strip():
        links["youtube"] = link_youtube.strip()
    if link_spotify.strip():
        links["spotify"] = link_spotify.strip()
    if link_bandcamp.strip():
        links["bandcamp"] = link_bandcamp.strip()
    return links


@router.post("/tunes/{tune_id}")
async def recording_create_for_tune(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    setting_id: str = Form(default=""),
    recording_id: str = Form(default=""),
    artist: str = Form(default=""),
    title: str = Form(default=""),
    track_number: str = Form(default=""),
    position: str = Form(default=""),
    link_youtube: str = Form(default=""),
    link_spotify: str = Form(default=""),
    link_bandcamp: str = Form(default=""),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")

    setting_id_int = _parse_int(setting_id)
    valid_setting_ids = {s.id for s in tune.settings}
    if setting_id_int is None or setting_id_int not in valid_setting_ids:
        ctx = await _tune_recordings_ctx(db, tune)
        ctx["error"] = "Pick which setting this recording is for."
        return templates.TemplateResponse(request, "recordings/_manage.html", ctx)

    recording = await _resolve_recording(
        db, recording_id, artist, title, _links_from_form(link_youtube, link_spotify, link_bandcamp)
    )
    if recording is None:
        ctx = await _tune_recordings_ctx(db, tune)
        ctx["error"] = "Pick an existing recording, or enter both an artist and a title."
        return templates.TemplateResponse(request, "recordings/_manage.html", ctx)

    await add_reference(
        db,
        recording.id,
        setting_id=setting_id_int,
        track_number=_parse_int(track_number),
        position=_parse_int(position),
    )
    return templates.TemplateResponse(request, "recordings/_manage.html", await _tune_recordings_ctx(db, tune))


@router.post("/sets/{set_id}")
async def recording_create_for_set(
    request: Request,
    set_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    recording_id: str = Form(default=""),
    artist: str = Form(default=""),
    title: str = Form(default=""),
    track_number: str = Form(default=""),
    position: str = Form(default=""),
    link_youtube: str = Form(default=""),
    link_spotify: str = Form(default=""),
    link_bandcamp: str = Form(default=""),
) -> Response:
    tune_set = await get_set(db, set_id)
    if tune_set is None:
        raise HTTPException(status_code=404, detail="Set not found")

    recording = await _resolve_recording(
        db, recording_id, artist, title, _links_from_form(link_youtube, link_spotify, link_bandcamp)
    )
    if recording is None:
        ctx = await _set_recordings_ctx(db, tune_set)
        ctx["error"] = "Pick an existing recording, or enter both an artist and a title."
        return templates.TemplateResponse(request, "recordings/_manage.html", ctx)

    await add_reference(
        db,
        recording.id,
        set_id=set_id,
        track_number=_parse_int(track_number),
        position=_parse_int(position),
    )
    return templates.TemplateResponse(request, "recordings/_manage.html", await _set_recordings_ctx(db, tune_set))


@router.post("/references/{reference_id}")
async def recording_reference_update(
    reference_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    setting_id: str = Form(default=""),
    artist: str = Form(default=""),
    title: str = Form(default=""),
    track_number: str = Form(default=""),
    position: str = Form(default=""),
    link_youtube: str = Form(default=""),
    link_spotify: str = Form(default=""),
    link_bandcamp: str = Form(default=""),
) -> Response:
    """Edit a reference in place: the underlying Recording's artist/title/
    links (shared everywhere it's tagged), plus this one reference's
    setting (if setting-scoped — re-pointing it at a different setting of
    the same tune) and track_number/position."""
    reference = await db.get(RecordingReference, reference_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="Recording reference not found")

    artist, title = artist.strip(), title.strip()
    if artist and title:
        await update_recording(
            db, reference.recording_id, artist, title, _links_from_form(link_youtube, link_spotify, link_bandcamp)
        )

    setting_id_int = _parse_int(setting_id)
    await update_reference(
        db,
        reference_id,
        setting_id=setting_id_int,
        track_number=_parse_int(track_number),
        position=_parse_int(position),
    )

    if reference.setting_id is not None:
        setting = await db.get(TuneSetting, reference.setting_id)
        tune = await get_tune(db, setting.tune_id) if setting else None
        if tune is None:
            raise HTTPException(status_code=404, detail="Tune not found")
        return templates.TemplateResponse(request, "recordings/_manage.html", await _tune_recordings_ctx(db, tune))

    tune_set = await get_set(db, reference.set_id)
    if tune_set is None:
        raise HTTPException(status_code=404, detail="Set not found")
    return templates.TemplateResponse(request, "recordings/_manage.html", await _set_recordings_ctx(db, tune_set))


@router.delete("/references/{reference_id}")
async def recording_reference_delete(
    reference_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    reference = await db.get(RecordingReference, reference_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="Recording reference not found")

    if reference.setting_id is not None:
        setting = await db.get(TuneSetting, reference.setting_id)
        tune = await get_tune(db, setting.tune_id) if setting else None
        await remove_reference(db, reference_id)
        if tune is None:
            raise HTTPException(status_code=404, detail="Tune not found")
        return templates.TemplateResponse(request, "recordings/_manage.html", await _tune_recordings_ctx(db, tune))

    tune_set = await get_set(db, reference.set_id)
    await remove_reference(db, reference_id)
    if tune_set is None:
        raise HTTPException(status_code=404, detail="Set not found")
    return templates.TemplateResponse(request, "recordings/_manage.html", await _set_recordings_ctx(db, tune_set))
