from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, Tune, TuneType
from cairn.schemas import TuneCreate, TuneUpdate
from cairn.services.abc_utils import build_abc
from cairn.services.boxes import add_tune, get_box, get_box_entry, list_boxes, set_preferred_setting
from cairn.services.lists import add_tune_to_list, get_active_list, get_list, get_list_entry, list_lists
from cairn.services.tunes import (
    FAMILY_LABELS,
    add_alias,
    build_tune_previews,
    core_setting,
    create_tune,
    delete_tune,
    get_tempo_history,
    get_tune,
    list_tunes,
    record_tempo,
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
_STUB_USER_ID = 1


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
    tune_previews = build_tune_previews(tunes)
    ctx = {
        "tunes": tunes,
        "tune_types": _TUNE_TYPES,
        "family_labels": FAMILY_LABELS,
        "active_type": tune_type,
        "active_family": family,
        "tune_previews": tune_previews,
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
    list_id: int | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")

    # Progress is not a setting-override source the way a box or list entry
    # is (see #120) — it only ever affects the breadcrumb, and only when
    # nothing more specific (list, then box) is already provided.
    from_progress = from_ == "progress"

    active_setting = None
    box = None
    if box_id is not None:
        box, entry = await get_box(db, box_id), await get_box_entry(db, box_id, tune_id)
        if entry and entry.setting_id is not None:
            active_setting = entry.setting

    linked_list = None
    if list_id is not None:
        linked_list, list_entry = await get_list(db, list_id), await get_list_entry(db, list_id, tune_id)
        # A list's own setting override outranks the box's, per the setting
        # resolution order in AGENTS.md.
        if list_entry and list_entry.setting_id is not None:
            active_setting = list_entry.setting

    core = core_setting(tune)
    if active_setting is None:
        active_setting = core

    built_abc = build_abc(tune, active_setting) if active_setting else ""
    settings_abc = {s.id: build_abc(tune, s) for s in tune.settings}
    min_tempo, tempo_records = await get_tempo_history(db, _STUB_USER_ID, tune_id)
    beats_per_bar = int(tune.time_signature.split("/")[0])

    boxes = await list_boxes(db, _STUB_USER_ID)
    box_entries = {b.id: next((e for e in b.entries if e.tune_id == tune_id), None) for b in boxes}
    lists_by_box_id: dict[int, list] = {}
    for practice_list in await list_lists(db, _STUB_USER_ID):
        lists_by_box_id.setdefault(practice_list.box_id, []).append(practice_list)
    active_list = await get_active_list(db, _STUB_USER_ID)

    return templates.TemplateResponse(
        request,
        "tunes/detail.html",
        {
            "tune": tune,
            "built_abc": built_abc,
            "settings_abc": settings_abc,
            "active_setting_id": active_setting.id if active_setting else None,
            "thesession_setting_anchor_id": core.thesession_setting_id if core else None,
            "box": box,
            "box_id": box_id,
            "linked_list": linked_list,
            "list_id": list_id,
            "from_progress": from_progress,
            "min_tempo": min_tempo,
            "tempo_records": tempo_records,
            "last_tempo": tempo_records[-1].tempo if tempo_records else None,
            "beats_per_bar": beats_per_bar,
            "boxes": boxes,
            "box_entries": box_entries,
            "non_core_settings": [s for s in tune.settings if not s.is_core],
            "lists_by_box_id": lists_by_box_id,
            "active_list_id": active_list.id if active_list else None,
            **_SETTINGS_CTX,
        },
    )


async def _box_membership_context(db: AsyncSession, tune: Tune, box_id: int) -> dict:
    box = await get_box(db, box_id)
    if box is None:
        raise HTTPException(status_code=404, detail="Box not found")
    entry = await get_box_entry(db, box_id, tune.id)
    lists_for_box = [pl for pl in await list_lists(db, _STUB_USER_ID) if pl.box_id == box_id]
    active_list = await get_active_list(db, _STUB_USER_ID)
    return {
        "tune": tune,
        "box": box,
        "entry": entry,
        "non_core_settings": [s for s in tune.settings if not s.is_core],
        "lists_for_box": lists_for_box,
        "active_list_id": active_list.id if active_list else None,
    }


@router.post("/{tune_id}/boxes")
async def tune_add_to_box(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    box_id: int = Form(...),
    setting_id: str = Form(default=""),
    list_id: str = Form(default=""),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")

    sid = int(setting_id) if setting_id else None
    try:
        await add_tune(db, box_id, tune_id)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Tune already in box") from exc
    # add_tune() may have auto-picked a setting via its own instrument-matching
    # heuristic; the user's explicit choice (including "Core setting") always
    # takes precedence, so this runs unconditionally rather than only when sid
    # is not None.
    await set_preferred_setting(db, box_id, tune_id, sid)

    if list_id:
        try:
            await add_tune_to_list(db, int(list_id), tune_id, setting_id=sid)
        except IntegrityError:
            pass  # already in that list — the box add still succeeded

    ctx = await _box_membership_context(db, tune, box_id)
    return templates.TemplateResponse(request, "tunes/partials/_box_membership_row.html", ctx)


@router.post("/{tune_id}/boxes/{box_id}/setting")
async def tune_update_box_setting(
    request: Request,
    tune_id: int,
    box_id: int,
    db: AsyncSession = Depends(get_db),
    setting_id: str = Form(default=""),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    if await get_box_entry(db, box_id, tune_id) is None:
        raise HTTPException(status_code=404, detail="Tune not in box")

    sid = int(setting_id) if setting_id else None
    await set_preferred_setting(db, box_id, tune_id, sid)

    ctx = await _box_membership_context(db, tune, box_id)
    return templates.TemplateResponse(request, "tunes/partials/_box_membership_row.html", ctx)


@router.post("/{tune_id}/tempo")
async def tempo_record_create(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    tempo: int = Form(...),
    box_id: int | None = Form(None),
) -> Response:
    await record_tempo(db, _STUB_USER_ID, tune_id, box_id, tempo)
    min_tempo, tempo_records = await get_tempo_history(db, _STUB_USER_ID, tune_id)
    return templates.TemplateResponse(
        request,
        "tunes/partials/_tempo_history.html",
        {"min_tempo": min_tempo, "tempo_records": tempo_records},
    )


@router.get("/{tune_id}/tempo-history")
async def tempo_history_partial(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    min_tempo, tempo_records = await get_tempo_history(db, _STUB_USER_ID, tune_id)
    return templates.TemplateResponse(
        request,
        "tunes/partials/_tempo_history.html",
        {"min_tempo": min_tempo, "tempo_records": tempo_records},
    )


@router.get("/{tune_id}/edit")
async def tune_edit(request: Request, tune_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    core = core_setting(tune)
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
