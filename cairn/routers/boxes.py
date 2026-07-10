import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import Instrument, TuneType
from cairn.services.boxes import (
    add_tune,
    create_box,
    get_box,
    get_box_detail,
    get_box_entry,
    list_boxes,
    remove_tune,
    set_display_alias,
    set_preferred_setting,
)
from cairn.services.lists import bulk_update_list_entry_setting, find_list_entries_by_setting
from cairn.services.tunes import FAMILY_LABELS, TUNE_FAMILIES, list_tunes, preview_abc
from cairn.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/boxes", tags=["boxes"])

_STUB_USER_ID = 1
_INSTRUMENTS = list(Instrument)
_TUNE_TYPES = list(TuneType)
_FAMILY_FOR_TYPE: dict[str, str] = {t.value: family for family, types in TUNE_FAMILIES.items() for t in types}


def _entry_previews(entries) -> dict[int, str]:
    """Map tune id -> ABC preview for box entries, preferring each entry's chosen setting.

    Uses the entry's own display alias (if any) for the preview's T: header,
    matching the name the row itself shows (#119).
    """
    previews: dict[int, str] = {}
    for entry in entries:
        display_name = entry.display_alias.name if entry.display_alias else None
        abc = preview_abc(entry.tune, entry.setting, display_name=display_name)
        if abc is not None:
            previews[entry.tune_id] = abc
    return previews


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
    tune_previews = _entry_previews(box.entries)
    return templates.TemplateResponse(
        request,
        "boxes/detail.html",
        {
            "box": box,
            "addable_tunes": addable_tunes,
            "addable_tunes_json": addable_tunes_json,
            "family_labels": FAMILY_LABELS,
            "tune_types": _TUNE_TYPES,
            "family_for_type": _FAMILY_FOR_TYPE,
            "tune_previews": tune_previews,
        },
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
        {"entry": entry, "box_id": box_id, "tune_previews": _entry_previews([entry])},
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
    old_entry = await get_box_entry(db, box_id, tune_id)
    old_setting_id = old_entry.setting_id if old_entry else None

    sid = int(setting_id) if setting_id else None
    await set_preferred_setting(db, box_id, tune_id, sid)
    entry = await get_box_entry(db, box_id, tune_id)

    affected = []
    if old_setting_id != sid:
        affected = await find_list_entries_by_setting(db, tune_id, box_id, old_setting_id)

    tune_previews = _entry_previews([entry])

    if not affected:
        return templates.TemplateResponse(
            request,
            "boxes/partials/_tune_row.html",
            {"entry": entry, "box_id": box_id, "tune_previews": tune_previews},
        )

    box = await get_box(db, box_id)
    row_html = templates.env.get_template("boxes/partials/_tune_row.html").render(
        {"entry": entry, "box_id": box_id, "tune_previews": tune_previews}
    )
    modal_html = templates.env.get_template("boxes/partials/_setting_change_modal.html").render(
        {
            "affected_entries": affected,
            "box_id": box_id,
            "tune_id": tune_id,
            "new_setting_id": sid,
            "tune_title": entry.tune.title,
            "box_name": box.name if box else "",
        }
    )
    return Response(content=row_html + modal_html, media_type="text/html")


@router.post("/{box_id}/tunes/{tune_id}/display-alias")
async def box_set_display_alias(
    request: Request,
    box_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    display_alias_id: str = Form(default=""),
) -> Response:
    if await get_box_entry(db, box_id, tune_id) is None:
        raise HTTPException(status_code=404, detail="Tune not in box")

    daid = int(display_alias_id) if display_alias_id else None
    await set_display_alias(db, box_id, tune_id, daid)
    entry = await get_box_entry(db, box_id, tune_id)
    return templates.TemplateResponse(
        request,
        "boxes/partials/_tune_row.html",
        {"entry": entry, "box_id": box_id, "tune_previews": _entry_previews([entry])},
    )


@router.post("/{box_id}/tunes/{tune_id}/propagate-setting")
async def box_propagate_setting(
    box_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    setting_id: str = Form(default=""),
    list_ids: list[int] = Form(default=[]),
) -> Response:
    sid = int(setting_id) if setting_id else None
    logger.debug(
        "propagate setting: box=%s tune=%s setting_id=%r list_ids=%r",
        box_id,
        tune_id,
        sid,
        list_ids,
    )
    await bulk_update_list_entry_setting(db, tune_id, list_ids, sid)
    return Response(content='<div id="box-setting-modal"></div>', media_type="text/html")
