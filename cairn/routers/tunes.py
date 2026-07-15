from typing import NamedTuple

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_current_user, get_db
from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, TempoRecord, Tune, TuneType, User
from cairn.schemas import TuneCreate, TuneUpdate
from cairn.services.abc_utils import KEY_ROOT_MAP, build_abc, shortest_semitones_to_root, transpose_abc
from cairn.services.boxes import add_tune, get_box, get_box_entry, list_boxes, set_display_alias, set_preferred_setting
from cairn.services.lists import add_tune_to_list, get_active_list, get_list, get_list_entry, list_lists
from cairn.services.tune_sets import list_sets_for_tune
from cairn.services.tunes import (
    FAMILY_LABELS,
    add_alias,
    build_tune_previews,
    core_setting,
    create_tune,
    delete_tune,
    get_tempo_history,
    get_tune,
    list_tunes,
    record_tempo,
    remove_alias,
    resolve_display_context,
    update_tune,
)
from cairn.templating import templates

router = APIRouter(prefix="/tunes", tags=["tunes"])

_TUNE_TYPES = list(TuneType)
_KEY_ROOTS = list(KeyRoot)
_KEY_MODES = list(KeyMode)
_INSTRUMENTS = list(Instrument)
_ORN_LEVELS = list(OrnamentationLevel)

_FORM_CTX = {"tune_types": _TUNE_TYPES, "key_roots": _KEY_ROOTS, "key_modes": _KEY_MODES}
_SETTINGS_CTX = {"instruments": _INSTRUMENTS, "orn_levels": _ORN_LEVELS}


class TempoChartPoint(NamedTuple):
    x: float
    y: float
    tempo: int
    label: str  # friendly date/time, e.g. "Jul 10, 02:30 PM"


class TempoChart(NamedTuple):
    width: int
    height: int
    points: list[TempoChartPoint]
    polyline: str  # "x1,y1 x2,y2 ..." for <polyline points="...">


_CHART_WIDTH = 560
_CHART_HEIGHT = 140
_CHART_PAD_X = 16
_CHART_PAD_TOP = 44  # extra headroom so the hover tooltip never needs per-point clamping
_CHART_PAD_BOTTOM = 20


def _build_tempo_chart(tempo_records: list[TempoRecord]) -> TempoChart | None:
    """Map tempo readings (oldest first) to SVG pixel coordinates for #182's trend graph.

    x is evenly spaced by reading order, not actual elapsed time. Several
    readings logged within one practice session (working a passage up from
    one setting to a faster one) would otherwise all crowd into a sliver of
    the axis whenever the history also spans weeks/months — the trend is
    the point, not real-time spacing. The actual timestamp is still shown
    in each point's tooltip, so nothing is lost.
    """
    if not tempo_records:
        return None
    tempos = [r.tempo for r in tempo_records]
    t_range = (max(tempos) - min(tempos)) or 1
    plot_w = _CHART_WIDTH - 2 * _CHART_PAD_X
    plot_h = _CHART_HEIGHT - _CHART_PAD_TOP - _CHART_PAD_BOTTOM
    n = len(tempo_records)

    points = []
    for i, record in enumerate(tempo_records):
        x_frac = 0.5 if n == 1 else i / (n - 1)
        y_frac = (record.tempo - min(tempos)) / t_range
        x = _CHART_PAD_X + x_frac * plot_w
        y = _CHART_HEIGHT - _CHART_PAD_BOTTOM - y_frac * plot_h
        points.append(
            TempoChartPoint(
                x=round(x, 1),
                y=round(y, 1),
                tempo=record.tempo,
                label=record.created_at.strftime("%b %d, %I:%M %p"),
            )
        )
    polyline = " ".join(f"{p.x},{p.y}" for p in points)
    return TempoChart(width=_CHART_WIDTH, height=_CHART_HEIGHT, points=points, polyline=polyline)


@router.get("/new")
async def tune_new(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "tunes/form.html",
        {"tune": None, "core_abc": "", **_FORM_CTX},
    )


@router.get("/")
async def tune_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tune_type: TuneType | None = Query(default=None, alias="type"),
    family: str | None = None,
) -> Response:
    tunes = await list_tunes(db, tune_type=tune_type, family=family)
    tune_previews = build_tune_previews(tunes)
    ctx = {
        "tunes": tunes,
        "tune_types": _TUNE_TYPES,
        "family_labels": FAMILY_LABELS,
        "active_type": tune_type,
        "active_family": family,
        "tune_previews": tune_previews,
    }
    template = "tunes/partials/_tune_list.html" if request.headers.get("HX-Request") else "tunes/index.html"
    return templates.TemplateResponse(request, template, ctx)


@router.post("/")
async def tune_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    tune_type: TuneType = Form(...),
    key_root: KeyRoot = Form(...),
    key_mode: KeyMode = Form(...),
    time_signature: str = Form(...),
    abc_notation: str = Form(...),
    origin: str | None = Form(None),
    region: str | None = Form(None),
    notes: str | None = Form(None),
) -> Response:
    tune_in = TuneCreate(
        title=title,
        tune_type=tune_type,
        key_root=key_root,
        key_mode=key_mode,
        time_signature=time_signature,
        origin=origin or None,
        region=region or None,
        notes=notes or None,
    )
    tune = await create_tune(db, tune_in, abc_notation=abc_notation)
    return RedirectResponse(f"/tunes/{tune.id}", status_code=303)


@router.get("/{tune_id}")
async def tune_detail(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    box_id: int | None = Query(default=None),
    list_id: int | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
    key: str | None = Query(default=None),
    octave: int | None = Query(default=None),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")

    # Progress is not a setting-override source the way a box or list entry
    # is (see #120) — it only ever affects the breadcrumb, and only when
    # nothing more specific (list, then box) is already provided.
    from_progress = from_ == "progress"

    # View-time only (#122) — never persisted. `key` picks a target root (the
    # tune's own mode always carries over — transpose_abc() never changes it)
    # and is converted to the shortest-route semitone shift; `octave` is a
    # separate +/-1-octave nudge on top of that (there's rarely a need for
    # more range than that in trad tunes), since an exact tritone target is a
    # genuine tie in pitch-class terms but still lands a full octave apart
    # depending on direction — see shortest_semitones_to_root().
    target_root = KEY_ROOT_MAP.get(key.lower()) if key else None
    key_shift = shortest_semitones_to_root(tune.key_root, target_root) if target_root else 0
    octave = max(-1, min(1, octave or 0))
    transpose = key_shift + octave * 12

    # box_id/list_id are just view-context (which box/list's setting, alias,
    # transpose to show) — dropped silently rather than 404ing the whole tune
    # page if they don't belong to the current user (a stale link, or a
    # crafted query param), so the tune itself still renders.
    box = None
    entry = None
    if box_id is not None:
        box = await get_box(db, box_id)
        if box is not None and box.user_id == user.id:
            entry = await get_box_entry(db, box_id, tune_id)
        else:
            box, box_id = None, None

    linked_list = None
    list_entry = None
    if list_id is not None:
        linked_list = await get_list(db, list_id)
        if linked_list is not None and linked_list.user_id == user.id:
            list_entry = await get_list_entry(db, list_id, tune_id)
        else:
            linked_list, list_id = None, None

    active_setting, display_name = resolve_display_context(tune, entry, list_entry)
    core = core_setting(tune)

    built_abc = build_abc(tune, active_setting, display_name=display_name) if active_setting else ""
    settings_abc = {s.id: build_abc(tune, s, display_name=display_name) for s in tune.settings}
    if transpose:
        built_abc = transpose_abc(built_abc, transpose)
        settings_abc = {sid: transpose_abc(abc, transpose) for sid, abc in settings_abc.items()}
    min_tempo, tempo_records = await get_tempo_history(db, user.id, tune_id)
    beats_per_bar = int(tune.time_signature.split("/")[0])

    boxes = await list_boxes(db, user.id)
    box_entries = {b.id: next((e for e in b.entries if e.tune_id == tune_id), None) for b in boxes}
    lists_by_box_id: dict[int, list] = {}
    for practice_list in await list_lists(db, user.id):
        lists_by_box_id.setdefault(practice_list.box_id, []).append(practice_list)
    active_list = await get_active_list(db, user.id)
    member_sets = await list_sets_for_tune(db, tune_id)

    # Base query string (box/list/breadcrumb context only) so the key picker
    # and octave controls can each change just their own param(s) without
    # dropping the others (#122).
    other_params = []
    if box_id is not None:
        other_params.append(f"box_id={box_id}")
    if list_id is not None:
        other_params.append(f"list_id={list_id}")
    if from_:
        other_params.append(f"from={from_}")
    base_qs_prefix = "&".join(other_params) + ("&" if other_params else "")

    selected_key = target_root.value if target_root else tune.key_root.value
    key_param = f"key={selected_key}&" if key_shift else ""
    # Listed highest root first (descending) so scrolling toward the top of
    # the dropdown moves to higher keys, matching the score's up/down sense.
    key_options = [
        (root.value, f"{root.label} {tune.key_mode.label}", f"?{base_qs_prefix}key={root.value}&octave={octave}")
        for root in reversed(_KEY_ROOTS)
    ]
    octave_up_href = f"?{base_qs_prefix}{key_param}octave={0 if octave == 1 else 1}"
    octave_down_href = f"?{base_qs_prefix}{key_param}octave={0 if octave == -1 else -1}"
    reset_href = f"?{base_qs_prefix}octave=0" if (key_shift or octave) else None

    return templates.TemplateResponse(
        request,
        "tunes/detail.html",
        {
            "tune": tune,
            "display_name": display_name,
            "member_sets": member_sets,
            "built_abc": built_abc,
            "settings_abc": settings_abc,
            "active_setting_id": active_setting.id if active_setting else None,
            "thesession_setting_anchor_id": core.thesession_setting_id if core else None,
            "box": box,
            "box_id": box_id,
            "linked_list": linked_list,
            "list_id": list_id,
            "from_progress": from_progress,
            "selected_key": selected_key,
            "key_options": key_options,
            "octave": octave,
            "octave_up_href": octave_up_href,
            "octave_down_href": octave_down_href,
            "reset_href": reset_href,
            "min_tempo": min_tempo,
            "tempo_records": tempo_records,
            "chart": _build_tempo_chart(tempo_records),
            "last_tempo": tempo_records[-1].tempo if tempo_records else None,
            "beats_per_bar": beats_per_bar,
            "boxes": boxes,
            "box_entries": box_entries,
            "non_core_settings": [s for s in tune.settings if not s.is_core],
            "lists_by_box_id": lists_by_box_id,
            "active_list_id": active_list.id if active_list else None,
            **_SETTINGS_CTX,
        },
    )


async def _get_owned_box(db: AsyncSession, user_id: int, box_id: int):
    box = await get_box(db, box_id)
    if box is None or box.user_id != user_id:
        raise HTTPException(status_code=404, detail="Box not found")
    return box


async def _box_membership_context(db: AsyncSession, user_id: int, tune: Tune, box_id: int) -> dict:
    box = await _get_owned_box(db, user_id, box_id)
    entry = await get_box_entry(db, box_id, tune.id)
    lists_for_box = [pl for pl in await list_lists(db, user_id) if pl.box_id == box_id]
    active_list = await get_active_list(db, user_id)
    return {
        "tune": tune,
        "box": box,
        "entry": entry,
        "non_core_settings": [s for s in tune.settings if not s.is_core],
        "lists_for_box": lists_for_box,
        "active_list_id": active_list.id if active_list else None,
    }


@router.post("/{tune_id}/boxes")
async def tune_add_to_box(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    box_id: int = Form(...),
    setting_id: str = Form(default=""),
    display_alias_id: str = Form(default=""),
    list_id: str = Form(default=""),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    await _get_owned_box(db, user.id, box_id)

    sid = int(setting_id) if setting_id else None
    daid = int(display_alias_id) if display_alias_id else None
    try:
        # display_alias_id has no auto-pick heuristic (unlike setting_id, see
        # below) so it's passed straight into add_tune() rather than needing
        # a follow-up call to override anything.
        await add_tune(db, box_id, tune_id, display_alias_id=daid)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Tune already in box") from exc
    # add_tune() may have auto-picked a setting via its own instrument-matching
    # heuristic; the user's explicit choice (including "Core setting") always
    # takes precedence, so this runs unconditionally rather than only when sid
    # is not None.
    await set_preferred_setting(db, box_id, tune_id, sid)

    if list_id:
        target_list = await get_list(db, int(list_id))
        if target_list is not None and target_list.user_id == user.id:
            try:
                await add_tune_to_list(db, int(list_id), tune_id, setting_id=sid, display_alias_id=daid)
            except IntegrityError:
                pass  # already in that list — the box add still succeeded

    ctx = await _box_membership_context(db, user.id, tune, box_id)
    return templates.TemplateResponse(request, "tunes/partials/_box_membership_row.html", ctx)


@router.post("/{tune_id}/boxes/{box_id}/setting")
async def tune_update_box_setting(
    request: Request,
    tune_id: int,
    box_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    setting_id: str = Form(default=""),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    await _get_owned_box(db, user.id, box_id)
    if await get_box_entry(db, box_id, tune_id) is None:
        raise HTTPException(status_code=404, detail="Tune not in box")

    sid = int(setting_id) if setting_id else None
    await set_preferred_setting(db, box_id, tune_id, sid)

    ctx = await _box_membership_context(db, user.id, tune, box_id)
    return templates.TemplateResponse(request, "tunes/partials/_box_membership_row.html", ctx)


@router.post("/{tune_id}/boxes/{box_id}/display-alias")
async def tune_update_box_display_alias(
    request: Request,
    tune_id: int,
    box_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    display_alias_id: str = Form(default=""),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    await _get_owned_box(db, user.id, box_id)
    if await get_box_entry(db, box_id, tune_id) is None:
        raise HTTPException(status_code=404, detail="Tune not in box")

    daid = int(display_alias_id) if display_alias_id else None
    await set_display_alias(db, box_id, tune_id, daid)

    ctx = await _box_membership_context(db, user.id, tune, box_id)
    return templates.TemplateResponse(request, "tunes/partials/_box_membership_row.html", ctx)


@router.post("/{tune_id}/tempo")
async def tempo_record_create(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tempo: int = Form(...),
    box_id: int | None = Form(None),
) -> Response:
    await record_tempo(db, user.id, tune_id, box_id, tempo)
    min_tempo, tempo_records = await get_tempo_history(db, user.id, tune_id)
    return templates.TemplateResponse(
        request,
        "tunes/partials/_tempo_history.html",
        {"min_tempo": min_tempo, "tempo_records": tempo_records, "chart": _build_tempo_chart(tempo_records)},
    )


@router.get("/{tune_id}/tempo-history")
async def tempo_history_partial(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    min_tempo, tempo_records = await get_tempo_history(db, user.id, tune_id)
    return templates.TemplateResponse(
        request,
        "tunes/partials/_tempo_history.html",
        {"min_tempo": min_tempo, "tempo_records": tempo_records, "chart": _build_tempo_chart(tempo_records)},
    )


@router.get("/{tune_id}/edit")
async def tune_edit(request: Request, tune_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    core = core_setting(tune)
    core_abc = core.abc_notation if core else ""
    return templates.TemplateResponse(
        request,
        "tunes/form.html",
        {"tune": tune, "core_abc": core_abc, **_FORM_CTX},
    )


@router.post("/{tune_id}")
async def tune_update(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    tune_type: TuneType = Form(...),
    key_root: KeyRoot = Form(...),
    key_mode: KeyMode = Form(...),
    time_signature: str = Form(...),
    abc_notation: str | None = Form(None),
    origin: str | None = Form(None),
    region: str | None = Form(None),
    notes: str | None = Form(None),
) -> Response:
    tune_in = TuneUpdate(
        title=title,
        tune_type=tune_type,
        key_root=key_root,
        key_mode=key_mode,
        time_signature=time_signature,
        origin=origin or None,
        region=region or None,
        notes=notes or None,
    )
    tune = await update_tune(db, tune_id, tune_in, abc_notation=abc_notation or None)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    return RedirectResponse(f"/tunes/{tune.id}", status_code=303)


@router.delete("/{tune_id}")
async def tune_delete(tune_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    deleted = await delete_tune(db, tune_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tune not found")
    return Response(status_code=200)


@router.post("/{tune_id}/aliases")
async def alias_add(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    notes: str = Form(default=""),
) -> Response:
    alias = await add_alias(db, tune_id, name, notes or None)
    if alias is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    tune = await get_tune(db, tune_id)
    return templates.TemplateResponse(request, "tunes/partials/_aliases.html", {"tune": tune})


@router.delete("/{tune_id}/aliases/{alias_id}")
async def alias_remove(
    request: Request,
    tune_id: int,
    alias_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    removed = await remove_alias(db, alias_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Alias not found")
    tune = await get_tune(db, tune_id)
    return templates.TemplateResponse(request, "tunes/partials/_aliases.html", {"tune": tune})
