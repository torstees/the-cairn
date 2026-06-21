import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import ProgressStatus
from cairn.services.abc_utils import build_abc, truncate_to_bars
from cairn.services.boxes import list_boxes
from cairn.services.lists import get_active_list
from cairn.services.session_plan import (
    _load_progress_map,
    bars_for_status,
    build_session,
    complete_item,
    finish_session,
    get_session,
    rate_item,
)
from cairn.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/practice", tags=["practice"])

_STUB_USER_ID = 1

# Cheat levels available above each starting level.
# Keys match the sentinel values returned by bars_for_status.
_CHEAT_LEVELS: dict[int | None, list[int | None]] = {
    None: [None, 4, 8, -1],  # title only → 4 → 8 → full
    4: [4, 8, -1],  # 4 bars → 8 → full
    8: [8, -1],  # 8 bars → full
    -1: [-1],  # full → (already at max)
}


def _build_item_display(items, progress_map: dict[int, ProgressStatus]) -> dict[int, dict]:
    """Build per-item display data (ABC variants + cheat levels) for tune items."""
    display: dict[int, dict] = {}
    for item in items:
        if item.tune is None:
            continue
        tune = item.tune
        core = next((s for s in tune.settings if s.is_core), None)
        if core is None:
            continue

        status = progress_map.get(tune.id, ProgressStatus.just_learning)
        bars = bars_for_status(status)
        levels = _CHEAT_LEVELS.get(bars, [-1])

        abc_full = build_abc(tune, core)
        abc_4 = truncate_to_bars(abc_full, 4) if 4 in levels else None
        abc_8 = truncate_to_bars(abc_full, 8) if 8 in levels else None

        key_label = f"{tune.key_root.value} {tune.key_mode.label}"
        display[item.id] = {
            "levels": json.dumps(levels),
            "abc_full": abc_full,
            "abc_4": abc_4 or "",
            "abc_8": abc_8 or "",
            "key_label": key_label,
            "initial_bars": bars,
        }
    return display


@router.get("/plan")
async def plan_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    boxes = await list_boxes(db, _STUB_USER_ID)
    active_list = await get_active_list(db, _STUB_USER_ID)
    return templates.TemplateResponse(
        request,
        "practice/plan.html",
        {"boxes": boxes, "active_list": active_list},
    )


@router.post("/plan")
async def plan_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    box_id: int = Form(...),
    total_minutes: int = Form(...),
) -> Response:
    session = await build_session(db, _STUB_USER_ID, box_id, total_minutes)
    logger.info("practice session created", extra={"session_id": session.id, "box_id": box_id})
    return RedirectResponse(f"/practice/session/{session.id}", status_code=303)


@router.get("/session/{session_id}")
async def session_detail(
    request: Request,
    session_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    tune_ids = {item.tune_id for item in session.items if item.tune_id}
    progress_map: dict[int, ProgressStatus] = {}
    if tune_ids and session.box_id:
        progress_map = await _load_progress_map(db, _STUB_USER_ID, session.box_id, tune_ids)

    item_display = _build_item_display(session.items, progress_map)
    active_list = await get_active_list(db, _STUB_USER_ID)
    return templates.TemplateResponse(
        request,
        "practice/session.html",
        {"session": session, "active_list": active_list, "item_display": item_display},
    )


@router.post("/session/{session_id}/item/{item_id}/complete")
async def item_complete(
    request: Request,
    session_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    item = await complete_item(db, session_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return templates.TemplateResponse(
        request,
        "practice/partials/_done_indicator.html",
        {"item": item},
    )


@router.post("/session/{session_id}/item/{item_id}/rate")
async def item_rate(
    request: Request,
    session_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    confidence: int = Form(...),
) -> Response:
    item = await rate_item(db, session_id, item_id, _STUB_USER_ID, confidence)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return templates.TemplateResponse(
        request,
        "practice/partials/_done_indicator.html",
        {"item": item},
    )


@router.post("/session/{session_id}/finish")
async def session_finish(
    session_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    session = await finish_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    logger.info("practice session finished", extra={"session_id": session_id, "total_minutes": session.total_minutes})
    return RedirectResponse(f"/practice/session/{session_id}", status_code=303)
