import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import Instrument, KeyRoot, TuneType
from cairn.services.abc_utils import (
    strip_chord_symbols,
    strip_decorative_headers,
    transpose_abc,
    transpose_semitones_for,
    truncate_to_bars,
)
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
    set_transpose,
)
from cairn.services.lists import bulk_update_list_entry_setting, find_list_entries_by_setting
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/boxes", tags=["boxes"])

_STUB_USER_ID = 1
_INSTRUMENTS = list(Instrument)
_TUNE_TYPES = list(TuneType)
_KEY_ROOTS = list(KeyRoot)
_FAMILY_FOR_TYPE: dict[str, str] = {t.value: family for family, types in TUNE_FAMILIES.items() for t in types}


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
        "row_target_id": f"box-tune-{entry.tune_id}",
    }


def _entry_previews(entries) -> dict[int, TunePreview]:
    """Map tune id -> (column snippet, popup preview) for box entries, preferring
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


@router.get("/{box_id}/tunes/{tune_id}/transpose")
async def box_transpose_popup(
    request: Request,
    box_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    key_root: str | None = Query(default=None),
    octave: str | None = Query(default=None),
) -> Response:
    entry = await get_box_entry(db, box_id, tune_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Tune not in box")

    if key_root is None and octave is None:
        pending_key, pending_octave = entry.transpose_key_root, entry.transpose_octave
    else:
        pending_key = KeyRoot(key_root) if key_root else None
        pending_octave = int(octave) if octave else 0

    ctx = _transpose_popup_ctx(
        entry, pending_key, pending_octave, f"/boxes/{box_id}/tunes/{tune_id}/transpose", "box-transpose-modal"
    )
    return templates.TemplateResponse(request, "components/_transpose_popup.html", ctx)


@router.post("/{box_id}/tunes/{tune_id}/transpose")
async def box_set_transpose(
    request: Request,
    box_id: int,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    key_root: str = Form(default=""),
    octave: str = Form(default="0"),
) -> Response:
    if await get_box_entry(db, box_id, tune_id) is None:
        raise HTTPException(status_code=404, detail="Tune not in box")

    kr = KeyRoot(key_root) if key_root else None
    oc = int(octave) if octave else 0
    await set_transpose(db, box_id, tune_id, kr, oc)
    entry = await get_box_entry(db, box_id, tune_id)
    row_html = templates.env.get_template("boxes/partials/_tune_row.html").render(
        {"entry": entry, "box_id": box_id, "tune_previews": _entry_previews([entry])}
    )
    return Response(
        content=row_html + '<div id="box-transpose-modal" hx-swap-oob="true"></div>', media_type="text/html"
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
