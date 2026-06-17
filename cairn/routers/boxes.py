from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import Instrument
from cairn.services.boxes import (
    add_tune,
    create_box,
    get_box_detail,
    get_box_entry,
    list_boxes,
    remove_tune,
    set_preferred_setting,
)
from cairn.services.tunes import list_tunes
from cairn.templating import templates

router = APIRouter(prefix="/boxes", tags=["boxes"])

_STUB_USER_ID = 1
_INSTRUMENTS = list(Instrument)


@router.get("/")
async def box_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    boxes = await list_boxes(db, _STUB_USER_ID)
    return templates.TemplateResponse(request, "boxes/index.html", {"boxes": boxes})


@router.get("/new")
async def box_new(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "boxes/form.html",
        {"box": None, "instruments": _INSTRUMENTS, "error": None},
    )


@router.post("/")
async def box_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    instruments: list[str] = Form(default=[]),
) -> Response:
    if not instruments:
        return templates.TemplateResponse(
            request,
            "boxes/form.html",
            {
                "box": None,
                "instruments": _INSTRUMENTS,
                "error": "Select at least one instrument.",
                "name": name,
            },
            status_code=422,
        )
    instrument_enums = [Instrument(i) for i in instruments]
    box = await create_box(db, _STUB_USER_ID, name, instrument_enums)
    return RedirectResponse(f"/boxes/{box.id}", status_code=303)


@router.get("/{box_id}")
async def box_detail(
    request: Request,
    box_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    box = await get_box_detail(db, box_id)
    if box is None:
        raise HTTPException(status_code=404, detail="Box not found")
    entry_tune_ids = {e.tune_id for e in box.entries}
    all_tunes = await list_tunes(db)
    addable_tunes = [t for t in all_tunes if t.id not in entry_tune_ids]
    return templates.TemplateResponse(
        request,
        "boxes/detail.html",
        {"box": box, "addable_tunes": addable_tunes},
    )


@router.post("/{box_id}/tunes")
async def box_add_tune(
    request: Request,
    box_id: int,
    db: AsyncSession = Depends(get_db),
    tune_id: int = Form(...),
) -> Response:
    box = await get_box_detail(db, box_id)
    if box is None:
        raise HTTPException(status_code=404, detail="Box not found")
    try:
        await add_tune(db, box_id, tune_id)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Tune already in box") from exc
    entry = await get_box_entry(db, box_id, tune_id)
    return templates.TemplateResponse(
        request,
        "boxes/partials/_tune_row.html",
        {"entry": entry, "box_id": box_id},
    )


@router.delete("/{box_id}/tunes/{tune_id}")
async def box_remove_tune(
    box_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    removed = await remove_tune(db, box_id, tune_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Tune not in box")
    return Response(status_code=200)


@router.post("/{box_id}/tunes/{tune_id}/setting")
async def box_set_setting(
    request: Request,
    box_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    setting_id: str = Form(default=""),
) -> Response:
    sid = int(setting_id) if setting_id else None
    entry = await set_preferred_setting(db, box_id, tune_id, sid)
    # Reload with full relationships for the partial
    entry = await get_box_entry(db, box_id, tune_id)
    return templates.TemplateResponse(
        request,
        "boxes/partials/_tune_row.html",
        {"entry": entry, "box_id": box_id},
    )
