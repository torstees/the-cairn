import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import ProgressStatus, TempoRecord
from cairn.services.abc_utils import build_abc, truncate_to_bars
from cairn.services.boxes import get_display_names_for_tunes, list_boxes
from cairn.services.lists import activate_list, deactivate_list, get_active_list, list_lists
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


def _build_item_display(
    items, progress_map: dict[int, ProgressStatus], display_names: dict[int, str] | None = None
) -> dict[int, dict]:
    """Build per-item display data (ABC variants + cheat levels) for tune items.

    display_names is tune_id -> the box's chosen display alias name (#119),
    for tunes that have one — used for the ABC's T: header and the session
    item's own title, so a tune's alias follows it into the active practice
    session the same way it already shows in that box's own tune list.
    """
    display_names = display_names or {}
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

        display_name = display_names.get(tune.id, tune.title)
        abc_full = build_abc(tune, core, display_name=display_name)
        abc_4 = truncate_to_bars(abc_full, 4) if 4 in levels else None
        abc_8 = truncate_to_bars(abc_full, 8) if 8 in levels else None

        key_label = f"{tune.key_root.value} {tune.key_mode.label}"
        display[item.id] = {
            "levels": levels,  # Python list (not JSON string)
            "abc_full": abc_full,
            "abc_4": abc_4 or "",
            "abc_8": abc_8 or "",
            "key_label": key_label,
            "initial_bars": bars,
            "display_name": display_name,
        }
    return display


@router.get("/plan")
async def plan_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    boxes = await list_boxes(db, _STUB_USER_ID)
    active_list = await get_active_list(db, _STUB_USER_ID)
    all_lists = await list_lists(db, _STUB_USER_ID)
    lists_by_box: dict[int, list[dict]] = {}
    for pl in all_lists:
        lists_by_box.setdefault(pl.box_id, []).append({"id": pl.id, "name": pl.name, "type_label": pl.list_type.label})
    default_box_id = active_list.box_id if active_list else (boxes[0].id if boxes else None)
    return templates.TemplateResponse(
        request,
        "practice/plan.html",
        {
            "boxes": boxes,
            "active_list": active_list,
            "lists_by_box": lists_by_box,
            "default_box_id": default_box_id,
        },
    )


@router.post("/plan")
async def plan_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    box_id: int = Form(...),
    total_minutes: int = Form(...),
    list_id: str = Form(""),
) -> Response:
    if list_id == "":
        await deactivate_list(db, _STUB_USER_ID)
    else:
        await activate_list(db, _STUB_USER_ID, int(list_id))
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
    display_names: dict[int, str] = {}
    if tune_ids and session.box_id:
        progress_map = await _load_progress_map(db, _STUB_USER_ID, session.box_id, tune_ids)
        display_names = await get_display_names_for_tunes(db, session.box_id, tune_ids)

    item_display = _build_item_display(session.items, progress_map, display_names)

    # Batch-fetch last recorded tempo for each tune in this session.
    last_tempo_map: dict[int, int] = {}
    if tune_ids:
        rows = await db.execute(
            select(TempoRecord)
            .where(TempoRecord.user_id == _STUB_USER_ID, TempoRecord.tune_id.in_(tune_ids))
            .order_by(TempoRecord.created_at.desc())
        )
        for r in rows.scalars().all():
            if r.tune_id not in last_tempo_map:
                last_tempo_map[r.tune_id] = r.tempo

    # Build the per-item data structure consumed by the one-at-a-time session view.
    session_items: list[dict] = []
    for item in session.items:
        if item.tune:
            disp = item_display.get(item.id)
            tune = item.tune
            try:
                beats = int(tune.time_signature.split("/")[0])
            except (ValueError, IndexError):
                beats = 4
            session_items.append(
                {
                    "id": item.id,
                    "type": "tune",
                    "itemType": item.item_type.value,
                    "itemTypeLabel": item.item_type.label,
                    "title": disp["display_name"] if disp else tune.title,
                    "minutesAllocated": item.minutes_allocated,
                    "completed": item.completed,
                    "tuneId": tune.id,
                    "tuneType": tune.tune_type.value,
                    "beatsPerBar": beats,
                    "lastTempo": last_tempo_map.get(tune.id),
                    "boxId": session.box_id,
                    "levels": disp["levels"] if disp else [-1],
                    "abcFull": disp["abc_full"] if disp else "",
                    "abc4": disp["abc_4"] if disp else "",
                    "abc8": disp["abc_8"] if disp else "",
                    "keyLabel": disp["key_label"] if disp else "",
                    "hasAbc": bool(disp and disp["abc_full"]),
                }
            )
        elif item.warmup:
            session_items.append(
                {
                    "id": item.id,
                    "type": "warmup",
                    "itemType": "warmup",
                    "itemTypeLabel": "Warmup",
                    "title": item.warmup.title,
                    "minutesAllocated": item.minutes_allocated,
                    "completed": item.completed,
                    "hasAbc": False,
                }
            )
        else:
            session_items.append(
                {
                    "id": item.id,
                    "type": "other",
                    "itemType": "other",
                    "itemTypeLabel": "Item",
                    "title": "Practice Item",
                    "minutesAllocated": item.minutes_allocated,
                    "completed": item.completed,
                    "hasAbc": False,
                }
            )

    active_list = await get_active_list(db, _STUB_USER_ID)
    return templates.TemplateResponse(
        request,
        "practice/session.html",
        {
            "session": session,
            "active_list": active_list,
            "session_items_json": json.dumps(session_items),
        },
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
