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

- [ ] **3.1 — Spaced repetition service**
  Create `cairn/services/spaced_rep.py`.
  Implement `next_review(confidence, interval_days, ease_factor) -> (float, float)`
  using a simplified SM-2 variant.
  Implement `record_practice(db, user_id, tune_id, confidence) -> StudentProgress`.
  Write thorough tests in `tests/test_services/test_spaced_rep.py` covering
  all confidence values (1–5) and edge cases (first practice, reset on low confidence).

- [ ] **3.2 — Progress routes**
  Router: `cairn/routers/progress.py`, prefix `/progress`.
  Routes:
  - `GET /progress` — all tunes with current status for the current user
  - `POST /progress/{tune_id}` — record a practice rating (HTMX, returns updated badge)
  - `POST /progress/{tune_id}/status` — manually advance or set status

- [ ] **3.3 — Progress badge component**
  Create `cairn/templates/components/_progress_badge.html`.
  Displays `status.label` with a colour-coded indicator.
  Used on tune detail and practice session views.
  Must be renderable as a standalone HTMX partial.

---

### 4. Practice Session Planner

- [ ] **4.1 — Session plan service**
  Create `cairn/services/session_plan.py`.
  Implement `build_session(db, user_id, total_minutes) -> list[PracticeSessionItem]`.
  Logic:
  - Allocate ~10% to warmup (at least 1 item)
  - Allocate remaining time across learning tunes (status < committed) and
    retention tunes (next_suggested <= now), weighted by status
  - Lower status = longer slot (see AGENTS.md progress table)
  - Never include mixed-meter auto-generated sets
  Write tests covering short sessions (15 min), standard sessions (45 min),
  and edge cases (no tunes due for retention, all tunes committed).

- [ ] **4.2 — Practice session routes and templates**
  Router: `cairn/routers/practice.py`, prefix `/practice`.
  Routes:
  - `GET /practice/plan` — form to enter total minutes → `practice/plan.html`
  - `POST /practice/plan` — generate and display session plan → `practice/session.html`
  - `POST /practice/session/{id}/item/{item_id}/complete` — mark item done (HTMX)
  - `POST /practice/session/{id}/finish` — close session, record total time

- [ ] **4.3 — Dashboard**
  Create `cairn/templates/dashboard.html` as the root `/` route.
  Show: tunes due for retention today, current learning tunes with status,
  a "Start Practice" button linking to `/practice/plan`.

---

### 5. Warmup Library

- [ ] **5.1 — Warmup CRUD**
  Router: `cairn/routers/warmups.py`, prefix `/warmups`.
  Basic CRUD for `WarmupItem`: list, create, edit, delete.
  Content field renders as ABC notation if `warmup_type == scale or snippet`,
  or as plain text if `warmup_type == text_blurb`.

---

### Phase 1 Complete Checklist

Before closing Phase 1:

- [ ] All migrations applied cleanly to a fresh database
- [ ] `make test` passes with no failures
- [ ] Dashboard loads and reflects real data
- [ ] A tune can be created with ABC notation and rendered in the browser
- [ ] A practice session can be planned, worked through, and finished
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
