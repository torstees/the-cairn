import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import Instrument, WarmupType
from cairn.services.warmups import (
    create_warmup,
    delete_warmup,
    get_warmup,
    list_warmups,
    update_warmup,
)
from cairn.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/warmups", tags=["warmups"])

_WARMUP_TYPES = list(WarmupType)
_INSTRUMENTS = list(Instrument)
_ABC_TYPES = {WarmupType.scale, WarmupType.snippet}


@router.get("")
async def warmup_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    warmups = await list_warmups(db)
    return templates.TemplateResponse(
        request,
        "warmups/index.html",
        {"warmups": warmups, "abc_types": _ABC_TYPES},
    )


@router.get("/new")
async def warmup_new(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "warmups/form.html",
        {
            "warmup": None,
            "warmup_types": _WARMUP_TYPES,
            "instruments": _INSTRUMENTS,
            "error": None,
        },
    )


@router.post("")
async def warmup_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    warmup_type: str = Form(...),
    content: str = Form(...),
    difficulty: int = Form(...),
    instrument: str = Form(default=""),
) -> Response:
    instrument_enum = Instrument(instrument) if instrument else None
    warmup = await create_warmup(
        db,
        title=title,
        warmup_type=WarmupType(warmup_type),
        content=content,
        difficulty=difficulty,
        instrument=instrument_enum,
    )
    logger.info("warmup created", extra={"warmup_id": warmup.id})
    return RedirectResponse(f"/warmups/{warmup.id}", status_code=303)


@router.get("/{warmup_id}")
async def warmup_detail(
    request: Request,
    warmup_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    warmup = await get_warmup(db, warmup_id)
    if warmup is None:
        raise HTTPException(status_code=404, detail="Warmup not found")
    return templates.TemplateResponse(
        request,
        "warmups/detail.html",
        {"warmup": warmup, "is_abc": warmup.warmup_type in _ABC_TYPES},
    )


@router.get("/{warmup_id}/edit")
async def warmup_edit(
    request: Request,
    warmup_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    warmup = await get_warmup(db, warmup_id)
    if warmup is None:
        raise HTTPException(status_code=404, detail="Warmup not found")
    return templates.TemplateResponse(
        request,
        "warmups/form.html",
        {
            "warmup": warmup,
            "warmup_types": _WARMUP_TYPES,
            "instruments": _INSTRUMENTS,
            "error": None,
        },
    )


@router.post("/{warmup_id}")
async def warmup_update(
    request: Request,
    warmup_id: int,
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    warmup_type: str = Form(...),
    content: str = Form(...),
    difficulty: int = Form(...),
    instrument: str = Form(default=""),
) -> Response:
    instrument_enum = Instrument(instrument) if instrument else None
    warmup = await update_warmup(
        db,
        warmup_id=warmup_id,
        title=title,
        warmup_type=WarmupType(warmup_type),
        content=content,
        difficulty=difficulty,
        instrument=instrument_enum,
    )
    if warmup is None:
        raise HTTPException(status_code=404, detail="Warmup not found")
    return RedirectResponse(f"/warmups/{warmup_id}", status_code=303)


@router.delete("/{warmup_id}")
async def warmup_delete(
    warmup_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    deleted = await delete_warmup(db, warmup_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Warmup not found")
    return Response(headers={"HX-Redirect": "/warmups"}, status_code=200)
