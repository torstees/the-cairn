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

- [ ] **6b.4 — TuneSet detail/read page**
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

- [ ] **6b.5 — Extend seed scripts to cover all content types**
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

- [ ] **7.1 — Content model, import pipeline, and service**
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

- [ ] **7.2 — Content rendering and routes**
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

- [ ] **7.3 — Warmup text blurb: markdown with embedded ABC notation**

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

### Phase 1 Complete Checklist

Before closing Phase 1:

- [ ] All migrations applied cleanly to a fresh database
- [ ] `make test` passes with no failures
- [ ] Dashboard loads and reflects real data
- [ ] A tune can be created with ABC notation and rendered in the browser
- [ ] A TuneBox can be created and tunes added to it with a preferred setting
- [ ] A PracticeList can be created, activated, and tunes tagged to it
- [ ] A practice session can be planned (with active box and optional list), worked through, and finished
- [ ] Progress can be manually updated and affects the next session plan
- [ ] No business logic lives in any route handler

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
- [ ] **Transposition** — allow ABC notation to be rendered in any key,
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
