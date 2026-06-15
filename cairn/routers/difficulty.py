from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import Instrument
from cairn.schemas import TuneDifficultyCreate
from cairn.services.tunes import get_tune, set_difficulty
from cairn.templating import templates

router = APIRouter(prefix="/tunes", tags=["difficulty"])

_INSTRUMENTS = list(Instrument)


def _ctx(tune):
    return {"tune": tune, "instruments": _INSTRUMENTS}


@router.get("/{tune_id}/difficulty")
async def difficulty_show(
    request: Request, tune_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    return templates.TemplateResponse(request, "tunes/partials/_difficulty.html", _ctx(tune))


@router.post("/{tune_id}/difficulty")
async def difficulty_set(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    instrument: Instrument = Form(...),
    difficulty: int = Form(...),
    notes: str = Form(""),
) -> Response:
    difficulty_in = TuneDifficultyCreate(
        tune_id=tune_id,
        instrument=instrument,
        difficulty=difficulty,
        notes=notes or None,
    )
    result = await set_difficulty(db, tune_id, difficulty_in)
    if result is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    tune = await get_tune(db, tune_id)
    return templates.TemplateResponse(request, "tunes/partials/_difficulty.html", _ctx(tune))
