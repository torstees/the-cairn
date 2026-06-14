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

- [ ] **1.7 — PracticeSession and PracticeSessionItem models**
  `PracticeSession`: id, user_id FK, started_at, ended_at (nullable), total_minutes (nullable).
  `PracticeSessionItem`: id, session_id FK, item_type (enum: warmup | learning | retention),
  tune_id FK (nullable), warmup_id FK (nullable), minutes_allocated, completed (bool),
  rating_given (int nullable).
  Generate Alembic migration.

- [ ] **1.8 — Pydantic schemas**
  Create `cairn/schemas.py` with `Create`, `Update`, and `Read` schemas for:
  `Tune`, `TuneSetting`, `TuneDifficulty`, `TuneSet`, `TuneSetMember`,
  `StudentProgress`, `WarmupItem`.
  All `Read` schemas must include `id` and `created_at`.

- [ ] **1.9 — Apply all migrations**
  Run `make migrate`. Verify `cairn.db` is created and all tables exist.
  Write a smoke test in `tests/test_models.py` that creates one instance of each
  model and commits it.

---

### 2. Tune Management

- [ ] **2.1 — Tune CRUD service**
  Create `cairn/services/tunes.py`.
  Functions: `create_tune`, `get_tune`, `list_tunes`, `update_tune`, `delete_tune`.
  `create_tune` must also create a core `TuneSetting` (is_core=True) in the same transaction.
  Enforce the invariant: a tune must always have exactly one `is_core=True` setting.
  Write tests in `tests/test_services/test_tunes.py`.

- [ ] **2.2 — Tune routes and templates**
  Router: `cairn/routers/tunes.py`, prefix `/tunes`.
  Routes:
  - `GET /tunes` — list all tunes → `tunes/index.html`
  - `GET /tunes/new` — blank form → `tunes/form.html`
  - `POST /tunes` — create tune + core setting → redirect to tune detail
  - `GET /tunes/{id}` — tune detail with settings list → `tunes/detail.html`
  - `GET /tunes/{id}/edit` — edit form → `tunes/form.html`
  - `POST /tunes/{id}` — update tune
  - `DELETE /tunes/{id}` — delete (HTMX, returns empty 200)

- [ ] **2.3 — ABC notation display**
  On `tunes/detail.html`, render the core `TuneSetting.abc_notation` using abcjs.
  The rendered score and a basic audio playback button must be visible.
  Use a `<div id="abc-render">` target and initialise abcjs in `static/js/app.js`.

- [ ] **2.4 — TuneSetting management**
  Add routes under `/tunes/{id}/settings`:
  - `GET /tunes/{id}/settings/new` — form for adding a new setting (HTMX partial)
  - `POST /tunes/{id}/settings` — create setting
  - `POST /tunes/{id}/settings/{setting_id}/set-core` — promote to core
    (must demote existing core in same transaction)
  All responses are HTMX partials; no full page reload.

- [ ] **2.5 — Tune difficulty ratings**
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

## Phase 4 — Pedagogy and Technique Layer (Design Pending)

This phase is not yet ready for implementation. The design is intentionally
incomplete and will be developed as the author's understanding of the
pedagogical requirements matures through practice and teaching.

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
