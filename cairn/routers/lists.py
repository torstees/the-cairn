from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import PracticeListType, ProgressStatus
from cairn.services.lists import (
    activate_list,
    add_tune_to_list,
    create_list,
    deactivate_list,
    get_list,
    get_list_entry,
    list_lists,
    remove_tune_from_list,
)
from cairn.services.tunes import list_tunes
from cairn.templating import templates

router = APIRouter(prefix="/lists", tags=["lists"])

_STUB_USER_ID = 1
_LIST_TYPES = list(PracticeListType)
_PROGRESS_STATUSES = [s for s in ProgressStatus if s != ProgressStatus.just_learning]


@router.get("/")
async def list_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    practice_lists = await list_lists(db, _STUB_USER_ID)
    return templates.TemplateResponse(
        request,
        "lists/index.html",
        {"practice_lists": practice_lists},
    )


@router.get("/new")
async def list_new(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "lists/form.html",
        {
            "practice_list": None,
            "list_types": _LIST_TYPES,
            "progress_statuses": _PROGRESS_STATUSES,
            "error": None,
        },
    )


@router.post("/")
async def list_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    list_type: PracticeListType = Form(...),
    box_id: int = Form(...),
    progress_goal: ProgressStatus = Form(default=ProgressStatus.committed),
    target_date: str = Form(default=""),
) -> Response:
    from datetime import date
    parsed_date = date.fromisoformat(target_date) if target_date else None
    practice_list = await create_list(
        db,
        _STUB_USER_ID,
        box_id,
        name,
        list_type,
        progress_goal=progress_goal,
        target_date=parsed_date,
    )
    return RedirectResponse(f"/lists/{practice_list.id}", status_code=303)


@router.get("/{list_id}")
async def list_detail(
    request: Request,
    list_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    practice_list = await get_list(db, list_id)
    if practice_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    entry_tune_ids = {e.tune_id for e in practice_list.entries}
    all_tunes = await list_tunes(db)
    addable_tunes = [t for t in all_tunes if t.id not in entry_tune_ids]
    return templates.TemplateResponse(
        request,
        "lists/detail.html",
        {"practice_list": practice_list, "addable_tunes": addable_tunes},
    )


@router.post("/{list_id}/activate")
async def list_activate(
    request: Request,
    list_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    practice_list = await activate_list(db, _STUB_USER_ID, list_id)
    if practice_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    return templates.TemplateResponse(
        request,
        "lists/partials/_activation.html",
        {"practice_list": practice_list},
    )


@router.post("/{list_id}/deactivate")
async def list_deactivate(
    request: Request,
    list_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    practice_list = await get_list(db, list_id)
    if practice_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    await deactivate_list(db, _STUB_USER_ID)
    practice_list.is_active = False
    return templates.TemplateResponse(
        request,
        "lists/partials/_activation.html",
        {"practice_list": practice_list},
    )


@router.post("/{list_id}/tunes")
async def list_add_tune(
    request: Request,
    list_id: int,
    db: AsyncSession = Depends(get_db),
    tune_id: int = Form(...),
) -> Response:
    practice_list = await get_list(db, list_id)
    if practice_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    try:
        await add_tune_to_list(db, list_id, tune_id)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Tune already in list") from exc
    entry = await get_list_entry(db, list_id, tune_id)
    return templates.TemplateResponse(
        request,
        "lists/partials/_entry_row.html",
        {"entry": entry, "list_id": list_id},
    )


@router.delete("/{list_id}/tunes/{tune_id}")
async def list_remove_tune(
    list_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    removed = await remove_tune_from_list(db, list_id, tune_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Tune not in list")
    return Response(status_code=200)
