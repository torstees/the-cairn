import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_current_user, get_current_user_optional, get_db
from cairn.models import Instrument, User, WarmupType
from cairn.services.content import render_markdown
from cairn.services.warmups import (
    create_warmup,
    delete_warmup,
    get_warmup,
    get_warmup_tempo,
    list_warmups,
    update_warmup,
    upsert_warmup_tempo,
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
async def warmup_new(request: Request, user: User = Depends(get_current_user)) -> Response:
    return templates.TemplateResponse(
        request,
        "warmups/form.html",
        {
            "warmup": None,
            "warmup_types": _WARMUP_TYPES,
            "instruments": _INSTRUMENTS,
            "selected_instruments": set(),
            "error": None,
        },
    )


@router.post("")
async def warmup_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    title: str = Form(...),
    warmup_type: str = Form(...),
    content: str = Form(...),
    difficulty: int = Form(...),
    instrument: list[str] = Form(default=[]),
    default_tempo: str | None = Form(default=None),
) -> Response:
    instruments = [Instrument(v) for v in instrument if v]
    warmup = await create_warmup(
        db,
        title=title,
        warmup_type=WarmupType(warmup_type),
        content=content,
        difficulty=difficulty,
        instruments=instruments,
        default_tempo=int(default_tempo) if default_tempo else None,
    )
    logger.info("warmup created", extra={"warmup_id": warmup.id})
    return RedirectResponse(f"/warmups/{warmup.id}", status_code=303)


@router.post("/preview-markdown")
async def warmup_preview_markdown(
    request: Request,
    user: User = Depends(get_current_user),
    content: str = Form(default=""),
) -> Response:
    return templates.TemplateResponse(
        request,
        "warmups/partials/_markdown_preview.html",
        {"rendered_body": render_markdown(content)},
    )


@router.get("/{warmup_id}")
async def warmup_detail(
    request: Request,
    warmup_id: int,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> Response:
    warmup = await get_warmup(db, warmup_id)
    if warmup is None:
        raise HTTPException(status_code=404, detail="Warmup not found")
    # A guest (see #225) has no personal tempo history for this warmup.
    last_tempo = await get_warmup_tempo(db, user.id, warmup_id) if user else None
    is_abc = warmup.warmup_type in _ABC_TYPES
    return templates.TemplateResponse(
        request,
        "warmups/detail.html",
        {
            "warmup": warmup,
            "is_abc": is_abc,
            "last_tempo": last_tempo,
            "rendered_body": None if is_abc else render_markdown(warmup.content),
        },
    )


@router.get("/{warmup_id}/edit")
async def warmup_edit(
    request: Request,
    warmup_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    warmup = await get_warmup(db, warmup_id)
    if warmup is None:
        raise HTTPException(status_code=404, detail="Warmup not found")
    selected = {wi.instrument for wi in warmup.instruments}
    return templates.TemplateResponse(
        request,
        "warmups/form.html",
        {
            "warmup": warmup,
            "warmup_types": _WARMUP_TYPES,
            "instruments": _INSTRUMENTS,
            "selected_instruments": selected,
            "error": None,
        },
    )


@router.post("/{warmup_id}")
async def warmup_update(
    request: Request,
    warmup_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    title: str = Form(...),
    warmup_type: str = Form(...),
    content: str = Form(...),
    difficulty: int = Form(...),
    instrument: list[str] = Form(default=[]),
    default_tempo: str | None = Form(default=None),
) -> Response:
    instruments = [Instrument(v) for v in instrument if v]
    warmup = await update_warmup(
        db,
        warmup_id=warmup_id,
        title=title,
        warmup_type=WarmupType(warmup_type),
        content=content,
        difficulty=difficulty,
        instruments=instruments,
        default_tempo=int(default_tempo) if default_tempo else None,
    )
    if warmup is None:
        raise HTTPException(status_code=404, detail="Warmup not found")
    return RedirectResponse(f"/warmups/{warmup_id}", status_code=303)


@router.post("/{warmup_id}/tempo")
async def warmup_tempo_record(
    warmup_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tempo: int = Form(...),
) -> Response:
    warmup = await get_warmup(db, warmup_id)
    if warmup is None:
        raise HTTPException(status_code=404, detail="Warmup not found")
    await upsert_warmup_tempo(db, user.id, warmup_id, tempo)
    return Response(status_code=204)


@router.delete("/{warmup_id}")
async def warmup_delete(
    warmup_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    deleted = await delete_warmup(db, warmup_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Warmup not found")
    return Response(headers={"HX-Redirect": "/warmups"}, status_code=200)
