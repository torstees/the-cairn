from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import Instrument, OrnamentationLevel
from cairn.schemas import TuneSettingCreate, TuneSettingUpdate
from cairn.services.abc_utils import build_abc
from cairn.services.tunes import create_setting, get_tune, set_core_setting, update_setting
from cairn.templating import templates

router = APIRouter(prefix="/tunes", tags=["settings"])

_INSTRUMENTS = list(Instrument)
_ORN_LEVELS = list(OrnamentationLevel)

_SETTINGS_CTX = {"instruments": _INSTRUMENTS, "orn_levels": _ORN_LEVELS}


def _settings_ctx(tune):
    core = next((s for s in tune.settings if s.is_core and s.instrument is None), None)
    settings_abc = {s.id: build_abc(tune, s) for s in tune.settings}
    return {
        "tune": tune,
        "built_abc": build_abc(tune, core) if core else "",
        "settings_abc": settings_abc,
        **_SETTINGS_CTX,
    }


@router.get("/{tune_id}/settings/new")
async def setting_new(
    request: Request, tune_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    return templates.TemplateResponse(
        request, "tunes/partials/_settings.html", _settings_ctx(tune)
    )


@router.post("/{tune_id}/settings")
async def setting_create(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    label: str = Form(...),
    abc_notation: str = Form(...),
    instrument: str = Form(""),
    ornamentation_level: OrnamentationLevel = Form(OrnamentationLevel.none),
    source: str = Form(""),
) -> Response:
    setting_in = TuneSettingCreate(
        tune_id=tune_id,
        label=label,
        abc_notation=abc_notation,
        instrument=Instrument(instrument) if instrument else None,
        ornamentation_level=ornamentation_level,
        source=source or None,
    )
    result = await create_setting(db, tune_id, setting_in)
    if result is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    tune = await get_tune(db, tune_id)
    return templates.TemplateResponse(
        request, "tunes/partials/_settings.html", _settings_ctx(tune)
    )


@router.post("/{tune_id}/settings/{setting_id}")
async def setting_update(
    request: Request,
    tune_id: int,
    setting_id: int,
    db: AsyncSession = Depends(get_db),
    label: str = Form(...),
    abc_notation: str = Form(...),
    instrument: str = Form(""),
    ornamentation_level: OrnamentationLevel = Form(OrnamentationLevel.none),
    source: str = Form(""),
    source_notes: str = Form(""),
) -> Response:
    setting_in = TuneSettingUpdate(
        label=label,
        abc_notation=abc_notation,
        instrument=Instrument(instrument) if instrument else None,
        ornamentation_level=ornamentation_level,
        source=source or None,
        source_notes=source_notes or None,
    )
    result = await update_setting(db, tune_id, setting_id, setting_in)
    if result is None:
        raise HTTPException(status_code=404, detail="Setting not found")
    tune = await get_tune(db, tune_id)
    return templates.TemplateResponse(
        request, "tunes/partials/_settings.html", _settings_ctx(tune)
    )


@router.post("/{tune_id}/settings/{setting_id}/set-core")
async def setting_set_core(
    request: Request,
    tune_id: int,
    setting_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await set_core_setting(db, tune_id, setting_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Setting not found")
    tune = await get_tune(db, tune_id)
    return templates.TemplateResponse(
        request, "tunes/partials/_settings.html", _settings_ctx(tune)
    )
