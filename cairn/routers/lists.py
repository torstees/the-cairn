import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import PracticeListType, ProgressStatus
from cairn.services.boxes import get_box_detail, list_boxes
from cairn.services.lists import (
    activate_list,
    add_tune_to_list,
    create_list,
    deactivate_list,
    delete_list,
    get_list,
    get_list_entry,
    list_lists,
    remove_tune_from_list,
    update_list,
    update_list_entry_setting,
)
from cairn.services.tunes import FAMILY_LABELS, TUNE_FAMILIES, list_tunes, preview_abc
from cairn.templating import templates

router = APIRouter(prefix="/lists", tags=["lists"])

_STUB_USER_ID = 1
_LIST_TYPES = list(PracticeListType)
_PROGRESS_STATUSES = [s for s in ProgressStatus if s != ProgressStatus.just_learning]
_FAMILY_FOR_TYPE: dict[str, str] = {t.value: family for family, types in TUNE_FAMILIES.items() for t in types}


def _entry_previews(entries) -> dict[int, str]:
    """Map tune id -> ABC preview for list entries, preferring each entry's chosen setting."""
    previews: dict[int, str] = {}
    for entry in entries:
        abc = preview_abc(entry.tune, entry.setting)
        if abc is not None:
            previews[entry.tune_id] = abc
    return previews


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
async def list_new(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    boxes = await list_boxes(db, _STUB_USER_ID)
    return templates.TemplateResponse(
        request,
        "lists/form.html",
        {
            "practice_list": None,
            "list_types": _LIST_TYPES,
            "progress_statuses": _PROGRESS_STATUSES,
            "boxes": boxes,
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


@router.get("/{list_id}/edit")
async def list_edit(
    request: Request,
    list_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    practice_list = await get_list(db, list_id)
    if practice_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    return templates.TemplateResponse(
        request,
        "lists/form.html",
        {
            "practice_list": practice_list,
            "list_types": _LIST_TYPES,
            "progress_statuses": _PROGRESS_STATUSES,
            "boxes": None,
            "error": None,
        },
    )


@router.post("/{list_id}")
async def list_update(
    request: Request,
    list_id: int,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    list_type: PracticeListType = Form(...),
    progress_goal: ProgressStatus = Form(default=ProgressStatus.committed),
    target_date: str = Form(default=""),
) -> Response:
    from datetime import date

    parsed_date = date.fromisoformat(target_date) if target_date else None
    practice_list = await update_list(db, list_id, name, list_type, progress_goal, parsed_date)
    if practice_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    return RedirectResponse(f"/lists/{list_id}", status_code=303)


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
    addable_tunes_json = json.dumps(
        [
            {
                "id": t.id,
                "label": f"{t.title} — {t.tune_type.label} · {t.key_root.label} {t.key_mode.label}",
                "type": t.tune_type.value,
                "family": _FAMILY_FOR_TYPE.get(t.tune_type.value, "other"),
            }
            for t in addable_tunes
        ]
    )
    settings_by_tune_id = json.dumps(
        {
            t.id: [
                {"id": s.id, "label": s.label + (f" ({s.instrument.label})" if s.instrument else "")}
                for s in t.settings
                if not s.is_core
            ]
            for t in addable_tunes
        }
    )
    box = await get_box_detail(db, practice_list.box_id)
    box_entries = box.entries if box else []
    box_setting_by_tune_id = json.dumps({e.tune_id: e.setting_id for e in box_entries if e.setting_id is not None})
    box_tune_ids_json = json.dumps([e.tune_id for e in box_entries])
    tune_previews = _entry_previews(practice_list.entries)
    return templates.TemplateResponse(
        request,
        "lists/detail.html",
        {
            "practice_list": practice_list,
            "addable_tunes": addable_tunes,
            "addable_tunes_json": addable_tunes_json,
            "settings_by_tune_id": settings_by_tune_id,
            "box_setting_by_tune_id": box_setting_by_tune_id,
            "box_tune_ids_json": box_tune_ids_json,
            "box_name": box.name if box else "",
            "family_labels": FAMILY_LABELS,
            "family_for_type": _FAMILY_FOR_TYPE,
            "tune_previews": tune_previews,
        },
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
    setting_id: str = Form(default=""),
) -> Response:
    practice_list = await get_list(db, list_id)
    if practice_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    parsed_setting_id = int(setting_id) if setting_id else None
    try:
        await add_tune_to_list(db, list_id, tune_id, setting_id=parsed_setting_id)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Tune already in list") from exc
    entry = await get_list_entry(db, list_id, tune_id)
    return templates.TemplateResponse(
        request,
        "lists/partials/_entry_row.html",
        {"entry": entry, "list_id": list_id, "tune_previews": _entry_previews([entry])},
    )


@router.post("/{list_id}/tunes/{tune_id}/setting")
async def list_set_entry_setting(
    request: Request,
    list_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    setting_id: str = Form(default=""),
) -> Response:
    sid = int(setting_id) if setting_id else None
    entry = await update_list_entry_setting(db, list_id, tune_id, sid)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return templates.TemplateResponse(
        request,
        "lists/partials/_entry_row.html",
        {"entry": entry, "list_id": list_id, "tune_previews": _entry_previews([entry])},
    )


@router.delete("/{list_id}")
async def list_delete(
    list_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    deleted = await delete_list(db, list_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="List not found")
    return Response(status_code=200, headers={"HX-Redirect": "/lists"})


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
