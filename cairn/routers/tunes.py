from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, TuneType
from cairn.schemas import TuneCreate, TuneUpdate
from cairn.services.abc_utils import build_abc
from cairn.services.boxes import get_box, get_box_entry
from cairn.services.tunes import (
    FAMILY_LABELS,
    add_alias,
    create_tune,
    delete_tune,
    get_tune,
    list_tunes,
    remove_alias,
    update_tune,
)
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
async def tune_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tune_type: TuneType | None = Query(default=None, alias="type"),
    family: str | None = None,
) -> Response:
    tunes = await list_tunes(db, tune_type=tune_type, family=family)
    ctx = {
        "tunes": tunes,
        "tune_types": _TUNE_TYPES,
        "family_labels": FAMILY_LABELS,
        "active_type": tune_type,
        "active_family": family,
    }
    template = "tunes/partials/_tune_list.html" if request.headers.get("HX-Request") else "tunes/index.html"
    return templates.TemplateResponse(request, template, ctx)


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
async def tune_detail(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    box_id: int | None = Query(default=None),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")

    active_setting = None
    box = None
    if box_id is not None:
        box, entry = await get_box(db, box_id), await get_box_entry(db, box_id, tune_id)
        if entry and entry.setting_id is not None:
            active_setting = entry.setting

    if active_setting is None:
        active_setting = next((s for s in tune.settings if s.is_core and s.instrument is None), None)

    built_abc = build_abc(tune, active_setting) if active_setting else ""
    settings_abc = {s.id: build_abc(tune, s) for s in tune.settings}
    return templates.TemplateResponse(
        request,
        "tunes/detail.html",
        {
            "tune": tune,
            "built_abc": built_abc,
            "settings_abc": settings_abc,
            "active_setting_id": active_setting.id if active_setting else None,
            "box": box,
            "box_id": box_id,
            **_SETTINGS_CTX,
        },
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


@router.post("/{tune_id}/aliases")
async def alias_add(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    notes: str = Form(default=""),
) -> Response:
    alias = await add_alias(db, tune_id, name, notes or None)
    if alias is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    tune = await get_tune(db, tune_id)
    return templates.TemplateResponse(request, "tunes/partials/_aliases.html", {"tune": tune})


@router.delete("/{tune_id}/aliases/{alias_id}")
async def alias_remove(
    request: Request,
    tune_id: int,
    alias_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    removed = await remove_alias(db, alias_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Alias not found")
    tune = await get_tune(db, tune_id)
    return templates.TemplateResponse(request, "tunes/partials/_aliases.html", {"tune": tune})
