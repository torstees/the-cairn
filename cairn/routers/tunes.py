from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, TuneType
from cairn.schemas import TuneCreate, TuneUpdate
from cairn.services.abc_utils import build_abc
from cairn.services.tunes import create_tune, delete_tune, get_tune, list_tunes, update_tune
from cairn.templating import templates

router = APIRouter(prefix="/tunes", tags=["tunes"])

_TUNE_TYPES = list(TuneType)
_KEY_ROOTS = list(KeyRoot)
_KEY_MODES = list(KeyMode)
_INSTRUMENTS = list(Instrument)
_ORN_LEVELS = list(OrnamentationLevel)

_FORM_CTX = {"tune_types": _TUNE_TYPES, "key_roots": _KEY_ROOTS, "key_modes": _KEY_MODES}
_SETTINGS_CTX = {"instruments": _INSTRUMENTS, "orn_levels": _ORN_LEVELS}


@router.get("/new")
async def tune_new(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "tunes/form.html",
        {"tune": None, "core_abc": "", **_FORM_CTX},
    )


@router.get("/")
async def tune_list(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    tunes = await list_tunes(db)
    return templates.TemplateResponse(request, "tunes/index.html", {"tunes": tunes})


@router.post("/")
async def tune_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    tune_type: TuneType = Form(...),
    key_root: KeyRoot = Form(...),
    key_mode: KeyMode = Form(...),
    time_signature: str = Form(...),
    abc_notation: str = Form(...),
    origin: str | None = Form(None),
    region: str | None = Form(None),
    notes: str | None = Form(None),
) -> Response:
    tune_in = TuneCreate(
        title=title,
        tune_type=tune_type,
        key_root=key_root,
        key_mode=key_mode,
        time_signature=time_signature,
        origin=origin or None,
        region=region or None,
        notes=notes or None,
    )
    tune = await create_tune(db, tune_in, abc_notation=abc_notation)
    return RedirectResponse(f"/tunes/{tune.id}", status_code=303)


@router.get("/{tune_id}")
async def tune_detail(request: Request, tune_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    core = next((s for s in tune.settings if s.is_core and s.instrument is None), None)
    built_abc = build_abc(tune, core) if core else ""
    settings_abc = {s.id: build_abc(tune, s) for s in tune.settings}
    return templates.TemplateResponse(
        request, "tunes/detail.html",
        {"tune": tune, "built_abc": built_abc, "settings_abc": settings_abc, **_SETTINGS_CTX},
    )


@router.get("/{tune_id}/edit")
async def tune_edit(request: Request, tune_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    core = next((s for s in tune.settings if s.is_core and s.instrument is None), None)
    core_abc = core.abc_notation if core else ""
    return templates.TemplateResponse(
        request,
        "tunes/form.html",
        {"tune": tune, "core_abc": core_abc, **_FORM_CTX},
    )


@router.post("/{tune_id}")
async def tune_update(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    tune_type: TuneType = Form(...),
    key_root: KeyRoot = Form(...),
    key_mode: KeyMode = Form(...),
    time_signature: str = Form(...),
    abc_notation: str | None = Form(None),
    origin: str | None = Form(None),
    region: str | None = Form(None),
    notes: str | None = Form(None),
) -> Response:
    tune_in = TuneUpdate(
        title=title,
        tune_type=tune_type,
        key_root=key_root,
        key_mode=key_mode,
        time_signature=time_signature,
        origin=origin or None,
        region=region or None,
        notes=notes or None,
    )
    tune = await update_tune(db, tune_id, tune_in, abc_notation=abc_notation or None)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    return RedirectResponse(f"/tunes/{tune.id}", status_code=303)


@router.delete("/{tune_id}")
async def tune_delete(tune_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    deleted = await delete_tune(db, tune_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tune not found")
    return Response(status_code=200)
