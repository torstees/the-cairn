from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import ProgressStatus, Tune, TuneSetting
from cairn.services.abc_utils import strip_chord_symbols, truncate_to_bars
from cairn.services.boxes import get_box_detail, get_box_entry
from cairn.services.spaced_rep import get_user_progress, record_practice, set_status
from cairn.services.tunes import COLUMN_PREVIEW_N_BARS, POPUP_PREVIEW_N_BARS, TunePreview, get_tune, preview_abc
from cairn.templating import templates

router = APIRouter(prefix="/progress", tags=["progress"])

# Phase 1 stubs — replace with real auth + TuneBox selection once those land.
_STUB_USER_ID = 1
_STUB_BOX_ID = 1

_STATUSES = list(ProgressStatus)


def _build_preview(tune: Tune, setting: TuneSetting | None) -> TunePreview | None:
    popup = preview_abc(tune, setting, n_bars=POPUP_PREVIEW_N_BARS, notes_only=True)
    if popup is None:
        return None
    column = strip_chord_symbols(truncate_to_bars(popup, COLUMN_PREVIEW_N_BARS))
    return TunePreview(column=column, popup=popup)


def _tune_previews(pairs, box_setting_by_tune_id: dict[int, TuneSetting]) -> dict[int, TunePreview]:
    previews: dict[int, TunePreview] = {}
    for tune, _progress in pairs:
        preview = _build_preview(tune, box_setting_by_tune_id.get(tune.id))
        if preview is not None:
            previews[tune.id] = preview
    return previews


@router.get("/")
async def progress_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    pairs = await get_user_progress(db, _STUB_USER_ID, _STUB_BOX_ID)
    box = await get_box_detail(db, _STUB_BOX_ID)
    box_setting_by_tune_id = {e.tune_id: e.setting for e in box.entries} if box else {}
    tune_previews = _tune_previews(pairs, box_setting_by_tune_id)
    now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC to match DB-stored datetimes
    return templates.TemplateResponse(
        request,
        "progress/index.html",
        {"pairs": pairs, "statuses": _STATUSES, "now": now, "tune_previews": tune_previews},
    )


@router.post("/{tune_id}")
async def progress_record(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    confidence: int = Form(...),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    progress = await record_practice(db, _STUB_USER_ID, _STUB_BOX_ID, tune_id, confidence)
    entry = await get_box_entry(db, _STUB_BOX_ID, tune_id)
    preview = _build_preview(tune, entry.setting if entry else None)
    tune_previews = {tune.id: preview} if preview is not None else {}
    now = datetime.now(UTC).replace(tzinfo=None)
    return templates.TemplateResponse(
        request,
        "progress/_tune_card.html",
        {"tune": tune, "progress": progress, "statuses": _STATUSES, "now": now, "tune_previews": tune_previews},
    )


@router.post("/{tune_id}/status")
async def progress_set_status(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    status: ProgressStatus = Form(...),
) -> Response:
    tune = await db.get(Tune, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    progress = await set_status(db, _STUB_USER_ID, _STUB_BOX_ID, tune_id, status)
    return templates.TemplateResponse(
        request,
        "components/_progress_badge.html",
        {"tune": tune, "progress": progress},
    )
