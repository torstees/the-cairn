import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import TuneSetting
from cairn.services.abc_utils import build_set_abc
from cairn.services.tune_sets import (
    create_set,
    delete_set,
    get_set,
    list_sets,
    set_members,
    update_set,
)
from cairn.services.tunes import list_tunes
from cairn.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sets", tags=["sets"])

_STUB_USER_ID = 1


def _parse_members(members_raw: str) -> list[dict]:
    try:
        data = json.loads(members_raw.strip()) if members_raw and members_raw.strip() else []
    except (json.JSONDecodeError, ValueError):
        data = []
    result = []
    for m in data:
        tune_id = m.get("tune_id")
        if not tune_id:
            continue
        sid = m.get("setting_id")
        result.append({
            "tune_id": int(tune_id),
            "setting_id": int(sid) if sid else None,
        })
    return result


async def _form_context(db: AsyncSession, tune_set=None, error: str | None = None) -> dict:
    tunes = await list_tunes(db)
    tunes_json = json.dumps([{"id": t.id, "label": t.title} for t in tunes])

    members_data: list[dict] = []
    set_abc_json: str | None = None

    if tune_set is not None:
        for member in tune_set.members:
            settings = [
                {"id": s.id, "label": s.label, "is_core": s.is_core}
                for s in member.tune.settings
            ]
            members_data.append({
                "tune_id": member.tune_id,
                "title": member.tune.title,
                "setting_id": str(member.setting_id) if member.setting_id else "",
                "settings": settings,
            })
        set_abc_json = json.dumps(build_set_abc(tune_set))

    return {
        "tune_set": tune_set,
        "tunes_json": tunes_json,
        "members_json": json.dumps(members_data),
        "set_abc_json": set_abc_json,
        "error": error,
    }


@router.get("")
async def set_index(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    sets = await list_sets(db)
    return templates.TemplateResponse(request, "sets/index.html", {"sets": sets})


@router.get("/new")
async def set_new(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    ctx = await _form_context(db)
    return templates.TemplateResponse(request, "sets/form.html", ctx)


@router.get("/tune-settings/{tune_id}")
async def tune_settings_json(tune_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    result = await db.execute(
        select(TuneSetting)
        .where(TuneSetting.tune_id == tune_id)
        .order_by(TuneSetting.is_core.desc(), TuneSetting.label)
    )
    settings = result.scalars().all()
    return JSONResponse([
        {"id": s.id, "label": s.label, "is_core": s.is_core}
        for s in settings
    ])


@router.post("")
async def set_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    description: str = Form(""),
    source: str = Form(""),
    flow_difficulty: str = Form(""),
    flow_difficulty_notes: str = Form(""),
    abc_header: str = Form(""),
    members: str = Form("[]"),
) -> Response:
    diff = int(flow_difficulty) if flow_difficulty.strip() else None
    tune_set = await create_set(
        db,
        title=title,
        description=description.strip() or None,
        source=source.strip() or None,
        abc_header=abc_header.strip() or None,
        flow_difficulty=diff,
        flow_difficulty_notes=flow_difficulty_notes.strip() or None,
    )
    member_data = _parse_members(members)
    if member_data:
        await set_members(db, tune_set.id, member_data)
    return RedirectResponse(f"/sets/{tune_set.id}/edit", status_code=303)


@router.get("/{set_id}/edit")
async def set_edit(
    request: Request, set_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    tune_set = await get_set(db, set_id)
    if tune_set is None:
        raise HTTPException(status_code=404)
    ctx = await _form_context(db, tune_set)
    return templates.TemplateResponse(request, "sets/form.html", ctx)


@router.post("/{set_id}")
async def set_update(
    request: Request,
    set_id: int,
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    description: str = Form(""),
    source: str = Form(""),
    flow_difficulty: str = Form(""),
    flow_difficulty_notes: str = Form(""),
    abc_header: str = Form(""),
    members: str = Form("[]"),
) -> Response:
    diff = int(flow_difficulty) if flow_difficulty.strip() else None
    updated = await update_set(
        db,
        set_id,
        title=title,
        description=description.strip() or None,
        source=source.strip() or None,
        abc_header=abc_header.strip() or None,
        flow_difficulty=diff,
        flow_difficulty_notes=flow_difficulty_notes.strip() or None,
    )
    if updated is None:
        raise HTTPException(status_code=404)
    await set_members(db, set_id, _parse_members(members))
    return RedirectResponse(f"/sets/{set_id}/edit", status_code=303)


@router.delete("/{set_id}")
async def set_delete(set_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    deleted = await delete_set(db, set_id)
    if not deleted:
        raise HTTPException(status_code=404)
    return Response(headers={"HX-Redirect": "/sets"}, status_code=200)
