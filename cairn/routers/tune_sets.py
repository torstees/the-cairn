import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_current_user, get_db
from cairn.models import ProgressStatus, StudentProgress, TuneSetting, TuneType, User
from cairn.services.abc_utils import build_set_abc
from cairn.services.boxes import get_box
from cairn.services.tune_sets import (
    create_set,
    delete_set,
    get_set,
    get_set_tempo,
    list_sets,
    set_members,
    update_set,
    upsert_set_tempo,
)
from cairn.services.tunes import FAMILY_LABELS, TUNE_FAMILIES, list_tunes
from cairn.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sets", tags=["sets"])

_TUNE_TYPES = list(TuneType)
_FAMILY_FOR_TYPE: dict[str, str] = {t.value: family for family, types in TUNE_FAMILIES.items() for t in types}


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
        result.append(
            {
                "tune_id": int(tune_id),
                "setting_id": int(sid) if sid else None,
            }
        )
    return result


async def _form_context(db: AsyncSession, user_id: int, tune_set=None, error: str | None = None) -> dict:
    tunes = await list_tunes(db, user_id)
    tunes_json = json.dumps(
        [
            {
                "id": t.id,
                "label": f"{t.title} — {t.tune_type.label} · {t.key_root.label} {t.key_mode.label}",
                "type": t.tune_type.value,
                "family": _FAMILY_FOR_TYPE.get(t.tune_type.value, "other"),
            }
            for t in tunes
        ]
    )

    members_data: list[dict] = []
    set_abc_json: str | None = None

    if tune_set is not None:
        for member in tune_set.members:
            settings = [{"id": s.id, "label": s.label, "is_core": s.is_core} for s in member.tune.settings]
            members_data.append(
                {
                    "tune_id": member.tune_id,
                    "title": member.tune.title,
                    "type_label": member.tune.tune_type.label,
                    "setting_id": str(member.setting_id) if member.setting_id else "",
                    "settings": settings,
                }
            )
        set_abc_json = json.dumps(build_set_abc(tune_set))

    return {
        "tune_set": tune_set,
        "tunes_json": tunes_json,
        "members_json": json.dumps(members_data),
        "set_abc_json": set_abc_json,
        "family_labels": FAMILY_LABELS,
        "tune_types": _TUNE_TYPES,
        "error": error,
    }


@router.get("")
async def set_index(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    sets = await list_sets(db)
    return templates.TemplateResponse(request, "sets/index.html", {"sets": sets})


@router.get("/new")
async def set_new(
    request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    ctx = await _form_context(db, user.id)
    return templates.TemplateResponse(request, "sets/form.html", ctx)


@router.get("/tune-settings/{tune_id}")
async def tune_settings_json(tune_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    result = await db.execute(
        select(TuneSetting)
        .where(TuneSetting.tune_id == tune_id)
        .order_by(TuneSetting.is_core.desc(), TuneSetting.label)
    )
    settings = result.scalars().all()
    return JSONResponse([{"id": s.id, "label": s.label, "is_core": s.is_core} for s in settings])


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
    request: Request, set_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    tune_set = await get_set(db, set_id)
    if tune_set is None:
        raise HTTPException(status_code=404)
    ctx = await _form_context(db, user.id, tune_set)
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


def _bars_from_progress(status: ProgressStatus | None) -> str:
    if status in (ProgressStatus.committed, ProgressStatus.performance_ready, ProgressStatus.solo_ready):
        return "full"
    if status in (ProgressStatus.getting_there, ProgressStatus.nearly_there, ProgressStatus.session_ready):
        return "8"
    return "2"


@router.get("/{set_id}")
async def set_detail(
    request: Request,
    set_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    box_id: int | None = Query(default=None),
) -> Response:
    tune_set = await get_set(db, set_id)
    if tune_set is None:
        raise HTTPException(status_code=404)

    box = await get_box(db, box_id) if box_id is not None else None
    last_tempo = await get_set_tempo(db, user.id, box_id, set_id) if box_id else None

    # Pre-build three variants of the set ABC server-side (compact single-X:1
    # format that ABCJS renders reliably), rather than combining per-member
    # individual X: blocks in JS.
    set_abc_full = build_set_abc(tune_set, box=box)
    set_abc_8 = build_set_abc(tune_set, box=box, n_bars=8)
    set_abc_2 = build_set_abc(tune_set, box=box, n_bars=2)

    # Progress lookup for default bar counts
    tune_ids = [m.tune_id for m in tune_set.members]
    progress_map: dict[int, ProgressStatus | None] = {}
    if box_id and tune_ids:
        rows = await db.execute(
            select(StudentProgress.tune_id, StudentProgress.status).where(
                StudentProgress.user_id == user.id,
                StudentProgress.box_id == box_id,
                StudentProgress.tune_id.in_(tune_ids),
            )
        )
        progress_map = {row.tune_id: row.status for row in rows}

    members_display = []
    # Keyed by tune_id rather than folded into members_display, since that
    # list is also json.dumps()'d for window.__cairnSetMembers — TuneAlias
    # ORM objects aren't JSON-serializable, and the JS side has no use for
    # them anyway (the tooltip is rendered server-side via alias_tooltip()).
    tune_aliases_by_id: dict[int, list] = {}
    for member in tune_set.members:
        tune = member.tune
        setting = member.setting
        if setting is None:
            setting = next((s for s in tune.settings if s.is_core), None)
            if setting is None and tune.settings:
                setting = tune.settings[0]
        status = progress_map.get(tune.id)
        members_display.append(
            {
                "tune_id": tune.id,
                "title": tune.title,
                "type_label": tune.tune_type.label,
                "key_label": f"{tune.key_root.label} {tune.key_mode.label}",
                "has_abc": setting is not None,
                "progress": status.value if status else None,
                "default_bars": _bars_from_progress(status),
            }
        )
        if tune.aliases:
            tune_aliases_by_id[tune.id] = tune.aliases

    return templates.TemplateResponse(
        request,
        "sets/detail.html",
        {
            "tune_set": tune_set,
            "set_abc_full": set_abc_full,
            "set_abc_8": set_abc_8,
            "set_abc_2": set_abc_2,
            "members_display": members_display,
            "members_json": json.dumps(members_display),
            "tune_aliases_by_id": tune_aliases_by_id,
            "box_id": box_id,
            "last_tempo": last_tempo,
        },
    )


@router.post("/{set_id}/tempo")
async def set_tempo_record(
    set_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tempo: int = Form(...),
    box_id: int = Form(...),
) -> Response:
    await upsert_set_tempo(db, user.id, box_id, set_id, tempo)
    return Response(status_code=204)
