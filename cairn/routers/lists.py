import json

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_current_user, get_db
from cairn.models import KeyRoot, PracticeList, PracticeListType, ProgressStatus, User
from cairn.services.abc_utils import (
    strip_chord_symbols,
    strip_decorative_headers,
    transpose_abc,
    transpose_semitones_for,
    truncate_to_bars,
)
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
    update_list_entry_display_alias,
    update_list_entry_setting,
    update_list_entry_transpose,
)
from cairn.services.tune_sets import (
    add_list_set,
    clear_list_set_difficulty,
    compute_default_set_difficulty,
    get_list_set_difficulty_override,
    list_list_sets,
    list_sets,
    remove_list_set,
    set_list_set_difficulty,
)
from cairn.services.tunes import (
    COLUMN_PREVIEW_N_BARS,
    FAMILY_LABELS,
    POPUP_PREVIEW_N_BARS,
    TUNE_FAMILIES,
    TunePreview,
    list_tunes,
    preview_abc,
)
from cairn.templating import templates

router = APIRouter(prefix="/lists", tags=["lists"])

_LIST_TYPES = list(PracticeListType)
_PROGRESS_STATUSES = [s for s in ProgressStatus if s != ProgressStatus.just_learning]
_KEY_ROOTS = list(KeyRoot)
_FAMILY_FOR_TYPE: dict[str, str] = {t.value: family for family, types in TUNE_FAMILIES.items() for t in types}


async def _get_owned_list(db: AsyncSession, user_id: int, list_id: int) -> PracticeList:
    """Fetch a practice list the user owns, or 404 — a missing row and an owner
    mismatch look identical to the caller so another user's list's existence
    isn't revealed.

    Deliberately a plain PK fetch (db.get), not get_list()'s eager-loaded
    version: pre-loading entries.display_alias/setting here, before a mutation
    on one of those same entries, would cache their pre-mutation state in the
    identity map — expire_on_commit=False never refreshes it, so the mutation
    would appear to silently not take effect on the response that follows.
    Callers that need the full detail object (entries, box, etc.) fetch it
    themselves via get_list() after this check.
    """
    practice_list = await db.get(PracticeList, list_id)
    if practice_list is None or practice_list.user_id != user_id:
        raise HTTPException(status_code=404, detail="List not found")
    return practice_list


def _entry_previews(entries) -> dict[int, TunePreview]:
    """Map tune id -> (column snippet, popup preview) for list entries, preferring
    each entry's chosen setting (#164 — replaces the single 4-bar preview).

    Both previews are notes-only (#164) — no T: header, so unlike the row's
    own title the entry's display alias (#119) has no effect here. Applies
    the entry's saved transpose (#158), if any, so the preview matches what
    practice will show.

    Both also drop transpose_abc()'s own "(transposed +N semitones)" Z:
    annotation — the row already shows the transposed key next to the title,
    so the text annotation is redundant in either preview. transpose_abc()
    runs after the initial notes_only strip inside preview_abc() (it needs
    the untransposed ABC as input), so it's stripped again here to catch the
    Z: line transpose_abc() itself adds.

    The column snippet additionally strips quoted chord symbols ("G", "Am",
    etc.) from the music body — ABCJS renders those well above the staff,
    which reads as a disconnected floating letter in a box this small. The
    popup keeps them; there's enough room there for them to read normally.
    """
    previews: dict[int, TunePreview] = {}
    for entry in entries:
        popup = preview_abc(entry.tune, entry.setting, n_bars=POPUP_PREVIEW_N_BARS, notes_only=True)
        if popup is not None:
            semitones = transpose_semitones_for(entry.tune.key_root, entry.transpose_key_root, entry.transpose_octave)
            if semitones:
                popup = strip_decorative_headers(transpose_abc(popup, semitones))
            column = strip_chord_symbols(truncate_to_bars(popup, COLUMN_PREVIEW_N_BARS))
            previews[entry.tune_id] = TunePreview(column=column, popup=popup)
    return previews


async def _set_difficulties(db: AsyncSession, box, list_sets_) -> dict[int, tuple[int | None, bool]]:
    """Map set id -> (effective difficulty, is_override) for a list's linked sets.

    The default is computed against the list's own parent box's instruments
    (PracticeList.box_id is NOT NULL — a list has no independent instrument
    concept of its own), recomputed fresh each time rather than cached.
    """
    result: dict[int, tuple[int | None, bool]] = {}
    for entry in list_sets_:
        override = await get_list_set_difficulty_override(db, entry.list_id, entry.set_id)
        if override is not None:
            result[entry.set_id] = (override, True)
        elif box is not None:
            result[entry.set_id] = (compute_default_set_difficulty(box, entry.tune_set), False)
        else:
            result[entry.set_id] = (None, False)
    return result


def _transpose_popup_ctx(entry, key_root: KeyRoot | None, octave: int, action_url: str, modal_id: str) -> dict:
    tune = entry.tune
    display_name = entry.display_alias.name if entry.display_alias else None
    preview = preview_abc(tune, entry.setting, display_name=display_name)
    semitones = transpose_semitones_for(tune.key_root, key_root, octave)
    if preview is not None and semitones:
        preview = transpose_abc(preview, semitones)
    return {
        "tune": tune,
        "entry": entry,
        "key_options": [
            (root.value, f"{root.label} {tune.key_mode.label}")
            for root in reversed(_KEY_ROOTS)
            if root != tune.key_root
        ],
        "selected_key": key_root.value if key_root else "",
        "octave": octave,
        "preview_abc": preview,
        "action_url": action_url,
        "modal_id": modal_id,
        "row_target_id": f"entry-row-{entry.tune_id}",
    }


@router.get("/")
async def list_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    practice_lists = await list_lists(db, user.id)
    return templates.TemplateResponse(
        request,
        "lists/index.html",
        {"practice_lists": practice_lists},
    )


@router.get("/new")
async def list_new(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    boxes = await list_boxes(db, user.id)
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
    user: User = Depends(get_current_user),
    name: str = Form(...),
    list_type: PracticeListType = Form(...),
    box_id: int = Form(...),
    progress_goal: ProgressStatus = Form(default=ProgressStatus.committed),
    target_date: str = Form(default=""),
) -> Response:
    from datetime import date

    box = await get_box_detail(db, box_id)
    if box is None or box.user_id != user.id:
        raise HTTPException(status_code=404, detail="Box not found")

    parsed_date = date.fromisoformat(target_date) if target_date else None
    practice_list = await create_list(
        db,
        user.id,
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
    user: User = Depends(get_current_user),
) -> Response:
    practice_list = await get_list(db, list_id)
    if practice_list is None or practice_list.user_id != user.id:
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
    user: User = Depends(get_current_user),
    name: str = Form(...),
    list_type: PracticeListType = Form(...),
    progress_goal: ProgressStatus = Form(default=ProgressStatus.committed),
    target_date: str = Form(default=""),
) -> Response:
    from datetime import date

    await _get_owned_list(db, user.id, list_id)
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
    user: User = Depends(get_current_user),
) -> Response:
    practice_list = await get_list(db, list_id)
    if practice_list is None or practice_list.user_id != user.id:
        raise HTTPException(status_code=404, detail="List not found")
    entry_tune_ids = {e.tune_id for e in practice_list.entries}
    all_tunes = await list_tunes(db, user.id)
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
    aliases_by_tune_id = json.dumps({t.id: [{"id": a.id, "label": a.name} for a in t.aliases] for t in addable_tunes})
    box = await get_box_detail(db, practice_list.box_id)
    box_entries = box.entries if box else []
    box_setting_by_tune_id = json.dumps({e.tune_id: e.setting_id for e in box_entries if e.setting_id is not None})
    box_display_alias_by_tune_id = json.dumps(
        {e.tune_id: e.display_alias_id for e in box_entries if e.display_alias_id is not None}
    )
    box_tune_ids_json = json.dumps([e.tune_id for e in box_entries])
    tune_previews = _entry_previews(practice_list.entries)

    list_sets_ = await list_list_sets(db, list_id)
    linked_set_ids = {e.set_id for e in list_sets_}
    all_sets = await list_sets(db)
    addable_sets = [s for s in all_sets if s.id not in linked_set_ids]
    addable_sets_json = json.dumps([{"id": s.id, "label": f"{s.title} ({len(s.members)} tunes)"} for s in addable_sets])
    set_difficulties = await _set_difficulties(db, box, list_sets_)

    return templates.TemplateResponse(
        request,
        "lists/detail.html",
        {
            "practice_list": practice_list,
            "addable_tunes": addable_tunes,
            "addable_tunes_json": addable_tunes_json,
            "settings_by_tune_id": settings_by_tune_id,
            "aliases_by_tune_id": aliases_by_tune_id,
            "box_setting_by_tune_id": box_setting_by_tune_id,
            "box_display_alias_by_tune_id": box_display_alias_by_tune_id,
            "box_tune_ids_json": box_tune_ids_json,
            "box_name": box.name if box else "",
            "family_labels": FAMILY_LABELS,
            "family_for_type": _FAMILY_FOR_TYPE,
            "tune_previews": tune_previews,
            "list_sets": list_sets_,
            "addable_sets": addable_sets,
            "addable_sets_json": addable_sets_json,
            "set_difficulties": set_difficulties,
        },
    )


@router.post("/{list_id}/sets")
async def list_add_set(
    request: Request,
    list_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    set_id: int = Form(...),
) -> Response:
    practice_list = await _get_owned_list(db, user.id, list_id)
    try:
        await add_list_set(db, list_id, set_id)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Set already in list") from exc
    box = await get_box_detail(db, practice_list.box_id)
    list_sets_ = await list_list_sets(db, list_id)
    entry = next(e for e in list_sets_ if e.set_id == set_id)
    set_difficulties = await _set_difficulties(db, box, [entry])
    return templates.TemplateResponse(
        request,
        "lists/partials/_set_row.html",
        {"list_id": list_id, "entry": entry, "set_difficulties": set_difficulties},
    )


@router.delete("/{list_id}/sets/{set_id}")
async def list_remove_set(
    list_id: int,
    set_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    await _get_owned_list(db, user.id, list_id)
    removed = await remove_list_set(db, list_id, set_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Set not in list")
    return Response(status_code=200)


@router.post("/{list_id}/sets/{set_id}/difficulty")
async def list_set_set_difficulty(
    request: Request,
    list_id: int,
    set_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    difficulty: int = Form(...),
) -> Response:
    await _get_owned_list(db, user.id, list_id)
    await set_list_set_difficulty(db, list_id, set_id, difficulty)
    return templates.TemplateResponse(
        request,
        "lists/partials/_set_difficulty.html",
        {"list_id": list_id, "set_id": set_id, "difficulty": difficulty, "is_override": True},
    )


@router.post("/{list_id}/sets/{set_id}/difficulty/reset")
async def list_reset_set_difficulty(
    request: Request,
    list_id: int,
    set_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    practice_list = await _get_owned_list(db, user.id, list_id)
    box = await get_box_detail(db, practice_list.box_id)
    list_sets_ = await list_list_sets(db, list_id)
    entry = next((e for e in list_sets_ if e.set_id == set_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Set not in list")
    await clear_list_set_difficulty(db, list_id, set_id)
    difficulty = compute_default_set_difficulty(box, entry.tune_set) if box is not None else None
    return templates.TemplateResponse(
        request,
        "lists/partials/_set_difficulty.html",
        {"list_id": list_id, "set_id": set_id, "difficulty": difficulty, "is_override": False},
    )


@router.post("/{list_id}/activate")
async def list_activate(
    request: Request,
    list_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    practice_list = await activate_list(db, user.id, list_id)
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
    user: User = Depends(get_current_user),
) -> Response:
    practice_list = await _get_owned_list(db, user.id, list_id)
    await deactivate_list(db, user.id)
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
    user: User = Depends(get_current_user),
    tune_id: int = Form(...),
    setting_id: str = Form(default=""),
    display_alias_id: str = Form(default=""),
) -> Response:
    await _get_owned_list(db, user.id, list_id)
    parsed_setting_id = int(setting_id) if setting_id else None
    parsed_display_alias_id = int(display_alias_id) if display_alias_id else None
    try:
        await add_tune_to_list(
            db,
            list_id,
            tune_id,
            setting_id=parsed_setting_id,
            display_alias_id=parsed_display_alias_id,
        )
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
    user: User = Depends(get_current_user),
    setting_id: str = Form(default=""),
) -> Response:
    await _get_owned_list(db, user.id, list_id)
    sid = int(setting_id) if setting_id else None
    entry = await update_list_entry_setting(db, list_id, tune_id, sid)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return templates.TemplateResponse(
        request,
        "lists/partials/_entry_row.html",
        {"entry": entry, "list_id": list_id, "tune_previews": _entry_previews([entry])},
    )


@router.post("/{list_id}/tunes/{tune_id}/display-alias")
async def list_set_entry_display_alias(
    request: Request,
    list_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    display_alias_id: str = Form(default=""),
) -> Response:
    await _get_owned_list(db, user.id, list_id)
    daid = int(display_alias_id) if display_alias_id else None
    entry = await update_list_entry_display_alias(db, list_id, tune_id, daid)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return templates.TemplateResponse(
        request,
        "lists/partials/_entry_row.html",
        {"entry": entry, "list_id": list_id, "tune_previews": _entry_previews([entry])},
    )


@router.get("/{list_id}/tunes/{tune_id}/transpose")
async def list_transpose_popup(
    request: Request,
    list_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    key_root: str | None = Query(default=None),
    octave: str | None = Query(default=None),
) -> Response:
    await _get_owned_list(db, user.id, list_id)
    entry = await get_list_entry(db, list_id, tune_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    if key_root is None and octave is None:
        pending_key, pending_octave = entry.transpose_key_root, entry.transpose_octave
    else:
        pending_key = KeyRoot(key_root) if key_root else None
        pending_octave = int(octave) if octave else 0

    ctx = _transpose_popup_ctx(
        entry, pending_key, pending_octave, f"/lists/{list_id}/tunes/{tune_id}/transpose", "list-transpose-modal"
    )
    return templates.TemplateResponse(request, "components/_transpose_popup.html", ctx)


@router.post("/{list_id}/tunes/{tune_id}/transpose")
async def list_set_entry_transpose(
    request: Request,
    list_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    key_root: str = Form(default=""),
    octave: str = Form(default="0"),
) -> Response:
    await _get_owned_list(db, user.id, list_id)
    kr = KeyRoot(key_root) if key_root else None
    oc = int(octave) if octave else 0
    entry = await update_list_entry_transpose(db, list_id, tune_id, kr, oc)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    row_html = templates.env.get_template("lists/partials/_entry_row.html").render(
        {"entry": entry, "list_id": list_id, "tune_previews": _entry_previews([entry])}
    )
    return Response(
        content=row_html + '<div id="list-transpose-modal" hx-swap-oob="true"></div>', media_type="text/html"
    )


@router.delete("/{list_id}")
async def list_delete(
    list_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    await _get_owned_list(db, user.id, list_id)
    deleted = await delete_list(db, list_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="List not found")
    return Response(status_code=200, headers={"HX-Redirect": "/lists"})


@router.delete("/{list_id}/tunes/{tune_id}")
async def list_remove_tune(
    list_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    await _get_owned_list(db, user.id, list_id)
    removed = await remove_tune_from_list(db, list_id, tune_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Tune not in list")
    return Response(status_code=200)
