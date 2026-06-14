# AGENTS.md — The Cairn

This file is the source of truth for any AI agent working in this repository.
Read it fully before writing or modifying any code.

---

## What This Project Is

**The Cairn** is a web application for learning and retaining traditional Irish music tunes.
It helps students manage practice time using spaced repetition, ABC notation display,
and a structured progression system from "Just Learning" to "Solo Ready".

The immediate use case is a single user (the developer) acting as their own teacher.
The architecture must support multiple students and teachers from day one —
multi-user is a near-term requirement, not an afterthought.

---

## Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.12+ | Use modern syntax (`match`, `X \| Y` unions, etc.) |
| Web framework | FastAPI | Async handlers throughout |
| Templating | Jinja2 | Server-rendered HTML; no SPA |
| Interactivity | HTMX + Alpine.js | No React, no Vue, no build step |
| CSS | Tailwind CSS (CDN) | Utility classes only; no custom CSS framework |
| ORM | SQLAlchemy 2.0 (async) | Use `mapped_column` / `Mapped` typed syntax exclusively |
| Migrations | Alembic | Never edit migration files by hand after creation |
| Database | SQLite (dev) | Path: `./cairn.db`; schema must be PostgreSQL-compatible |
| ABC rendering | abcjs (CDN) | Client-side only; version pinned in base template |
| Package manager | uv | Use `uv add`, never `pip install` |
| Task runner | Makefile | All common dev tasks must have a make target |
| Shell environment | WSL (Ubuntu) | Never use PowerShell or cmd.exe |

---

## Project Structure

```
cairn/
├── AGENTS.md                  # This file
├── TODO.md                    # Current phase task list
├── Makefile                   # Dev task targets
├── pyproject.toml             # Dependencies and project metadata
├── alembic.ini
├── alembic/
│   └── versions/              # Auto-generated only; never hand-edit
├── cairn/
│   ├── __init__.py
│   ├── main.py                # FastAPI app factory; mounts routers
│   ├── database.py            # Async engine, session factory, Base, TimestampMixin
│   ├── models.py              # All SQLAlchemy models (single file; see split rule below)
│   ├── schemas.py             # All Pydantic schemas
│   ├── dependencies.py        # FastAPI dependency functions (get_db, get_current_user)
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── tunes.py           # Tune + TuneSetting CRUD
│   │   ├── sets.py            # TuneSet CRUD
│   │   ├── practice.py        # Practice session planning + recording
│   │   ├── progress.py        # StudentProgress updates
│   │   ├── warmups.py         # WarmupItem library
│   │   └── auth.py            # Login / session (stub in Phase 1)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── spaced_rep.py      # Spaced repetition scheduling logic
│   │   ├── session_plan.py    # Practice session builder
│   │   └── abc_utils.py       # ABC notation helpers
│   └── templates/
│       ├── base.html          # HTML shell; loads HTMX, Alpine, abcjs, Tailwind
│       ├── components/        # Reusable HTMX partials (tune card, progress badge, etc.)
│       ├── tunes/
│       ├── sets/
│       ├── practice/
│       └── warmups/
├── static/
│   └── js/
│       └── app.js             # Alpine components only; minimal hand-written JS
└── tests/
    ├── conftest.py
    ├── test_models.py
    └── test_services/
        ├── test_spaced_rep.py
        └── test_session_plan.py
```

### Model file split rule
Keep all models in `models.py` until any single domain group exceeds 5 models.
At that point, convert to a `models/` package with one file per domain group
(e.g. `models/tunes.py`, `models/users.py`, `models/sets.py`).
Do not split preemptively.

---

## Naming Conventions

- **Files**: `snake_case.py`
- **Classes**: `PascalCase`
- **Functions / variables**: `snake_case`
- **Database tables**: `snake_case`, plural (e.g. `tune_settings`, `student_progress`)
- **Pydantic schemas**: suffix with `Create`, `Update`, `Read` (e.g. `TuneCreate`, `TuneRead`)
- **Router prefixes**: `/tunes`, `/sets`, `/practice`, `/progress`, `/warmups`, `/auth`
- **Template partials** (HTMX fragments): prefix with `_` (e.g. `_tune_card.html`)
- **HTMX targets**: `id` attributes in kebab-case (e.g. `tune-list`, `progress-badge-{id}`)

---

## Coding Conventions

### FastAPI
- All route handlers are `async def`
- Use dependency injection for DB sessions (`Depends(get_db)`)
- Return Pydantic schemas from API routes, not raw SQLAlchemy objects
- HTML routes return `TemplateResponse`; JSON routes return Pydantic models
- Group related routes in a router file and include it in `main.py`
- **No business logic in route handlers** — delegate everything to `services/`

The route/service boundary in practice:

```python
# WRONG — logic in route handler
@router.post("/progress/{tune_id}")
async def update_progress(tune_id: int, rating: int, db: AsyncSession = Depends(get_db)):
    progress = await db.get(StudentProgress, tune_id)
    progress.interval_days = progress.interval_days * 2.5
    progress.next_suggested = datetime.now() + timedelta(days=progress.interval_days)
    await db.commit()
    return progress

# CORRECT — route is only the HTTP boundary
@router.post("/progress/{tune_id}")
async def update_progress(tune_id: int, rating: int, db: AsyncSession = Depends(get_db)):
    return await progress_service.record_practice(db, tune_id, rating)
```

### SQLAlchemy
- Use the **2.0 style** `Mapped` / `mapped_column` syntax exclusively
- All models inherit from a shared `Base` defined in `database.py`
- All models also inherit from `TimestampMixin` (provides `created_at`, `updated_at`)
- Define `__tablename__` explicitly on every model
- Use `relationship()` with `back_populates` (never `backref`)
- Use `AsyncSession` only — never the synchronous `Session`

```python
# Canonical model pattern
class Tune(TimestampMixin, Base):
    __tablename__ = "tunes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    tune_type: Mapped[TuneType] = mapped_column(Enum(TuneType), nullable=False)

    settings: Mapped[list["TuneSetting"]] = relationship(back_populates="tune")
```

### Enums
- Define all domain enums in `models.py` using `enum.Enum`
- All enums inherit from `LabelledEnum` (defined in `models.py`) which
  provides a `.label` property via `value.replace("_", " ").title()`
- Never define `.label` directly on individual enum classes
- Keep storage values as `snake_case` strings; `.label` handles presentation

```python
class LabelledEnum(str, enum.Enum):
    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

class ProgressStatus(LabelledEnum):
    just_learning     = "just_learning"
    getting_there     = "getting_there"
    nearly_there      = "nearly_there"
    session_ready     = "session_ready"
    committed         = "committed"
    performance_ready = "performance_ready"
    solo_ready        = "solo_ready"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()
```

### Alembic
- Generate migrations with: `alembic revision --autogenerate -m "short description"`
- Apply with: `alembic upgrade head`
- **Never edit a migration file after it has been committed**
- If a migration is wrong, generate a new one to correct it

### HTMX + Templates
- Prefer HTMX attributes for all server interactions
- Alpine.js is for UI state only (open/closed, active tab, toggle)
- Never fetch data from JavaScript — that is HTMX's responsibility
- Every HTMX partial must function as a standalone renderable fragment
- Inline ABC notation in text content is delimited with [abc]...[/abc] markers.
The `render_inline_abc()` helper in `abc_utils.py` converts these to
elements for ABCJS rendering. Use this pattern for warmup descriptions
and pedagogy content. Never store rendered HTML in the database.

---

## Domain Model: Key Entities

### Tune / TuneSetting
A `Tune` is the abstract entity (title, type, key). A `TuneSetting` is a specific
ABC notation version of that tune. One setting must always be flagged `is_core = True`.
Core settings contain no ornamentation unless it is structurally central to the tune.
Ornamented versions are separate settings, never mutations of the core.

### TuneSet
An ordered collection of one or more tunes intended to be played together.
There is no maximum length — sets of 5+ tunes are valid.
Member order is significant and must be preserved.

TuneSet carries two difficulty ratings:

| Field | Display name | Meaning | Source |
|---|---|---|---|
| `peak_difficulty` | Peak Difficulty | Difficulty of the hardest tune in the set for a given instrument | Derived: `MAX` of member `TuneDifficulty.difficulty` |
| `flow_difficulty` | Flow Difficulty | How demanding the transitions and set organisation are | Manual rating, nullable until set |

`peak_difficulty` is computed at query time, never stored.
`flow_difficulty` uses the same 1–5 scale as tune difficulty but measures different things:

| Rating | Flow Difficulty means |
|---|---|
| 1 | Flows naturally; transitions feel obvious |
| 2 | Minor adjustment needed between tunes |
| 3 | Transitions require deliberate practice |
| 4 | Key/meter shifts or similar-feel confusion demand significant work |
| 5 | Expert-level set construction; very demanding transitions |

Mixed-meter sets (e.g. jig into reel) are valid but must have `flow_difficulty`
set manually. The auto-generator must never produce mixed-meter sets.

### StudentProgress
Progress is always per student per tune — never global to a tune.
The `next_suggested` field drives the spaced repetition retention queue.
`bars_to_show` is derived from `status`, not stored.

### Difficulty
Difficulty is always per instrument. Never put a single difficulty score
on `Tune` itself. Use `TuneDifficulty` with an instrument enum.

---

## Planned: Pedagogy and Technique Layer

This section is intentionally incomplete. A pedagogical content system is planned
but not yet fully designed. Do not make structural decisions that would close off
this design space.

### What is known

The app intends to go beyond tune notation and ornamentation reference to provide
rich explanations of *why* traditional music techniques exist and *when* to use them.
The core insight driving this: ornamentation in Irish traditional music is functional,
not decorative. Each ornament solves a specific musical problem (e.g. rolls maintain
pulse on sustained notes; cuts and strikes accent and articulate). Students who
understand the function will use ornaments musically and spontaneously; students
who only learn where ornaments appear in specific tunes are working from a script.

This extends beyond ornamentation to any technique or concept that traditional
pedagogy leaves implicit but that adult learners benefit from having made explicit.

### What this implies for existing models

`OrnamentDefinition` must support this richer pedagogical intent. At minimum it needs:
- `functional_purpose` — why this ornament exists musically
- `when_to_use` — the musical conditions that call for it
- `when_not_to_use` — equally important
- `instrument_notes` — behaviour varies significantly across instruments
- `regional_variation` — e.g. Sligo rolls vs Clare rolls

### What is not yet designed

- A broader long-form content type for conceptual scaffolding
  (e.g. "What is pulse and why does it matter", "Why pipes and flute ornament
  differently from fiddle", "How to listen for ornamentation in recordings")
- How this content is surfaced during practice sessions
- Whether this content is teacher-authored, student-facing only, or both
- What other implicit traditional pedagogy concepts belong here beyond ornamentation
  (rhythmic feel, regional style, tone production, breathing, etc.)

### Constraints for the agent

- Do not implement `OrnamentDefinition` without the fields listed above
- Do not design any content storage as a simple key-value or tag system —
  the pedagogy layer will need richer structure than that
- Do not assume ornamentation is the only concept this layer will cover
- Leave the content type for long-form conceptual articles as an open question
  until the design is ready

## Domain Rules (Invariants — Never Violate)

1. **Every tune has exactly one `is_core = True` TuneSetting at all times.**
   Enforce at the service layer, not only at the database layer.

2. **Progress is per student per tune.** Never modify a `Tune` record to
   reflect a student's progress.

3. **Spaced repetition state lives in `StudentProgress`** (`next_suggested`,
   `interval_days`, `ease_factor`). Never compute next review date in a route handler.

4. **ABC notation is never mutated to add ornamentation.** Ornamented versions
   are always separate `TuneSetting` records or derived at render time.

5. **Difficulty is per instrument.** All difficulty queries must specify an instrument.

6. **TuneSet member order is always preserved.** Use an explicit `order`
   integer column on the join model, not insertion order.

7. **`peak_difficulty` for a set is always `MAX` of member tune difficulties**
   for a given instrument. Never store it; always compute it.

8. **Mixed-meter sets require a manual `flow_difficulty` rating.**
   The session planner must never auto-generate mixed-meter sets.

9. **`flow_difficulty` and tune `difficulty` use the same 1–5 scale
   but are never interchangeable.** Always use field names and display
   labels to distinguish them in UI and queries.

---

## Progress Status: Display Logic

| Status | Label | Bars shown | Suggested practice slot |
|---|---|---|---|
| `just_learning` | Just Learning | All bars | 10–15 min |
| `getting_there` | Getting There | First 8 bars | 5–10 min |
| `nearly_there` | Nearly There | First 4 bars | 3–5 min |
| `session_ready` | Session Ready | First 2 bars | 2–3 min |
| `committed` | Committed | Title only | Spaced rep queue |
| `performance_ready` | Performance Ready | Title only | Spaced rep queue |
| `solo_ready` | Solo Ready | Title only | Spaced rep queue |

`bars_to_show` is always derived from `status` at render time — never stored.

---

## What the Agent Must Not Do

- Do not install packages with `pip` — use `uv add`
- Do not create migration files unless explicitly instructed
- Do not add JavaScript frameworks beyond HTMX and Alpine.js
- Do not write inline `<style>` blocks — use Tailwind utility classes
- Do not put business logic in route handlers — it belongs in `services/`
- Do not use synchronous `Session` — only `AsyncSession`
- Do not use `backref` — use `back_populates`
- Do not modify any file under `alembic/versions/`
- Do not store computed values (`peak_difficulty`, `bars_to_show`) as columns
- Do not generate mixed-meter sets automatically
- Do not split `models.py` into a package unless the 5-model-per-domain rule is met
- Do not use PowerShell or cmd.exe — all shell commands must be run via WSL

---

## Testing

- Framework: `pytest` with `pytest-asyncio`
- All tests use an in-memory SQLite database configured in `conftest.py`
- Every service function must have at least one test
- Route tests use FastAPI's `AsyncClient` from `httpx`
- Run tests: `make test`

---

## Definition of Done

A task is complete when:

1. The code runs without errors (`make dev` starts cleanly)
2. `make test` passes with no failures
3. `make lint` passes with no violations
4. Any new model has a corresponding Alembic migration generated (not necessarily applied)
5. Any new route has a corresponding Jinja2 template or returns valid JSON
6. No business logic lives in a route handler
7. All new enums have a `.label` property
8. No rule in "What the Agent Must Not Do" has been violated
9. The agent has not split `models.py` unless the split rule threshold was reached

---

## Makefile Targets

```makefile
make dev        # Start uvicorn with --reload
make test       # Run pytest
make migrate    # alembic upgrade head
make migration  # alembic revision --autogenerate (prompts for -m message)
make shell      # Open Python REPL with app context
make lint       # ruff check + ruff format --check
make fmt        # ruff format (auto-fix)
```

---

## UX Principles
Aesthetic: warm pub/cottage kitchen — earthy tones, serif typography, soft textures.
Primary device: iPad in landscape, used at a piano or music stand.
Touch targets must be generous. ABC notation must be legible at arm's length.
Navigation should be minimal — content first.

## Current Phase

**Phase 1 — Solo Tool**

Scope: single user, tune + setting management, ABC notation display,
manual progress tracking, basic practice session planning.
Sets schema is defined in Phase 1 but UI is Phase 2.
No teacher/student workflow, no group features yet.

See `TODO.md` for the current task list.
