# TODO.md — The Cairn

Task list for Phase 1. Each task is scoped to be handed to an agent in a single session.
Complete tasks in order — later tasks depend on earlier ones.

Mark tasks: `[ ]` not started · `[~]` in progress · `[x]` done

---

## Phase 1 — Solo Tool

### 0. Project Bootstrap

- [ ] **0.1 — Initialise project with uv**
  Create `pyproject.toml` with all Phase 1 dependencies. Initialise a virtual environment.
  Dependencies: `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `aiosqlite`,
  `alembic`, `jinja2`, `python-multipart`, `pydantic`, `pytest`, `pytest-asyncio`, `httpx`, `ruff`.

- [ ] **0.2 — Create Makefile**
  Targets: `dev`, `test`, `migrate`, `migration`, `shell`, `lint`, `fmt`.
  See AGENTS.md for expected behaviour of each target.

- [ ] **0.3 — FastAPI app skeleton**
  Create `cairn/main.py` (app factory, router mounts, static files, Jinja2).
  Create `cairn/database.py` (async engine, `AsyncSession` factory, `Base`, `TimestampMixin`).
  Create `cairn/dependencies.py` (`get_db` dependency).
  App must start with `make dev` and return 200 on `GET /`.
  Run `alembic init alembic` and configure `env.py` for async SQLAlchemy
  Verify `alembic/versions/` directory exists before considering complete

- [x] **0.4 — Base template**
  Create `cairn/templates/base.html`.
  Must load via CDN: Tailwind CSS, HTMX, Alpine.js, abcjs (pin versions).
  Include a minimal nav placeholder and a `{% block content %}` area.

---

### 1. Core Data Models

- [x] **1.1 — Enums**
  Define all enums in `cairn/models.py`:
  `TuneType`, `Instrument`, `ProgressStatus`, `OrnamentationLevel`, `WarmupType`.
  All must be `str, enum.Enum` with a `.label` property.
  Refer to AGENTS.md for the full `ProgressStatus` value list.

- [x] **1.2 — Tune and TuneSetting models**
  `Tune`: id, title, tune_type, key, time_signature, origin, region, notes, created_by.
  `TuneSetting`: id, tune_id FK, label, abc_notation, is_core, ornamentation_level, source_notes.
  `TuneDifficulty`: id, tune_id FK, instrument, difficulty (1–5), notes.
  Include relationships and `TimestampMixin`.
  Generate Alembic migration.

- [x] **1.3 — WarmupItem model**
  Fields: id, title, warmup_type, content, instrument (nullable), difficulty.
  Generate Alembic migration.

- [x] **1.4 — TuneSet and TuneSetMember models**
  `TuneSet`: id, title, description, flow_difficulty (nullable int 1–5),
  flow_difficulty_notes (nullable text).
  `TuneSetMember`: id, set_id FK, tune_id FK, order (int, explicit position).
  No maximum length on set membership.
  `peak_difficulty` is never stored — always derived as MAX of member difficulties.
  Generate Alembic migration.

- [x] **1.5 — User model (stub)**
  Fields: id, username, email, hashed_password, role (enum: guest | student | teacher | admin),
  primary_instrument.
  No auth logic yet — model only.
  Generate Alembic migration.
  Note: `guest` role represents unauthenticated visitors and is defined in the
  enum for use in authorization logic only. Guests are never stored in the
  `users` table. All other roles require a user record.

- [x] **1.5b — ContentVisibility enum**
  Add `ContentVisibility` enum to `models.py`:
  values: `public`, `enrolled`, `private`.
  With `.label` property per convention.
  No migration needed yet — enum is defined but not attached to any model until Phase 4.

- [x] **1.6 — StudentProgress model**
  Fields: id, user_id FK, tune_id FK, status (ProgressStatus), confidence (int 1–5),
  interval_days (float), ease_factor (float, default 2.5), last_practiced (datetime nullable),
  next_suggested (datetime nullable), teacher_approved (bool, default False).
  Generate Alembic migration.

- [x] **1.7 — PracticeSession and PracticeSessionItem models**
  `PracticeSession`: id, user_id FK, started_at, ended_at (nullable), total_minutes (nullable).
  `PracticeSessionItem`: id, session_id FK, item_type (enum: warmup | learning | retention),
  tune_id FK (nullable), warmup_id FK (nullable), minutes_allocated, completed (bool),
  rating_given (int nullable).
  Generate Alembic migration.

- [x] **1.8 — Pydantic schemas**
  Create `cairn/schemas.py` with `Create`, `Update`, and `Read` schemas for:
  `Tune`, `TuneSetting`, `TuneDifficulty`, `TuneSet`, `TuneSetMember`,
  `StudentProgress`, `WarmupItem`.
  All `Read` schemas must include `id` and `created_at`.


- [x] **1.9 — Apply all migrations**
  Run `make migrate`. Verify `cairn.db` is created and all tables exist.
  Write a smoke test in `tests/test_models.py` that creates one instance of each
  model and commits it.

---

### 2. Tune Management

- [x] **2.1 — Tune CRUD service**
  Create `cairn/services/tunes.py`.
  Functions: `create_tune`, `get_tune`, `list_tunes`, `update_tune`, `delete_tune`.
  `create_tune` must also create a core `TuneSetting` (is_core=True) in the same transaction.
  Enforce the invariant: a tune must always have exactly one `is_core=True` setting.
  Write tests in `tests/test_services/test_tunes.py`.

- [x] **2.2 — Tune routes and templates**
  Router: `cairn/routers/tunes.py`, prefix `/tunes`.
  Routes:
  - `GET /tunes` — list all tunes → `tunes/index.html`
  - `GET /tunes/new` — blank form → `tunes/form.html`
  - `POST /tunes` — create tune + core setting → redirect to tune detail
  - `GET /tunes/{id}` — tune detail with settings list → `tunes/detail.html`
  - `GET /tunes/{id}/edit` — edit form → `tunes/form.html`
  - `POST /tunes/{id}` — update tune
  - `DELETE /tunes/{id}` — delete (HTMX, returns empty 200)

- [x] **2.2b — Split key field and add time signature defaults**
      Model, schema, service, and migration changes only.
      **Key root enum**
      Use the full chromatic set for `KeyRoot` including enharmonic equivalents:
      C, C#, Db, D, Eb, E, F, F#, Gb, G, Ab, A, Bb, B.
      Rationale: supports O'Neill's transcriptions at concert pitch and is
      required for the planned transposition feature. Enharmonic equivalents
      (C#/Db, F#/Gb, Ab) are included since ABC notation and music21 both
      handle them and we don't want to lose information from historical sources.
      The ABC `K:` declaration and the stored `key_root`/`key_mode` fields
      must always be kept in sync — enforce this in the tune service.
      UI form changes (HTMX auto-populate, dual dropdowns) are
      part of this task since the form at 2.2 needs updating anyway.
      Safe to drop existing `key` column — no production data exists.
      Delete `cairn.db` and re-run `make migrate` after generation
      rather than attempting an in-place migration on dev.

- [x] **2.2c — TuneSetting and Tune model additions**
  **Tune model**
  Add `composer` field (nullable):
    composer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    Maps to ABC notation's `C:` field — seed import script should extract
    it automatically. Many traditional tunes will have no known composer.

  **TuneSetting model**
  Add three fields:
    `instrument` (nullable) — identifies instrument-specific arrangements.
    Null means the setting is valid for all instruments:
      instrument: Mapped[Instrument | None] = mapped_column(
        Enum(Instrument), nullable=True
      )
    `source` (nullable) — the person, collection, festival class, or
    recording responsible for this particular setting. Distinct from
    `source_notes` which provides context. Examples: "Tommy Peoples",
    "Catskills Irish Arts Week 2019", "O'Neill's 1001":
        source: Mapped[str | None] = mapped_column(String(200), nullable=True)

  `mutation_notation` (nullable, format TBD) — placeholder for future
  variation and mutation annotation. Do not implement any rendering or
  parsing logic for this field. Store as raw text only. See Phase 3
  open design questions:
    mutation_notation: Mapped[str | None] = mapped_column(
      Text, nullable=True
        # Format TBD — see Phase 3 mutation notation design notes
        # Do not implement rendering until format is decided
    )

  **Domain rule update**
  The `is_core = True` invariant now reads:
  A tune has exactly one `is_core = True` setting where `instrument`
  is null — representing the traditional version for all instruments.
  Instrument-specific arrangements are non-core settings with
  `instrument` set explicitly. Enforce at service layer.

  **Display logic for instrument-specific settings**
  When rendering a tune for a specific instrument:
  1. Check for a non-core setting matching the user's instrument
  2. If found, display it by default with a note "showing [instrument] arrangement"
  3. Always keep the core setting accessible regardless
  Implement this logic in the tune service, not the route handler.

  **Update schemas**
  Add all new fields to `TuneCreate`, `TuneUpdate`, and `TuneRead`.
  Add `instrument` to `TuneSettingCreate`, `TuneSettingUpdate`,
  and `TuneSettingRead`.

  **Migration**
  Generate a single Alembic migration covering all changes above.
  Safe to delete `cairn.db` and re-run `make migrate` from scratch
  — no production data exists.

- [x] **2.3 — ABC notation display**
  On `tunes/detail.html`, render the core `TuneSetting.abc_notation` using abcjs.
  The rendered score and a basic audio playback button must be visible.
  Use a `<div id="abc-render">` target and initialise abcjs in `static/js/app.js`.

- [x] **2.3b — Build ABC headers from DB fields**
  Currently `TuneSetting.abc_notation` is expected to contain a complete ABC
  file including headers. Redesign so that `abc_notation` holds only the
  music body (notes) plus any optional user-supplied headers that are not
  covered by DB fields. Headers are assembled on the fly from the database.

  **Field-to-header mapping** (canonical order, K: always last):
    X:  → always 1 for a single tune (position in TuneSet once 2.4 is done)
    T:  → Tune.title
    C:  → Tune.composer                           (omit if null)
    O:  → Tune.origin                             (omit if null)
    A:  → Tune.region                             (omit if null)
    R:  → Tune.tune_type.value
    M:  → Tune.time_signature
    S:  → TuneSetting.source                      (omit if null)
    Z:  → TuneSetting.source_notes                (omit if null)
    N:  → Tune.notes                              (omit if null)
    N:  → "Arranged for {instrument.label}"       (omit if null; always after Tune.notes N:)
    K:  → key_root + mode suffix (e.g. "Ador", "D", "Gmix")

  Both N: lines may be present simultaneously when both Tune.notes and
  TuneSetting.instrument are set. Each appears on its own N: line.

  **User-supplied headers**
  Any line in `abc_notation` matching `^[A-Z]:` whose letter is not in the
  mapped set above is treated as a user-supplied header and inserted between
  the last N: line and K: in the output. `L:` is the primary expected example.
  Lines in `abc_notation` whose letter IS in the mapped set are silently
  dropped (DB value takes precedence).

  **`build_abc(tune, setting, x=1) -> str`**
  Create `cairn/services/abc_utils.py`.
  This function assembles the final ABC string from the mapping above.
  It is the only place in the codebase that produces ABC for rendering or
  export. The function must:
  1. Parse `setting.abc_notation` into user-supplied headers and music lines
  2. Build the DB-derived headers in canonical order
  3. Insert user-supplied headers between the last N: and K:
  4. Append the music lines
  Write unit tests in `tests/test_services/test_abc_utils.py` covering:
  - All DB fields populated
  - Nullable fields omitted correctly
  - L: in abc_notation is preserved
  - Headers in the mapped set inside abc_notation are dropped
  - K: is always the last header
  - Both N: lines present when both Tune.notes and instrument are set
  - Only one N: line when only one of the two is set

  **Remove `_sync_abc_key`**
  Delete `_sync_abc_key` and `_ABC_MODE_SUFFIX` from `cairn/services/tunes.py`.
  `create_tune` and `update_tune` no longer need to rewrite the ABC — the
  key is always built from the DB by `build_abc`. Remove the K: rewrite
  calls in both functions.

  **Rendering**
  Update `cairn/templates/tunes/detail.html` so the string inside
  `<template id="abc-source">` is the output of `build_abc(tune, core)`
  rather than `core.abc_notation` directly.

  **Form**
  Update `cairn/templates/tunes/form.html`:
  - Rename the textarea label from "ABC Notation" to "Music Notation"
  - Update the placeholder to show only notes plus an optional L: line,
    with a short hint listing which fields are auto-generated as headers
  - Remove the abc_notation textarea from the edit form — the notes body
    is set at creation and edited via the TuneSetting management routes
    added in task 2.4

  **No migration needed**
  Safe to delete `cairn.db` and re-run `make migrate` — no production data.
  Existing `abc_notation` values that contain full ABC headers will have
  those headers stripped by `build_abc` at render time.

- [x] **2.4 — TuneSetting management**
  Add routes under `/tunes/{id}/settings`:
  - `GET /tunes/{id}/settings/new` — form for adding a new setting (HTMX partial)
  - `POST /tunes/{id}/settings` — create setting
  - `POST /tunes/{id}/settings/{setting_id}/set-core` — promote to core
    (must demote existing core in same transaction)
  All responses are HTMX partials; no full page reload.

- [x] **2.5 — Tune difficulty ratings**
  Add routes under `/tunes/{id}/difficulty`:
  - `GET /tunes/{id}/difficulty` — show difficulty by instrument (HTMX partial)
  - `POST /tunes/{id}/difficulty` — set difficulty for an instrument
  Display using a simple 1–5 selector per instrument.

---

### 3. Progress Tracking

- [x] **3.1 — Spaced repetition service**
  Create `cairn/services/spaced_rep.py`.
  Implement `next_review(confidence, interval_days, ease_factor) -> (float, float)`
  using a simplified SM-2 variant.
  Implement `record_practice(db, user_id, tune_id, confidence) -> StudentProgress`.
  Write thorough tests in `tests/test_services/test_spaced_rep.py` covering
  all confidence values (1–5) and edge cases (first practice, reset on low confidence).

- [x] **3.2 — Progress routes**
  Router: `cairn/routers/progress.py`, prefix `/progress`.
  Routes:
  - `GET /progress` — all tunes with current status for the current user
  - `POST /progress/{tune_id}` — record a practice rating (HTMX, returns updated badge)
  - `POST /progress/{tune_id}/status` — manually advance or set status

- [x] **3.3 — Progress badge component**
  Create `cairn/templates/components/_progress_badge.html`.
  Displays `status.label` with a colour-coded indicator.
  Used on tune detail and practice session views.
  Must be renderable as a standalone HTMX partial.

- [x] **3.4 — Migrate StudentProgress to per-box**
  Add `box_id FK → tune_boxes.id` to `StudentProgress`.
  Change the unique constraint from `(user_id, tune_id)` to `(user_id, tune_id, box_id)`.
  Update all service functions that read or write `StudentProgress`:
  `record_practice`, `get_user_progress`, `set_status` in `spaced_rep.py`, and
  any callers in `cairn/routers/progress.py`.
  Update all affected tests in `tests/test_services/test_spaced_rep.py` and
  `tests/test_routers/test_progress.py` — fixtures must now create a TuneBox
  and pass `box_id` wherever a `StudentProgress` record is created or queried.
  Generate an Alembic migration.
  Safe to delete `cairn.db` and re-run `make migrate` — no production data exists.
  **Do not implement TuneBox models in this task** — use a plain integer stub
  (e.g. `box_id=1`) in tests until task 4.1 adds the real model.

---

### 4. Tune Box and Practice Lists

- [x] **4.1 — TuneBox models and CRUD service**
  New models in `cairn/models.py`:

  `TuneBox`: id, user_id FK, name (str).

  `TuneBoxInstrument`: box_id FK, instrument (Instrument enum).
  Composite primary key `(box_id, instrument)`. A box must have ≥ 1 instrument.

  `TuneBoxEntry`: id, box_id FK, tune_id FK, setting_id FK (nullable —
  preferred TuneSetting for this box context). Unique `(box_id, tune_id)`.

  Service functions in `cairn/services/boxes.py`:
  - `create_box(db, user_id, name, instruments) -> TuneBox`
    Must create at least one `TuneBoxInstrument` in the same transaction.
  - `add_tune(db, box_id, tune_id) -> TuneBoxEntry`
    Auto-set `setting_id` if exactly one existing TuneSetting matches a box
    instrument; leave null otherwise.
  - `set_preferred_setting(db, box_id, tune_id, setting_id) -> TuneBoxEntry`
  - `remove_tune(db, box_id, tune_id) -> bool`
  - `list_boxes(db, user_id) -> list[TuneBox]`
  - `get_box(db, box_id) -> TuneBox | None`

  Generate Alembic migration.
  Write tests in `tests/test_services/test_boxes.py`.
  After this task, update the `box_id` stubs from task 3.4 to use real TuneBox ids.

- [x] **4.2 — TuneBox routes and templates**
  Router: `cairn/routers/boxes.py`, prefix `/boxes`.
  Routes:
  - `GET /boxes` — list user's boxes → `boxes/index.html`
  - `GET /boxes/new` — create box form → `boxes/form.html`
  - `POST /boxes` — create box + instruments → redirect to box detail
  - `GET /boxes/{id}` — box detail with tune list → `boxes/detail.html`
  - `POST /boxes/{id}/tunes` — add a tune to the box (HTMX, returns tune row partial)
  - `DELETE /boxes/{id}/tunes/{tune_id}` — remove tune (HTMX)
  - `POST /boxes/{id}/tunes/{tune_id}/setting` — set preferred setting (HTMX)
  Add a "Boxes" link to `base.html` nav.

- [x] **4.3 — PracticeList and TuneListEntry models and CRUD service**
  New models in `cairn/models.py`:

  `PracticeListType` enum: `repertoire | woodshed` (with `.label`).

  `PracticeList`: id, user_id FK, box_id FK, name (str), list_type
  (PracticeListType), progress_goal (ProgressStatus, must be > just_learning,
  default committed), target_date (date, nullable), is_active (bool, default False).

  `TuneListEntry`: id, tune_id FK, list_id FK, setting_id FK (nullable —
  session display override; also selects the SettingProgress record to use).
  Unique `(tune_id, list_id)`.

  Service functions in `cairn/services/lists.py`:
  - `create_list(db, user_id, box_id, name, list_type, progress_goal, target_date) -> PracticeList`
  - `activate_list(db, user_id, list_id) -> PracticeList`
    Deactivates any currently active list for this user first.
  - `deactivate_list(db, user_id) -> None`
  - `add_tune_to_list(db, list_id, tune_id, setting_id) -> TuneListEntry`
  - `remove_tune_from_list(db, list_id, tune_id) -> bool`
  - `get_active_list(db, user_id) -> PracticeList | None`

  Generate Alembic migration.
  Write tests in `tests/test_services/test_lists.py`.

- [x] **4.4 — PracticeList routes and templates**
  Router: `cairn/routers/lists.py`, prefix `/lists`.
  Routes:
  - `GET /lists` — all lists for current user → `lists/index.html`
  - `GET /lists/new` — create list form → `lists/form.html`
  - `POST /lists` — create list → redirect to list detail
  - `GET /lists/{id}` — list detail with tune membership → `lists/detail.html`
  - `POST /lists/{id}/activate` — set as active list (HTMX)
  - `POST /lists/{id}/deactivate` — deactivate (HTMX)
  - `POST /lists/{id}/tunes` — add tune to list (HTMX)
  - `DELETE /lists/{id}/tunes/{tune_id}` — remove from list (HTMX)
  Add a "Lists" link to `base.html` nav.

- [x] **4.5 — SettingProgress model and service integration**
  New model in `cairn/models.py`:

  `SettingProgress`: id, user_id FK, setting_id FK, box_id FK, status
  (ProgressStatus). Unique `(user_id, setting_id, box_id)`.

  Add to `cairn/services/spaced_rep.py`:
  - `get_effective_status(db, user_id, tune_id, box_id, setting_id | None) -> ProgressStatus`
    Returns `SettingProgress.status` if a setting_id is given and a record exists;
    otherwise `StudentProgress.status`; otherwise `just_learning`.
  - `retire_setting_progress(db, user_id, setting_id, box_id) -> None`

  Update `record_practice` to also advance `SettingProgress` when the active
  list entry has a `setting_id`. Retire the `SettingProgress` record automatically
  if its status catches up to `StudentProgress.status`.

  Update Repertoire auto-removal in `set_status` / `record_practice` to use
  `get_effective_status` rather than raw `StudentProgress.status`.

  Generate Alembic migration.
  Add tests in `tests/test_services/test_spaced_rep.py`.

- [x] **4.5b — Setting picker for list entries**
  Update the add-tune form on `lists/detail.html` to include an optional setting
  dropdown alongside the tune picker. When the tune selection changes, an HTMX
  request fetches the non-core settings for that tune and populates the setting
  dropdown (hidden if the tune has no non-core settings). The selected setting is
  submitted with `tune_id` in `POST /lists/{id}/tunes` and stored as
  `TuneListEntry.setting_id`. No new service functions needed — `add_tune_to_list`
  already accepts `setting_id`.

---

### 5. Practice Session Planner

- [x] **5.1 — Session plan service**
  Create `cairn/services/session_plan.py`.
  Implement `build_session(db, user_id, box_id, total_minutes) -> list[PracticeSessionItem]`.
  Logic:
  - Allocate ~10% to warmup (at least 1 item)
  - Resolve the active PracticeList for this user (may be None)
  - Build learning and retention queues per the session queue logic in AGENTS.md:
    - Repertoire list: learning = list entries with effective_status < goal;
      retention = full box, status ≥ goal, next_suggested ≤ now, minus learning tunes
    - Woodshed list: learning = list entries with effective_status < goal;
      retention = full box, status ≥ goal; woodshed-tagged tunes bypass SM-2 gate
      and are top-weighted; minus learning tunes
    - No active list: learning = box tunes with status < committed, weighted by
      proximity to committed; retention = box tunes with status ≥ committed,
      next_suggested ≤ now
  - Lower status = longer learning slot (see AGENTS.md progress table)
  - Never include mixed-meter auto-generated sets
  Write tests covering: short session (15 min), standard session (45 min), Repertoire
  list active, Woodshed list active, no active list, no tunes due for retention,
  all tunes committed.

- [x] **5.2 — Practice session routes and templates**
  Router: `cairn/routers/practice.py`, prefix `/practice`.
  Routes:
  - `GET /practice/plan` — form to enter total minutes and select active box →
    `practice/plan.html`
  - `POST /practice/plan` — generate and display session plan →
    `practice/session.html`; show active practice list name if one is set
  - `POST /practice/session/{id}/item/{item_id}/complete` — mark item done (HTMX)
  - `POST /practice/session/{id}/finish` — close session, record total time

- [x] **5.3 — Dashboard**
  Create `cairn/templates/dashboard.html` as the root `/` route.
  Show: active TuneBox name, active PracticeList name (if any), tunes due for
  retention today, current learning tunes with status, a "Start Practice" button
  linking to `/practice/plan`.

---

### 6. Warmup Library

- [x] **6.1 — Warmup CRUD**
  Router: `cairn/routers/warmups.py`, prefix `/warmups`.
  Basic CRUD for `WarmupItem`: list, create, edit, delete.
  Content field renders as ABC notation if `warmup_type == scale or snippet`,
  or as plain text if `warmup_type == text_blurb`.

---

### 6b. TuneSet Management

- [x] **6b.1 — TuneSet model updates and migration**
  Extend the existing `TuneSet` and `TuneSetMember` models (from task 1.4)
  and add a box-set join model.

  **`TuneSet` — new fields:**
  - `source: Mapped[str | None] = mapped_column(String(200), nullable=True)`
    Where this set came from (e.g. "Tommy Peoples session", "Catskills 2023").
    Maps to the ABC `S:` header when building the combined ABC string.
  - `abc_header: Mapped[str | None] = mapped_column(Text, nullable=True)`
    Raw ABC header lines supplied by the user. These are injected verbatim
    into the combined ABC output and take priority over auto-populated headers
    when the same letter appears in both. One header per line, e.g. `P:AABB`.

  **`TuneSetMember` — new field:**
  - `setting_id: Mapped[int | None] = mapped_column(ForeignKey("tune_settings.id"), nullable=True)`
    Optionally pins a specific `TuneSetting` for this member. When null, the
    tune's active box setting (or its core setting) is used.
  - Add relationship: `setting: Mapped["TuneSetting | None"] = relationship()`

  **New model `TuneBoxSetEntry`** in `cairn/models.py`:
  Links a TuneSet to a TuneBox (parallel to `TuneBoxEntry` for individual tunes).
  ```
  TuneBoxSetEntry: id, box_id FK → tune_boxes.id, set_id FK → tune_sets.id
  Unique constraint: (box_id, set_id)
  ```
  Relationships: `box: Mapped["TuneBox"]`, `tune_set: Mapped["TuneSet"]`.
  Add `box_set_entries: Mapped[list["TuneBoxSetEntry"]]` relationship to `TuneBox`.

  **New model `TuneSetTempo`** in `cairn/models.py`:
  Records the last-used metronome tempo per user/box/set context.
  Box is part of the key because the same set can appear in multiple boxes
  and the natural tempo may differ (different keys, different settings per box).
  ```python
  class TuneSetTempo(TimestampMixin, Base):
      __tablename__ = "tune_set_tempos"

      user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
      box_id:  Mapped[int] = mapped_column(ForeignKey("tune_boxes.id"), primary_key=True)
      set_id:  Mapped[int] = mapped_column(ForeignKey("tune_sets.id"), primary_key=True)
      tempo:   Mapped[int] = mapped_column(Integer, nullable=False)
  ```
  Composite PK `(user_id, box_id, set_id)`. Upsert on write (same pattern as
  `WarmupTempo`). `box_id` is required; when the detail page is viewed outside
  a box context, tempo is not recorded.

  **Update Pydantic schemas** in `cairn/schemas.py`:
  - `TuneSetCreate` / `TuneSetUpdate` / `TuneSetRead`: add `source`, `abc_header`
  - `TuneSetMemberCreate` / `TuneSetMemberUpdate` / `TuneSetMemberRead`: add `setting_id`
  - Add `TuneBoxSetEntryRead`

  Generate Alembic migration covering all changes above.
  Safe to delete `cairn.db` and re-run `make migrate` — no production data.

- [x] **6b.2 — TuneSet CRUD service and ABC builder**
  Create `cairn/services/tune_sets.py`.

  **Service functions:**
  - `create_set(db, title, description, source, abc_header, flow_difficulty,
    flow_difficulty_notes) -> TuneSet`
  - `get_set(db, set_id) -> TuneSet | None`
    Eager-load `members`, `members.tune`, `members.setting`, `members.tune.settings`.
  - `list_sets(db) -> list[TuneSet]`
    Ordered by title; eager-load member count only (no deep loading).
  - `update_set(db, set_id, **fields) -> TuneSet | None`
  - `delete_set(db, set_id) -> bool`
  - `set_members(db, set_id, member_data: list[dict]) -> TuneSet`
    Replaces the full member list in one transaction. Each dict has keys
    `tune_id` (required) and `setting_id` (optional, nullable). `order` is
    assigned from list position (0-based). Deletes removed members, upserts
    existing ones, inserts new ones. Returns the updated TuneSet.
  - `add_box_set(db, box_id, set_id) -> TuneBoxSetEntry`
  - `remove_box_set(db, box_id, set_id) -> bool`

  **ABC builder** `build_set_abc(tune_set, box=None) -> str` in
  `cairn/services/abc_utils.py`:
  Builds a multi-tune ABC string (one X: section per member, in member order).
  Header assembly for each member tune (X: index increments per member):
  - Use existing `build_abc(tune, setting, x=N)` for each member's tune body.
    The `setting` passed is `member.setting` if set, otherwise the tune's
    core setting.
  Set-level headers are inserted before the first X: block:
  - `T:` → `tune_set.title`
  - `S:` → `tune_set.source` (omit if null)
  - `G:` → `box.name` (omit if box is None)
  If `tune_set.abc_header` is set, its lines are injected after `G:` (or
  after `S:` / `T:` if G is absent); any letter that already appeared in
  the auto-populated set-level headers is replaced by the user-supplied line.
  Write unit tests in `tests/test_services/test_tune_sets.py` covering:
  - `create_set` and round-trip via `get_set`
  - `set_members` with reorder (verify `order` column)
  - `set_members` strips removed members
  - `build_set_abc` with and without `box`, with and without `source`/`abc_header`
  - `build_set_abc` user-supplied header overrides auto-populated header of same letter
  - `add_box_set` / `remove_box_set`

- [x] **6b.3 — TuneSet CRUD routes and templates**
  Router: `cairn/routers/tune_sets.py`, prefix `/sets`.
  Mount in `cairn/main.py`. Add a "Sets" link to `base.html` nav.

  **Routes:**
  - `GET /sets` — list all sets → `sets/index.html`
  - `GET /sets/new` — blank create form → `sets/form.html`
  - `POST /sets` — create set → redirect to `/sets/{id}`
  - `GET /sets/{id}/edit` — edit form → `sets/form.html`
  - `POST /sets/{id}` — update set → redirect to `/sets/{id}`
  - `DELETE /sets/{id}` — delete (HTMX, returns HX-Redirect to `/sets`)
  - `GET /sets/{id}/settings/{tune_id}` — HTMX partial: returns a `<select>`
    of available settings for `tune_id`, for the setting picker.

  **Form (`sets/form.html`) features:**
  - Text inputs: title (required), description (optional), source (optional)
  - Difficulty slider 1–5 with live numeric label (same pattern as warmup form)
  - ABC header textarea (collapsible `<details>` block, same styling as the
    ABC notation reference block on `warmups/form.html`); placeholder shows
    example lines like `P:AABB\nQ:1/4=120`
  - Member list — drag-to-reorder using the HTML5 `draggable` attribute and
    Alpine.js drag handlers. Each row shows:
    - Tune title (read-only; lookup from hidden `tune_id` input)
    - Setting picker: an inline `<select>` populated via
      `GET /sets/{id}/settings/{tune_id}` (HTMX on page load per row);
      the first option is always "— default —" (null setting_id)
    - Setting label shown in parentheses after the tune title, truncated to
      ~30 chars with CSS `text-overflow: ellipsis`
    - Remove button (×)
  - Tune search / add: a text input with HTMX search that returns matching
    tunes as clickable rows; clicking a row appends it to the member list
    and fires the settings fetch for that tune
  - Live combined ABC preview (`<div id="set-abc-preview">`) below the
    member list, rendered via ABCJS and updated on every member change,
    reorder, or setting pick. Build the combined ABC string client-side
    from inline JSON data attributes (pre-populated from the server) so the
    preview round-trips without a server call. ABC string is regenerated in
    JS whenever the member list changes; pass `build_set_abc` output as the
    initial value via `window.__cairnSetAbc = {{ set_abc | tojson }}` and
    re-render on each edit.
  - Hidden `member[]` inputs (JSON-encoded array of `{tune_id, setting_id}`)
    submitted with the form; decoded in the route handler and passed to
    `set_members()`

  **Index (`sets/index.html`):**
  Table or card list: title, member count, flow_difficulty badge, edit link.

- [x] **6b.4 — TuneSet detail/read page**
  Route: `GET /sets/{id}` → `sets/detail.html`.
  The route handler calls `build_set_abc(tune_set, box=active_box)` where
  `active_box` is looked up via the stub user's active TuneBox (may be None).

  **Combined ABC render:**
  Render the full multi-tune ABC string via ABCJS in a `<div id="set-abc-render">`.
  Use the same approach as `tunes/detail.html`: a `<template id="abc-source">`
  holding the raw ABC, initialised via `window.initTuneTools(abcString)` or an
  equivalent set-aware init function in `app.js`.

  **Playback controls:**
  Metronome, drone, and tuner buttons using the same shared infrastructure
  as `tunes/detail.html` (tempo slider, metro/play buttons, tuner drawer).

  **Tempo recording:**
  On metro stop, if the session lasted at least 4 bars at the current BPM,
  POST to `POST /sets/{id}/tempo` with `tempo` and `box_id` form fields.
  The route handler calls `upsert_set_tempo(db, user_id, box_id, set_id, tempo)`
  (SQLite upsert, same pattern as `upsert_warmup_tempo`). Returns 204.
  When rendering the detail page, the route handler calls
  `get_set_tempo(db, user_id, box_id, set_id) -> int | None` and passes
  `last_tempo` to the template. The slider seeds from:
  `window.__cairnLastTempo || naturalBpm || 100`
  (no `default_tempo` on TuneSet; the stored value is always from a real session).
  If `box_id` is absent (no active box), skip the fetch and disable recording.

  **Per-member bars-to-show controls:**
  Below (or overlaying) the rendered score, show a row of controls — one per
  member — labelled by tune title. Each control cycles through:
  `2 bars → 8 bars → Full → 2 bars …`
  Default value is determined by the lowest progress level among all members
  for the stub user:
  - `just_learning` or no record → 2 bars
  - `getting_familiar` → 8 bars
  - `committed` or higher → Full
  Clicking cycles to the next option. The ABCJS render is re-scoped on click
  to show only the selected bar range for that tune (using the ABCJS
  `startingTune` / `oneSvgPerLine` options or by slicing the ABC body).
  A "►" arrow button advances to the next member's segment after the current
  one finishes (or the user clicks it).

  **Member list sidebar or footer:**
  Shows tune titles in order with their current bars-to-show state and a
  progress badge (status from `StudentProgress` for the stub user).

- [x] **6b.5 — Extend seed scripts to cover all content types**
  Update `scripts/export_seed.py` and `scripts/seed.py` to handle warmups,
  boxes, and lists in addition to the existing tunes support. TuneSet export
  and import will be added here once 6b.1 is implemented.

  **`scripts/export_seed.py`** — write one file per entity type to `seeds/`:
  - `seeds/tunes.json` — existing (no change to format)
  - `seeds/warmups.json` — title, warmup_type, content, difficulty,
    default_tempo, instruments list
  - `seeds/boxes.json` — name, instruments list, entries list
    (each entry: `tune_title`, `setting_label` or null)
  - `seeds/lists.json` — name, box_name, list_type, progress_goal,
    target_date, is_active, entries list
    (each entry: `tune_title`, `setting_label` or null)
  All cross-references use stable human-readable keys (title / label / name)
  rather than database IDs so seeds survive a fresh database.
  Default output directory: `seeds/` (positional arg overrides).

  **`scripts/seed.py`** — read from `seeds/` directory, in dependency order:
  tunes → warmups → boxes → lists.
  Each file is optional — missing files are skipped with a notice.
  Deduplication per type:
  - Tunes: by title (existing behaviour)
  - Warmups: by title
  - Boxes: by (user_id, name)
  - Lists: by (user_id, box_id, name)
  FK resolution during import:
  - Box entry `tune_title` → look up `Tune.id` by title; warn and skip entry if not found
  - Box entry `setting_label` → look up `TuneSetting.id` by (tune_id, label); null if not found or label is null
  - List `box_name` → look up `TuneBox.id` by (user_id, name); error and skip list if not found
  - List entry resolution: same pattern as box entries
  Restore `is_active` on lists (at most one per user will be active, matching
  the constraint enforced by `activate_list`).

  **After 6b.1**: add TuneSet export (title, description, source, abc_header,
  flow_difficulty, flow_difficulty_notes, members list with tune_title and
  setting_label) and import (dedup by title, member FK resolution by title).

---

### 7. Content Management

Markdown-based content system for authored pages (onboarding, help, feature
explanations) with a model flexible enough to serve Phase 4 lesson content
without redesign.

**Dependencies to add to `pyproject.toml`:**
- `markdown` — rendering library
- `python-frontmatter` — YAML front matter parsing

- [x] **7.1 — Content model, import pipeline, and service**
  **New enum** in `cairn/models.py`:
  `ContentType`: `page | lesson | tutorial | technique_guide`
  (extend as Phase 4 content types become clear; start with `page` only).

  **New model** in `cairn/models.py`:
  ```
  Content: id, slug (String 200, unique, indexed), title (String 200),
           content_type (ContentType), body (Text — raw markdown),
           visibility (ContentVisibility, default public),
           created_by FK → users.id (nullable — null = system/built-in),
           metadata (JSON, nullable — type-specific structured data)
  ```
  Include `TimestampMixin`. Generate Alembic migration.

  **Service** `cairn/services/content.py`:
  - `upsert_content(db, slug, title, content_type, body, visibility,
    metadata=None, created_by=None) -> Content`
    Insert or update by slug. Used by both the import script and future
    in-app authoring routes.
  - `get_content(db, slug) -> Content | None`
  - `list_content(db, content_type=None) -> list[Content]`
    Filters by content_type when provided, ordered by title.

  **Import script** `scripts/import_content.py`:
  Reads every `*.md` file under `content/` (create the directory).
  Each file has a YAML front matter block; required keys:
  `slug`, `title`, `content_type`. Optional: `visibility`, `metadata`.
  Upserts each record into the DB via `upsert_content`.
  Run via `uv run python scripts/import_content.py`.

  **YAML front matter format:**
  ```yaml
  ---
  slug: getting-started
  title: Getting Started with The Cairn
  content_type: page
  visibility: public
  ---
  Markdown body here…
  ```

  **`make content` target** in `Makefile`:
  Runs the import script. Should be mentioned in `AGENTS.md`.

  Write tests in `tests/test_services/test_content.py` covering:
  upsert creates, upsert updates by slug, get_content hit and miss,
  list_content with and without type filter.

- [x] **7.2 — Content rendering and routes**
  **Renderer** — add `render_markdown(body: str) -> str` to
  `cairn/services/content.py`.
  Uses `markdown.markdown()` with extensions:
  `attr_list`, `tables`, `extra`, `nl2br`.
  `attr_list` enables `{.class}` syntax on any element:
  ```markdown
  ![image](url){.w-1/2 .float-right .rounded-lg}
  # Heading {.text-2xl}
  ```
  HTML passthrough is enabled by default in python-markdown — no extra
  configuration needed. Authors may use raw HTML as an escape hatch for
  layouts `attr_list` cannot express (e.g. flex containers).

  **Router** `cairn/routers/content.py`, prefix `/pages`, tag `content`.
  - `GET /pages/{slug}` — look up content by slug, render body, return
    `content/page.html`. Return 404 if slug not found or visibility
    is `private` (enforce `enrolled` and `public` only for Phase 1 since
    there is no auth yet).

  **Templates:**
  - `cairn/templates/content/page.html` — extends `base.html`.
    Renders `{{ rendered_body | safe }}` inside a `prose` container.
    Use Tailwind's prose-style utility classes applied manually (no
    Tailwind Typography plugin — CDN build doesn't include it).
    Apply sensible defaults to the container:
    `max-w-3xl mx-auto space-y-4 text-stone-700 leading-relaxed`.
    Headings, links, tables, and images should look reasonable without
    per-element classes when authors don't specify any.

  Wire router into `cairn/main.py`.

  **Seed file:** create `content/getting-started.md` as a placeholder page
  so the import script and route have something to exercise.

  Write a smoke test in `tests/test_routers/test_content.py`:
  seed a `Content` record, `GET /pages/{slug}`, assert 200 and title
  appears in the response.

- [x] **7.3 — Warmup text blurb: markdown with embedded ABC notation**

  Change warmup `text_blurb` content from plain text to markdown, rendered
  via `render_markdown()` (from 7.2) and with ABC fenced block support
  (from the 7.2 extension issue #68).

  **Detail page** (`cairn/templates/warmups/detail.html`):
  When `warmup.warmup_type == WarmupType.text_blurb`, render
  `warmup.content` through `render_markdown()` in the route handler and
  pass `rendered_body` to the template. Display with the same prose
  container as `content/page.html`:
  `max-w-3xl mx-auto space-y-4 text-stone-700 leading-relaxed`.
  ABC blocks in the markdown render via the ABCJS post-processor from
  issue #68 — no extra work needed.

  **Form** (`cairn/templates/warmups/form.html`):
  When `warmup_type` is `text_blurb`, show a Write / Preview tab toggle
  above the content textarea (same pattern as GitHub's editor):
  - **Write tab** — shows the raw textarea for editing
  - **Preview tab** — POSTs the textarea content to a new endpoint
    `POST /warmups/preview-markdown` (returns rendered HTML fragment),
    then swaps the textarea out for a `<div>` showing the result; swap
    back on return to Write
  The toggle is hidden for `scale` and `snippet` types (those use the
  live ABCJS preview from issue #64).

  **New route** `POST /warmups/preview-markdown`:
  Accepts `body: str` form field. Calls `render_markdown(body)`.
  Returns an HTML fragment (not a full page) for injection into the
  preview panel. No auth required for Phase 1.

  **No schema/migration needed** — `content` column stays `Text`;
  the interpretation changes by type.

  Update `content/` seed docs or AGENTS.md to note that `text_blurb`
  warmup bodies accept markdown with ` ```abc ``` ` fenced blocks.

  Write tests in `tests/test_routers/test_warmups.py`:
  - `POST /warmups/preview-markdown` returns rendered HTML
  - ABC fenced block in preview body is passed through as a
    `<code class="language-abc">` element (rendering is client-side)

---

### 8. TheSession.org Data Integration

Pulls reference data from [TheSession-data](https://github.com/adactio/TheSession-data)
(released under ODbL) into local side tables, so users can populate their own
tunes/settings/aliases from a well-known community dataset instead of typing
everything from scratch. No page in the app browses these side tables
directly — they exist purely to back the linking wizard in 8.2. ODbL requires
attribution for reused facts; see 8.3.

**Source data**: 7 CSVs under `csv/` in that repo — `tunes.csv` (one row per
*setting*, not per tune: `tune_id, setting_id, name, type, meter, mode, abc,
date, username, composer`), `aliases.csv` (`tune_id, alias, name` — `name` is
the tune's current canonical name, repeated per alias row), `tune_popularity.csv`
(`name, tune_id, tunebooks`), `sets.csv` (user-submitted tune sequences —
`tuneset, date, member_id, username, settingorder, name, tune_id, setting_id,
type, meter, mode, abc`), `recordings.csv` (`id, artist, recording, track,
number, tune, tune_id` — note `id` here is the *recording's* id and repeats
across its tracks, not a per-row id), `sessions.csv` (real-world session
*venues* — `id, name, address, town, area, country, latitude, longitude,
date`), `events.csv` (`id, event, dtstart, dtend, venue, address, town, area,
country, latitude, longitude`). The repo also ships a pre-built `thesession.db`,
but it's Git LFS-tracked (~136MB) — fetching the CSVs directly from
`raw.githubusercontent.com` is simpler and avoids an LFS dependency.

**No new pyproject dependency needed** — the import script can use stdlib
`csv` + `urllib.request`.

**Two model groups, split across 8.1 and 8.4** — `TheSessionSetting` /
`TheSessionAlias` / `TheSessionTunePopularity` (3 models, all keyed on
`tune_id`) are the tune-reference data the wizard in 8.2 actually needs.
`TheSessionSet` / `TheSessionSetMember` / `TheSessionRecording` /
`TheSessionVenue` / `TheSessionEvent` (5 models — real-world session/
recording/event metadata, not tune data) are unrelated to the wizard and
nothing in 8.2/8.3 depends on them. Splitting the work this way means 8.1
unblocks the wizard on its own, and 8.4 is fully deferrable — it can happen
whenever, or not at all, without affecting anything else. It also means
neither group *exceeds* the 5-model threshold in `AGENTS.md`'s model file
split rule (3 and 5 respectively), so each can live in its own scoped
sibling file (e.g. `cairn/models_thesession_tunes.py` and
`cairn/models_thesession_community.py`) from the start — no need to convert
`models.py` into a `models/` package for either.

- [x] **8.1 — Side-table models + import script (tune reference data)**

  **New models**, one per CSV, in a new `cairn/models_thesession_tunes.py`.
  Each is a faithful 1:1 mirror of its CSV: don't pre-aggregate or
  deduplicate at import time (e.g. no separate "tune-level" table for
  `tunes.csv` — query `DISTINCT tune_id` from `TheSessionSetting` at read
  time instead). This keeps the mirror lossless and matches the goal of
  having data available for whatever query comes up later, without baking
  in assumptions about which row "wins" per tune.

  - `TheSessionSetting` (from `tunes.csv`) — surrogate `id` (PK, **not**
    `setting_id`: confirmed against the real dataset that `setting_id` isn't
    actually unique — e.g. setting_id 1892 appears twice with different
    `composer` credits — so treating it as a PK would silently drop rows),
    `setting_id` (indexed, not unique), `tune_id` (indexed), `name`,
    `tune_type_raw`, `meter`, `mode_raw`, `abc` (Text — music body only, no
    headers, same convention as our own `TuneSetting.abc_notation`),
    `submitted_date`, `username`, `composer`
  - `TheSessionAlias` (from `aliases.csv`) — surrogate `id` (PK), `tune_id`
    (indexed), `alias`, `canonical_name`
  - `TheSessionTunePopularity` (from `tune_popularity.csv`) — `tune_id` (PK),
    `name`, `tunebooks`

  **Import script** `scripts/import_thesession.py` (structured so 8.4 can
  extend it with more CSVs later rather than replacing it):
  - Downloads each CSV fresh from
    `https://raw.githubusercontent.com/adactio/TheSession-data/main/csv/{name}.csv`
    on every run — nothing vendored into this repo.
  - `tunes.csv` alone is tens of thousands of rows — use a bulk
    insert per file (e.g. `session.execute(insert(Model), rows)` in
    batches inside one transaction), not the one-row-at-a-time ORM
    `db.add()` + `commit()` style `import_abc.py`/`import_content.py` use.
  - These are pure read-only mirror tables with no user-authored data mixed
    in, so the simplest correct refresh is delete-all-then-bulk-reinsert per
    table per run, rather than tracking per-row upserts.
  - `make thesession-import` target (mirroring `make content`).

  **Mapping notes**:
  - `mode_raw` → `KeyRoot`/`KeyMode`: reuse `_parse_key()` from
    `scripts/import_abc.py` as-is — it already handles concatenated
    `"Gmajor"`/`"Edorian"`-style strings via its mode-suffix capture group
    and `_KEY_MODE_MAP` lookup, confirmed against real sample rows.
  - `tune_type_raw` → `TuneType`: compared the distinct `type` values in
    `tunes.csv` against our `TuneType` enum directly. 10 of TheSession's 12
    values already match ours 1:1 (`barndance`, `hornpipe`, `polka`, `reel`,
    `jig`, `march`, `slide`, `strathspey`, `waltz`, plus `"slip jig"` which
    just needs the space normalized to `slip_jig`). Two have no equivalent
    yet: `mazurka` and `three-two` (→ `three_two`) — add these as new
    `TuneType` values, and assign them a bucket in `TUNE_FAMILIES`
    (`cairn/services/tunes.py`) so Family filtering keeps working — `mazurka`
    is triple-time like `waltz` (probably `"other"`); `three_two` is closer
    to `strathspey`'s march-family feel but could go either way, worth a
    second opinion when it comes up. One direction only: our own `air` type
    has no equivalent in TheSession's vocabulary, so no incoming tune will
    ever map to it — not a problem, just means airs aren't part of this
    import.

  Write tests in `tests/test_scripts/test_import_thesession.py` (mirroring
  `tests/test_scripts/test_seed.py`): CSV-row-to-model parsing per table,
  the reused key/mode mapping, and that re-running the import doesn't
  duplicate or leak stale rows.

- [x] **8.2 — Tune-linking wizard**

  **`Tune` model** gets two new nullable fields: `thesession_tune_id: int`
  and `thesession_username: str` (the username tied to whichever setting
  populated the tune). **`TuneSetting`** gets `thesession_setting_id: int`
  and `thesession_username: str` (who submitted that specific setting).
  These are plain reference ids, **not** FKs into the 8.1 side tables — the
  side tables are a refreshable cache; these fields are a permanent
  attribution link that must survive a cache refresh/rebuild. Generate an
  Alembic migration.

  **`GET /tunes/{id}`**: if `tune.thesession_tune_id` is set, show it as a
  link to `https://thesession.org/tunes/{thesession_tune_id}` (add
  `#setting{thesession_setting_id}` when a setting id is also known)
  instead of the "Link Tune" button described below.
  Otherwise, show a "Link Tune" button (tooltip: "Link to Tune @
  TheSession.org") that opens the wizard.

  **Wizard** — a modal/multi-step flow (Alpine for step state + HTMX
  partials per step, similar in spirit to the existing setting-change
  confirmation modal in `boxes/partials/_setting_change_modal.html`):

  - **Page 1 — pick a tune**: search/filter over `TheSessionSetting`
    grouped by distinct `tune_id`. Same Tune Type / Family filters as the
    regular tune index (reuse `TUNE_FAMILIES`/`FAMILY_LABELS` from
    `cairn/services/tunes.py` against the mapped `TuneType`). Search matches
    against `TheSessionAlias.alias` as well as the tune name. Each row shows
    title, key, and tune type, with the same hover-preview mechanism used
    elsewhere in the app (`data-abc-preview-id` + `<template>` +
    `initTuneHoverPreview()` from #102), built from that tune's first
    setting's `abc`.
  - **Page 2 — aliases**: every `TheSessionAlias` for the chosen `tune_id`,
    checkbox per alias (all checked by default), Check All / Uncheck All.
    Pre-uncheck (or hide) any alias whose name already exists on the tune
    (case-insensitive match against `TuneAlias.name`) so re-linking a tune
    never creates duplicates.
  - **Page 3 — settings**: every `TheSessionSetting` for that `tune_id`,
    fully rendered via ABCJS, checkbox per setting, 0 or more selectable.
  - **Page 4 — confirm + choose default**: only the checked settings are
    shown, with a radio choice for which one becomes the "default" — i.e.
    the source for `Tune.thesession_tune_id`/`thesession_username`. If the
    tune has no existing core setting (a brand-new tune), the default
    setting *also* becomes the actual `is_core=True` `TuneSetting`, and the
    tune's own `title`, `tune_type`, `time_signature` (from `meter`), and
    `key_root`/`key_mode` (from `mode_raw`) are populated from it. If a core
    setting already exists, the default only sets the `Tune`-level
    attribution fields — the existing core setting is never overwritten.
  - **Save**: creates a new non-core `TuneSetting` (with
    `thesession_setting_id`/`thesession_username` set) for every checked
    setting other than one chosen as core; creates the checked, non-
    duplicate aliases; sets `Tune.thesession_tune_id`/`thesession_username`.

  New endpoints, exact shape TBD at implementation time — something like
  `GET /tunes/{id}/thesession-search`, `GET
  /tunes/{id}/thesession-tune/{external_tune_id}` (aliases + settings for
  steps 2–3), `POST /tunes/{id}/thesession-link` (final save). Consider a
  dedicated `cairn/routers/thesession_link.py` given the number of steps.

  Write tests covering: search/filter results, alias dedup on import,
  imported settings carry the right `thesession_setting_id`/`username`,
  core setting is never overwritten when one already exists, and a
  brand-new tune is correctly populated from the chosen default.

- [x] **8.3 — Attribution links**

  Anywhere a tune or setting page shows data carrying a
  `thesession_tune_id`/`thesession_setting_id`, show a small attribution
  link back to `https://thesession.org/tunes/{id}` (setting-anchored where
  applicable), per ODbL's attribution requirement. At minimum:
  `tunes/detail.html`, and each setting in `tunes/partials/_settings.html`
  that carries a `thesession_setting_id`.

  Already delivered as part of 8.2's code review (a code-review finding
  flagged this as a required-by-AGENTS.md Domain Rule #18 gap in the 8.2
  diff itself, so it was fixed there rather than left for a separate PR).

- [x] **8.4 — Side-table models + import for community data (deferred, optional)**

  Not needed by 8.2/8.3 or anything else in the app yet — done anyway since
  it's a small, self-contained extension of 8.1's existing import script.
  Exists to have the rest of TheSession-data available to query without a
  later re-import project; nothing in the app browses these tables yet.

  **New models**, one per CSV, in `cairn/models_thesession_community.py`:

  - `TheSessionSet` (from `sets.csv`, header fields, deduplicated to one row
    per `tuneset` — see `import_sets()`) — `tuneset_id` (PK),
    `submitted_date`, `member_id`, `username`, `name`
  - `TheSessionSetMember` (from `sets.csv`, one row per member) — surrogate
    `id` (PK), `tuneset_id` (FK → `TheSessionSet`), `position`
    (`settingorder`), `tune_id`, `setting_id` — doesn't duplicate
    name/type/meter/mode/abc; join to `TheSessionSetting` (8.1) via
    `setting_id` when needed
  - `TheSessionRecording` (from `recordings.csv`) — surrogate `id` (PK),
    `recording_id` (the CSV's own `id`, not unique per row), `artist`,
    `recording_name`, `track_number`, `position`, `tune_name`, `tune_id`
    (nullable — blank in some source rows)
  - `TheSessionVenue` (from `sessions.csv`, named to avoid confusion with our
    own `PracticeSession`) — `id` (PK), `name`, `address`, `town`, `area`,
    `country`, `latitude`, `longitude`, `submitted_date`
  - `TheSessionEvent` (from `events.csv`) — `id` (PK), `name` (`event`
    column), `starts_at` (`dtstart`), `ends_at` (`dtend`), `venue_name`,
    `address`, `town`, `area`, `country`, `latitude`, `longitude`

  **Correction from this task's original spec, found via a live import
  against the real, current CSV**: `recordings.csv`'s `artist` column was
  assumed to be a bare opaque numeric id (no accompanying name data). Real
  current data disagrees — 201,448 of 201,581 rows (~99.93%) hold the
  artist's actual name as a plain string; only 133 rows (3 distinct values)
  still hold a bare legacy numeric id, never backfilled with a name when
  TheSession-data's schema evidently changed upstream. Field renamed
  `artist_id` → `artist` (still just a `String`, stored as-is either way —
  a faithful mirror, not a cleaned-up view). See 9.2's note, corrected
  the same way.

  Extended `scripts/import_thesession.py` (from 8.1) with these four CSVs
  rather than a second script — same bulk-insert, delete-then-reinsert
  approach. `sets.csv`'s dual-table split (one row per member, deduplicated
  down to one `TheSessionSet` header per `tuneset`) is the one CSV that
  doesn't map 1:1 to a single table — `import_sets()` flushes header rows
  ahead of each member batch (and once more at the end) so a set's header
  is always inserted before its own members.

  Tests in `tests/test_scripts/test_import_thesession.py`, alongside the
  8.1 tests, covering the same concerns (parsing per table, re-running
  doesn't duplicate rows, stale rows dropped on re-run) for all four CSVs,
  plus `TheSessionRecording`'s duplicate-`recording_id`-across-tracks case
  and the legacy-numeric-`artist` case.

---

### 9. Recording References

Lets a user tag a `TuneSetting` or `TuneSet` with a specific physical/digital
recording ("I learned this off Kevin Burke's Sweeney's Dream") plus optional
streaming links (YouTube, Amazon Music, Spotify, etc.).

**Design choice — two tables, not full Artist/Album/Track normalization, not
a bare link.** A fully normalized Artist/Album/Track schema buys dedup and
"browse by artist" queries, but that's only worth the find-or-create-matching
complexity at TheSession's crowd-sourced scale — not for one user's own
annotations. A bare link field loses the ability to show artist/track
without following the link, and forces retyping everything if the same
recording is tagged against multiple tunes. The middle ground: a `Recording`
holds the artist/title/links once; a join table links it to as many
tunes/settings as apply, each with its own track position. Call it
"Recording," not "Album" — matches TheSession's own terminology and covers
compilations, singles, and session-video-only references, not just albums.

- [ ] **9.1 — Recording model + tune/set linking**

  **New models** in `cairn/models.py`:
  ```
  Recording: id, artist (String, plain text — no dedup/FK, same reasoning
             as TheSession's own flat model), title (String),
             links (JSON, nullable — e.g. {"youtube": "...", "amazon": "..."};
             same pattern as Content.metadata_ in cairn/services/content.py)
  RecordingReference: id, recording_id (FK -> Recording),
             setting_id (FK -> TuneSetting, nullable),
             set_id (FK -> TuneSet, nullable),
             track_number (Integer, nullable), position (Integer, nullable —
             which tune within that track, for medleys)
  ```
  `RecordingReference` follows the same "exactly one of two nullable FKs is
  set" pattern already used by `PracticeSessionItem.tune_id`/`warmup_id` —
  enforce exactly one of `setting_id`/`set_id` at the service layer.
  Include `TimestampMixin`. Generate an Alembic migration.

  **Service** `cairn/services/recordings.py`: `create_recording`,
  `add_reference` (setting or set + recording + track/position),
  `list_recordings_for_setting`, `list_recordings_for_set`,
  `remove_reference`.

  **UI**: an "add a recording" affordance on the tune detail page (per
  setting) and the set detail page — artist/title/links fields plus a
  searchable "or pick an existing Recording" step so the same album isn't
  re-created every time a new tune from it is tagged.

  Write tests in `tests/test_services/test_recordings.py`.

- [ ] **9.2 — Optional: suggest recordings from TheSession data**

  Depends on TODO 8.4 (`TheSessionRecording`) having been done — this piece
  doesn't apply otherwise.

  When adding a recording for a tune that has `thesession_tune_id` set,
  additionally query `TheSessionRecording` for
  `tune_id == tune.thesession_tune_id` and offer each match as a
  pre-fillable suggestion (recording title, track number, position, and —
  see below — artist). **This is a pre-fill, not a full auto-import**:
  streaming links aren't part of TheSession's data at all, so those stay
  blank for the user to fill in regardless.

  Correction from this section's original note (written before 8.4 was
  actually implemented): `recordings.csv`'s `artist` column was assumed to
  be a bare opaque numeric id. A live import against the real, current CSV
  (done as part of 8.4) shows this is stale — 201,448 of 201,581 rows
  (~99.93%) now hold the artist's actual name as a plain string (e.g.
  `Dervish`), not a numeric id; only a small legacy fraction (133 rows, 3
  distinct values: `422`, `1651`, `1691`) still hold a bare leftover numeric
  id, presumably never backfilled with a name when TheSession-data's own
  schema changed upstream. `TheSessionRecording.artist` (8.4) stores
  whichever it is, as-is. So the pre-fill suggestion here **can** include
  the artist field directly in the near-universal case — only fall back to
  leaving it blank when the stored value is purely numeric (i.e. still one
  of those legacy rows).

---

### 10. GCP Deployment (Solo Ops)

Gets the app running on GCP for real, single-user use — no dev/QA
environment (that's handled locally), deployed via GitHub Actions on tag/
release.

**Compute target — Compute Engine VM, not Cloud Run.** The app is
SQLite-backed (`cairn/database.py`), and Cloud Run's filesystem is
ephemeral/networked — SQLite's file-locking model doesn't tolerate that
well, and moving off SQLite to Cloud SQL is a bigger lift than this
warrants for one user. A small always-on VM (e2-micro, free-tier eligible)
with SQLite on the local persistent disk works exactly like local dev — no
DB-layer code changes needed beyond making the connection string
overridable. `cairn/logging_config.py`'s `is_cloud()` already detects
`GOOGLE_CLOUD_PROJECT`/`GAE_APPLICATION` alongside the Cloud Run-specific
`K_SERVICE`/`K_REVISION` vars, so structured JSON logging already activates
correctly on a GCE VM with no changes.

- [x] **10.1 — Externalize the database URL**
  `cairn/database.py` currently hardcodes `DATABASE_URL = "sqlite+aiosqlite:///./cairn.db"`.
  Change to read from a `DATABASE_URL` env var, falling back to that same
  literal for local dev (no `.env` file needed yet — no other secrets exist
  in the app since there's no auth). Keep this minimal; don't introduce a
  settings/config framework for one variable.
  Also updated `alembic/env.py` to honor the same `DATABASE_URL` override,
  so `alembic upgrade head` always targets the same database the app
  connects to.

- [x] **10.2 — systemd service + provisioning script**
  No Docker — a plain `uv`-managed checkout on the VM, matching how it
  already runs locally.
  - `deploy/cairn.service` — systemd unit. `ExecStart` runs
    `uv run uvicorn cairn.main:app --host 0.0.0.0 --port 8000` from the
    repo's `WorkingDirectory`; `Restart=always`; `EnvironmentFile` for
    `DATABASE_URL` / `CAIRN_LOG_LEVEL` overrides.
  - `deploy/provision.sh` — one-time (idempotent, safe to re-run) VM setup:
    installs `uv`, clones the repo, installs the systemd unit, enables it.
    Also runs `uv sync --locked` and `alembic upgrade head`, and installs +
    configures Caddy. Creates a dedicated `cairn` system user and
    `/etc/cairn/cairn.env` (created once, never overwritten by re-runs).
  - **Decided: `the-cairn.app` (registered via Cloudflare), fronted by
    Caddy** for automatic Let's Encrypt TLS — no longer optional, since
    `.app` is on the browser HSTS preload list and plain HTTP to it is
    refused outright, not just discouraged. `deploy/Caddyfile`:
    ```
    the-cairn.app {
        reverse_proxy localhost:8000
    }
    ```
    Install Caddy in `provision.sh` alongside the systemd unit; open 443
    (and 80, needed for the ACME HTTP challenge) in the VM firewall (10.3).

- [x] **10.3 — One-time GCP project setup**
  Manual (not part of the automated deploy) — document the steps rather
  than scripting them, since this runs once:
  - Enable the Compute Engine API; create the e2-micro VM in a free-tier
    region (`us-west1`, `us-central1`, or `us-east1`). Disk: explicitly pick
    **Standard persistent disk** (`pd-standard`) — the Console's default is
    often "Balanced" (`pd-balanced`), which is *not* covered by the Always
    Free tier. Only `pd-standard` up to 30GB-months is free, so size it
    20–30GB (no cost difference from 10GB, just headroom). Firewall rules
    opening 80 and 443 (10.2's Caddy needs both — 80 for the ACME HTTP
    challenge, 443 for the app itself).
  - Reserve the VM's external IP as **static** (GCP's default is
    ephemeral — it changes on VM stop/restart, which would silently break
    DNS). Once reserved, the user adds an **A record** for `the-cairn.app`
    pointing at that IP in Cloudflare's DNS tab, with the proxy status set
    to **DNS only** (grey cloud, not orange) — Caddy needs to see the real
    client connection directly to complete the Let's Encrypt HTTP
    challenge; Cloudflare's proxy would intercept it (fixable later by
    switching to a DNS-01 challenge or Cloudflare Origin CA certs, but
    not worth the complexity for a first pass). This is a manual, one-time
    step on the user's side — can't be scripted since it lives in their
    Cloudflare account.
  - Prefer IAP-tunneled SSH (`roles/iap.tunnelResourceAccessor`) over
    exposing port 22 publicly, if GitHub Actions can reach it that way
    (see 10.4) — otherwise a normal SSH firewall rule scoped to GitHub's
    published IP ranges.
  - Create a dedicated, least-privilege service account for GitHub
    Actions' deploy step and set up Workload Identity Federation between
    GitHub's OIDC provider and that service account — no long-lived JSON
    key stored in GitHub secrets.

  Done. All of the above was completed via the GCP Console (Cloud Shell's
  `gcloud` hit a persistent "Gaia id not found" error unrelated to this
  project's config — worked around entirely through the Console UI). For
  10.4's workflow, the two values it needs:
  - Service account: `github-deploy@the-cairn.iam.gserviceaccount.com`
  - Workload Identity Provider:
    `projects/325835760854/locations/global/workloadIdentityPools/github-pool/providers/github-provider`

- [x] **10.4 — GitHub Actions deploy workflow**
  New `.github/workflows/deploy.yml`, separate from the existing `ci.yml`.
  - Trigger: `release: types: [published]` — an explicit "Publish
    release" action is the deploy trigger, giving a manual gate even if
    tagging itself is automated.
  - Auth via `google-github-actions/auth@v2` using the WIF setup from
    10.3 (no static credentials).
  - Steps: connect to the VM (SSH or IAP tunnel) → `git fetch --tags &&
    git checkout <released tag>` → `uv sync --locked` → `alembic upgrade
    head` → `sudo systemctl restart cairn` → health check (`curl` the
    app's root, expect 200) before declaring success.
  - Rollback is manual on a single-VM setup (no blue/green) — document the
    rollback steps (checkout previous tag, `uv sync --locked`, `systemctl
    restart`) in the workflow file's comments rather than automating it.

  Done. Connects via `gcloud compute ssh --tunnel-through-iap` (plain
  `gcloud`, not a third-party SSH action) and runs the new
  `deploy/run-deploy.sh <tag>` script on the VM, which does the
  fetch/checkout/sync/migrate/restart/health-check sequence as root via
  OS Login sudo, `sudo -u cairn` for the app-owned steps. Rollback
  documented in `deploy.yml`'s own comments per the plan above.

  **Two things needed before this actually works, beyond what 10.3
  covered:**
  1. Grant `github-deploy@the-cairn.iam.gserviceaccount.com` the
     `roles/compute.osAdminLogin` role (project-level IAM, same place as
     the earlier `iap.tunnelResourceAccessor` grant) and enable OS Login
     on the VM (instance metadata `enable-oslogin=TRUE`) — needed so the
     workflow's ephemeral SSH session gets passwordless sudo via GCE's
     `google-sudoers` mechanism, without granting the service account any
     broader Compute Engine permissions.
  2. Set two GitHub Actions repo variables (Settings → Secrets and
     variables → Actions → Variables — not secrets, these aren't
     sensitive): `CAIRN_VM_NAME` and `CAIRN_VM_ZONE`, matching the actual
     VM.
  3. SSH into the VM once (Console's SSH button, which already uses IAP)
     and run `deploy/provision.sh` — it was never actually run against
     the real VM during 10.3, which only covered IAM/networking, so
     `/opt/cairn` doesn't exist yet. Do this *after* this PR merges to
     main, so the initial clone already includes `deploy/run-deploy.sh`
     (needed for the very first automated deploy — it can't fetch itself
     into existence).

- [x] **10.5 — Backup the SQLite file**
  The VM's disk is the only copy of the user's tune library and progress
  data. **Decided: SQLite's own `.backup` command, not whole-disk
  snapshots** — the DB file is the only irreplaceable thing on the VM (the
  code lives in git, the VM setup is 10.2's provisioning script), and
  `.backup` produces a safe, consistent copy even while the app is
  running (unlike a plain `cp`, which can grab a half-written page
  mid-transaction).
  - A nightly `cron` job on the VM runs
    `sqlite3 cairn.db ".backup /tmp/cairn-$(date +%F).db"` and uploads the
    result to a GCS bucket (`gcloud storage cp` / `gsutil cp`).
  - Retention is enforced by a GCS lifecycle rule on that bucket (delete
    objects older than 14 days) — configured once, no manual pruning
    script to maintain.

  Done: `deploy/backup.sh` + a `/etc/cron.d/cairn-backup` entry installed
  by `provision.sh` (nightly at 3am), which also now installs the
  `sqlite3` and `gcloud` CLIs (neither was present on the base image).

  **Manual GCP steps needed before backups actually run** (same spirit
  as 10.3 — one-time, done via Console):
  1. Create a GCS bucket for backups (name must be globally unique —
     something like `the-cairn-backups-325835760854` works).
  2. On that bucket, add a **Lifecycle rule**: delete objects older than
     14 days.
  3. Grant the VM's own attached service account (the same
     `PROJECT_NUMBER-compute@developer.gserviceaccount.com` granted
     `iam.serviceAccountUser` during 10.4) the **Storage Object Admin**
     role, scoped to just this bucket (bucket → Permissions → Grant
     Access) — not project-wide.
  4. Check the VM's **Access scopes** (Compute Engine → VM instances →
     the instance → Edit — requires the VM to be *stopped* to change).
     If it's set to the default limited scope rather than "Allow full
     access to all Cloud APIs," Storage writes will fail even with
     correct IAM. Needs read/write Storage access at minimum.
  5. Set `CAIRN_BACKUP_BUCKET=<bucket-name>` in `/etc/cairn/cairn.env` on
     the VM (uncomment the line provisioning already added) — the cron
     job reads this fresh every run, no restart needed.

---

### 11. Authentication & Multi-User Enforcement

The app is now live in production. It has been single-user since Phase 1,
standing in a hardcoded `_STUB_USER_ID = 1` throughout `main.py` and seven
routers (`_STUB_`-prefixed per `DESIGN.md`'s own "easy to find and replace
in Phase 2" convention). Real per-account isolation is the prerequisite for
opening the app to other musicians. The schema already anticipated
multi-user (`User`/`Role`/`ContentVisibility` from Phase 1 tasks 1.5/1.5b);
what's missing is entirely the auth *behavior*, plus closing a real gap:
several detail/mutation routes (`box_detail`, `box_add_tune`, `list_edit`,
and others) don't check ownership at all today — harmless with one stub
user, a real cross-account data leak with two.

Decided: **Google OAuth** ("Sign in with Google"), not password auth (the
existing `hashed_password` column is unused — no signup ever wrote to it)
and not magic-link (would require standing up email-sending infrastructure
from scratch). Tune/setting sharing model: a shared core catalog plus
optionally-private custom tunes/settings. Teacher/student privacy:
roster-based, with link-sharing as an explicit alternative a teacher can
use instead of a formal roster.

- [ ] **11.1 — Dependencies + config module**
  Add `authlib` (OAuth client — handles CSRF state/nonce and OIDC ID-token
  verification, not worth hand-rolling) and `itsdangerous` (required by
  Starlette's `SessionMiddleware`). New `cairn/config.py`, matching the
  existing minimal `os.environ.get(...)` style of `database.py`/
  `logging_config.py` (no `pydantic-settings`): `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET_KEY`. Fail loudly at import time
  if empty outside a test context.

- [ ] **11.2 — Schema migration**
  Chains off current head `16937de1282b`.
  - `User`: add `google_sub` (String, unique, indexed, NOT NULL). Drop
    `hashed_password` entirely — confirm production has zero `User` rows
    first (no seed file creates one).
  - `Tune` + `TuneSetting`: add `visibility` (reuse the existing
    `ContentVisibility` enum — `public`/`private` used this round,
    `enrolled` reserved for 11.9), server-default `'public'`.
  - New `Enrollment` table: `id`, `teacher_id`/`student_id` (FK→users.id),
    `status` (new enum: pending/active), `TimestampMixin`,
    `UniqueConstraint(teacher_id, student_id)`.
  - New `ShareLink` table: `id`, `token` (unique, indexed,
    `secrets.token_urlsafe`), `tune_id`/`setting_id` (nullable FKs, exactly
    one set), `created_by` (FK→users.id), `TimestampMixin`.

- [ ] **11.3 — Google OAuth login/logout**
  New `cairn/routers/auth.py` (the file `AGENTS.md`'s own target tree
  already names). `GET /auth/login` → Google consent screen via authlib.
  `GET /auth/callback` → exchange code, verify ID token, look up `User` by
  `google_sub`; auto-provision on first login (no separate signup form) from
  the Google profile, default `role=student`; store `user_id` in session,
  redirect to `next` (or `/`). `POST /auth/logout` → clear session, redirect
  to login. `cairn/dependencies.py` gains `get_current_user`, raising a
  `NotAuthenticatedError` on no/invalid session; `main.py` registers an
  `@app.exception_handler` for it that redirects to
  `/auth/login?next=...` rather than a bare 401 — the standard FastAPI
  pattern for a server-rendered app. `SessionMiddleware` added in
  `main.py`; every `include_router(...)` except `auth_router` gets
  `dependencies=[Depends(get_current_user)]` — everything requires login in
  this round, no public unauthenticated browsing yet.

- [x] **11.4 — Replace `_STUB_USER_ID`, close the ownership gap**
  Delete the module-level `_STUB_USER_ID = 1` from `main.py` and all seven
  routers (`boxes.py`, `lists.py`, `tune_sets.py`, `warmups.py`,
  `practice.py`, `tunes.py`, `progress.py`); add
  `user: User = Depends(get_current_user)` to every handler; replace
  `_STUB_USER_ID` → `user.id` (thread through helper functions too, e.g.
  `practice.py`'s `_load_progress_map`, not just top-level routes). Then
  close the real gap: add an ownership-checked fetch
  (`_get_owned_box`/`_get_owned_list` — extending the pattern
  `services/lists.py`'s `activate_list` already uses) to every currently
  unchecked detail/mutation route (`box_detail`, `box_add_tune`,
  `box_remove_tune`, `box_set_setting`, `box_set_display_alias`, box
  transpose routes, `list_edit`, `list_update`, `list_deactivate`,
  `list_add_tune`, list entry setting/alias/transpose routes, `list_delete`,
  `list_remove_tune`) — 404 (not 403) on a missing row or an owner
  mismatch, so another user's resource's existence isn't revealed.

- [x] **11.5 — Nav: logged-in state**
  `cairn/templating.py` currently has no context-processor hook and
  `base.html`'s nav is hardcoded with no per-page override point. Add a
  thin `TemplateResponse`-shaped wrapper that merges in
  `request.state.user` (set once in `get_current_user`) before delegating
  to the real `Jinja2Templates` — swap the import in every router (a
  mechanical rename, not a per-call-site edit) rather than touching dozens
  of `TemplateResponse(...)` calls. Add username + a logout form to
  `base.html`'s nav, left of the existing Tuner button (same `ml-auto`
  group).

- [x] **11.6 — Test suite**
  Add a `user` fixture to `tests/test_routers/conftest.py` that creates a
  `User` row and overrides `get_current_user` via
  `app.dependency_overrides` (same mechanism already used for `get_db`) —
  replaces the copy-pasted `_seed()`-style helpers currently asserting
  `u.id == _STUB_USER_ID` across `test_dashboard.py`, `test_lists.py`,
  `test_practice.py`, `test_thesession_link.py`, `test_progress.py`,
  `test_tunes.py`, `test_boxes.py` (all of which break once that constant
  is deleted). Add: a second-user cross-account-404 test per router on the
  previously-unchecked routes (the actual regression test for 11.4's fix),
  and an unauthenticated-request redirect-to-login test.

- [ ] **11.7 — Manual setup**
  Same spirit as 10.3/10.4 — one-time, via Console:
  1. Register an OAuth consent screen + OAuth client in Google Cloud
     Console; authorized redirect URI
     `https://the-cairn.app/auth/callback` (plus a `localhost` one for
     local dev/testing).
  2. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and a generated
     `SESSION_SECRET_KEY` in `/etc/cairn/cairn.env` on the VM — same
     established override mechanism, no new plumbing needed.

**Follow-up, not built this round** (schema from 11.2 already supports
these; no routes/UI yet):

- [x] **11.8 — Tune/setting visibility enforcement**
  Filter `/tunes` listing and search to
  `visibility == public OR created_by == current_user`; a "make private"
  toggle in the tune/setting edit UI.

- [x] **11.9 — Enrollment (teacher/student roster) UI**
  Teacher-facing "invite a student" flow (email-address-based invite →
  accept screen) and a student-facing pending-invitations view;
  `enrolled`-visibility content filtered to the enrolled roster.

- [x] **11.10 — ShareLink UI**
  A "get a shareable link" action on a private tune/setting, and a public
  (unauthenticated) `/shared/{token}` view route — the one deliberate
  exception to "everything requires auth" from 11.3, scoped narrowly to
  exactly the shared item.

- [x] **11.11 — Guest read access to the public catalog**
  `GET /tunes`, `/tunes/{id}`, `/warmups`, `/warmups/{id}`, `/sets`,
  `/sets/{id}`, and `/pages/{slug}` no longer require login — a guest can
  browse the public catalog itself, not just an individual shared item.
  `get_current_user_optional` (returns `None` instead of raising) backs
  these routes; visibility enforcement is unchanged (guest = public only,
  same rule 11.8 already applies to a logged-in user). Every mutation route
  on these routers keeps its own explicit `Depends(get_current_user)`
  rather than relying on the router-level gate.

- [x] **11.12 — Guest landing page at root**
  `GET /` no longer redirects a guest straight to `/auth/login` — it
  renders `templates/landing.html` (a hero + "Sign in with Google" button,
  then the `getting-started` `Content` page's rendered body) instead of the
  personal dashboard. Uses the same `get_current_user_optional` from 11.11.
  `base.html`'s nav also gained a "Sign in with Google" link for the
  logged-out case (there was previously no visible way to log in from any
  page other than by guessing `/auth/login`).

---

### Phase 1 Complete Checklist

Before closing Phase 1:

- [x] All migrations applied cleanly to a fresh database
- [x] `make test` passes with no failures
- [x] Dashboard loads and reflects real data
- [x] A tune can be created with ABC notation and rendered in the browser
- [x] A TuneBox can be created and tunes added to it with a preferred setting
- [x] A PracticeList can be created, activated, and tunes tagged to it
- [x] A practice session can be planned (with active box and optional list), worked through, and finished
- [ ] Progress can be manually updated and affects the next session plan
- [x] No business logic lives in any route handler

---

## Phase 2 — Practice Intelligence (Planned, Not Started)

- Spaced repetition scheduling surfaced in the UI
- Per-user tempo tracking — add `target_tempo: int | None` to `StudentProgress`;
  initialise the detail-page speed slider from the user's last recorded tempo for
  that tune (falling back to the type-based default); capture slider value when
  recording a practice rating; surface tempo trend in session history charts
- Bars-to-show logic fully wired to status
- WarmupItem rotation (avoid repeating the same warmup)
- Session history view and progress-over-time charts
- TuneSet UI (create, edit, reorder members, rate flow difficulty)
- Group / ensemble readiness features
- SetReview (keep / never again verdict)
- Teacher approval workflow


## Phase 3 — Ornamentation System (Planned, Not Started)

- OrnamentDefinition library (cut, roll, cran, triplet, etc.)
- ABC transformation layer
- Linking ornaments to specific positions in a tune with explanations
- Presenting ornamentation as independent study items
- [x] **Transposition** — allow ABC notation to be rendered in any key,
      particularly useful for players on different instruments or tunings
      (e.g. Bb piper seeing D flute notation transposed to their fingering).
      Implementation notes:
      - Use `music21` for transposition logic in `abc_utils.py`
      - Transposition manipulates the ABC `K:` field directly
      - `key_root` and `key_mode` on `Tune` must be updated to match
        the transposed `K:` declaration — enforce sync in tune service
      - Stored ABC is always the original untransposed version;
        transposition is applied at render time, never stored
      - Consider O'Neill's concert pitch issue: a tune stored in Bb
        may be the same tune a flute player knows in D — transposition
        makes these reconcilable
      - UI: a key selector on the tune detail page that re-renders
        the ABC via HTMX without a full page reload

## Phase 4 — Pedagogy and Technique Layer (Design Pending)

This phase is not yet ready for implementation. The design is intentionally
incomplete and will be developed as the author's understanding of the
pedagogical requirements matures through practice and teaching.

- [ ] **Lesson sessions** — a session type on par with practice sessions
      but structured around technique instruction rather than tune learning
      and retention. Likely teacher-led. Design deferred until Phase 4
      pedagogy layer is defined. `SessionItemType.technique` is already
      in place as a building block.

### What is known and should inform earlier phases

- `OrnamentDefinition` (Phase 3) must include `functional_purpose`,
  `when_to_use`, `when_not_to_use`, `instrument_notes`, `regional_variation`
- No content storage designed in earlier phases should assume a simple
  structure — the pedagogy layer will need richer relationships

### Open design questions (resolve before implementing)

- [ ] What long-form content types are needed beyond `OrnamentDefinition`?
      (Conceptual articles? Technique guides? Listening exercises?)
- [ ] How is pedagogical content surfaced during a practice session?
      (Proactively suggested? Student-initiated? Teacher-assigned?)
- [ ] What other implicit traditional pedagogy concepts belong here?
      Running list (add to this as they surface):
      - Ornamentation functional purpose ✓
      - The "lift" and rhythmic feel of different tune types (reel vs jig vs hornpipe)
      - Regional stylistic differences
      - Tone production and breathing (instrument-specific)
      - How to listen analytically to recordings
- [x] Is this content teacher-authored, built-in, or both?
      → Both. Visibility flag on the contribution controls access,
        not a distinction between content types. See ContentVisibility
        enum (1.5b) and OrnamentDefinition notes in AGENTS.md.
- [ ] How does this layer interact with the ABC transformation system?
- [ ] **Session/regional discovery** — public, location-based listings of
      traditional music sessions contributed by teachers and experienced players.
      Potentially linkable to tune repertoire (e.g. "this session favours Clare
      style reels"). Public and search-indexed by definition since sessions are
      inherently public events. May warrant its own phase given scope.
      Open questions:
      - Who can contribute session listings — teachers only, or any verified user?
      - How is location handled — free text, structured address, or map-based?
      - How does repertoire linking work — tags, explicit tune lists, or style flags?

### Do not start this phase until

- [ ] The open design questions above are resolved
- [ ] At least one complete learning cycle has been completed with the app
      (real practice experience will inform the design better than speculation)
