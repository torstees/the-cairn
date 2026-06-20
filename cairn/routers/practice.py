import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.services.boxes import list_boxes
from cairn.services.lists import get_active_list
from cairn.services.session_plan import build_session, complete_item, finish_session, get_session
from cairn.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/practice", tags=["practice"])

_STUB_USER_ID = 1


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
    active_list = await get_active_list(db, _STUB_USER_ID)
    return templates.TemplateResponse(
        request,
        "practice/session.html",
        {"session": session, "active_list": active_list},
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
        "practice/partials/_item_row.html",
        {"item": item, "session_id": session_id},
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
