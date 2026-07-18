import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_current_user, get_db
from cairn.models import Instrument, InstrumentTuning, User
from cairn.services.tunings import (
    FRETTED_INSTRUMENTS,
    PRESET_TUNINGS_JSON,
    create_tuning,
    delete_tuning,
    list_tunings,
    tunings_to_json,
)
from cairn.templating import templates

router = APIRouter(prefix="/tunings", tags=["tunings"])

# A single ABC pitch: a note letter plus any number of octave markers (comma
# down, apostrophe up) — e.g. "D,", "e", "F#" (accidentals aren't strictly
# ABC-pitch syntax here, but are harmless to allow through for a tuning label).
_PITCH_RE = re.compile(r"^[A-Ga-g][,'#b]*$")


def _ctx(tunings: list[InstrumentTuning], error: str | None = None) -> dict:
    return {
        "tunings": tunings,
        "tunings_json": tunings_to_json(tunings),
        "fretted_instruments": sorted(FRETTED_INSTRUMENTS, key=lambda i: i.label),
        "presets_json": PRESET_TUNINGS_JSON,
        "error": error,
    }


async def _manage_ctx(db: AsyncSession, user: User, error: str | None = None) -> dict:
    return _ctx(await list_tunings(db, user.id), error=error)


@router.post("")
async def tuning_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    instrument: str = Form(...),
    name: str = Form(...),
    strings_raw: str = Form(...),
) -> Response:
    try:
        instrument_enum = Instrument(instrument)
    except ValueError:
        instrument_enum = None

    tokens = strings_raw.split()
    valid = (
        instrument_enum in FRETTED_INSTRUMENTS
        and bool(name.strip())
        and bool(tokens)
        and all(_PITCH_RE.match(t) for t in tokens)
    )
    if not valid:
        return templates.TemplateResponse(
            request,
            "tunings/_manage.html",
            await _manage_ctx(db, user, error="Enter a name and a space-separated tuning (e.g. D, A, D G A d)."),
        )

    # Checked up front (rather than relying on the DB's unique constraint and
    # catching IntegrityError) so a rejected duplicate can still re-render
    # this same partial with the existing list — recovering an AsyncSession
    # after a failed flush/commit to immediately query it again is exactly
    # the class of MissingGreenlet trap this codebase has hit before.
    existing = await list_tunings(db, user.id)
    stripped_name = name.strip()
    if any(t.instrument == instrument_enum and t.name == stripped_name for t in existing):
        error = f'You already have a "{stripped_name}" tuning for {instrument_enum.label}.'
        return templates.TemplateResponse(request, "tunings/_manage.html", _ctx(existing, error=error))

    await create_tuning(db, user.id, instrument_enum, name, tokens)
    return templates.TemplateResponse(request, "tunings/_manage.html", await _manage_ctx(db, user))


@router.delete("/{tuning_id}")
async def tuning_delete(
    tuning_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    if not await delete_tuning(db, tuning_id, user.id):
        raise HTTPException(status_code=404, detail="Tuning not found")
    return templates.TemplateResponse(request, "tunings/_manage.html", await _manage_ctx(db, user))
