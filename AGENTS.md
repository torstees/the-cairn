# AGENTS.md — The Cairn

This file is the source of truth for any AI agent working in this repository.
Read it fully before writing or modifying any code.

---

## Repository

GitHub: https://github.com/torstees/the-cairn
Use `gh` CLI for issues, PRs, and other GitHub operations — do not construct URLs manually.

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
│   │   ├── boxes.py           # TuneBox + TuneBoxEntry management
│   │   ├── lists.py           # PracticeList + TuneListEntry management
│   │   ├── practice.py        # Practice session planning + recording
│   │   ├── progress.py        # StudentProgress updates
│   │   ├── warmups.py         # WarmupItem library
│   │   └── auth.py            # Login / session (stub in Phase 1)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── spaced_rep.py      # Spaced repetition scheduling logic
│   │   ├── boxes.py           # TuneBox + TuneBoxEntry CRUD
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
- Markdown content (Content pages, `text_blurb` warmups) supports embedded
ABC notation via fenced ` ```abc ` code blocks. `render_markdown()` in
`cairn/services/content.py` renders the markdown server-side (the fenced
block passes through as `<pre><code class="language-abc">`);
`renderMarkdownAbcBlocks()` in `static/js/app.js` finds those blocks
client-side and replaces each with an `ABCJS.renderAbc()` rendering.
Never store rendered HTML in the database — only raw markdown.

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
Progress is per **(student, tune, TuneBox)** — never global to a tune.
Unique constraint: `(user_id, tune_id, box_id)`.
The `next_suggested` field drives the spaced repetition retention queue,
scoped to the TuneBox. `bars_to_show` is derived from `status`, not stored.

### TuneBox

A `TuneBox` is a named, instrument-scoped catalog of tunes a student currently
works on or intends to learn. Each user may have multiple TuneBoxes (e.g. "Flute"
covering flute + tin_whistle, "Accordion" covering accordion). All session
planning, progress tracking, and practice list membership is scoped to a TuneBox.

A TuneBox has one or more associated `Instrument` values via `TuneBoxInstrument`.
Instruments that share technique (e.g. flute and tin_whistle) can share a box.

Tunes are added to a box via `TuneBoxEntry`, which carries an optional preferred
`TuneSetting` for that instrument context. On adding a tune, if exactly one
existing `TuneSetting` has an `instrument` matching any of the box's instruments,
auto-set it as the `TuneBoxEntry.setting_id`. If zero or multiple match, leave null.

**Setting resolution order** (most to least specific):
1. `TuneListEntry.setting_id` — active practice list override
2. `TuneBoxEntry.setting_id` — box-level preferred setting
3. First `TuneSetting` where `instrument` ∈ box's instrument list — auto-match
4. Core setting (`is_core = True`, `instrument = None`) — fallback

**Display name resolution order** (`TuneBoxEntry`/`TuneListEntry.display_alias_id`,
a `TuneAlias` a box or list can show instead of the tune's own title — #119):
1. `TuneListEntry.display_alias_id` — active practice list override
2. `TuneBoxEntry.display_alias_id` — box-level choice
3. `Tune.title` — fallback

Unlike settings, there's no instrument-based auto-match step for display
names — a tune with no alias chosen anywhere always falls straight back to
its own title. `cairn.services.tunes.resolve_display_context()` resolves
both the effective setting and display name together in one call.

### SettingProgress

Tracks progress on a specific `TuneSetting` (a particular version or arrangement)
within a box context. Created when a student tags a tune to a practice list with
a setting override and needs to start that version from scratch.

Unique constraint: `(user_id, setting_id, box_id)`.

`SettingProgress.status` always starts **below** the parent `StudentProgress.status`
for the same `(user, tune, box)` — the student is behind on this specific version.
When practice advances `SettingProgress.status` to equal `StudentProgress.status`,
the record is retired (it becomes redundant). The student may also retire it manually.

**Effective status rule**: when building session queues for a list where
`TuneListEntry.setting_id` is set, look for a `SettingProgress(user, setting, box)`
record first. If one exists, use its `status`. Otherwise fall back to
`StudentProgress(user, tune, box).status`.

### PracticeList

A named, intentional group of tunes within a TuneBox used to focus a practice
session. A PracticeList always belongs to exactly one TuneBox. Only one list per
user may be `is_active = True` at a time — enforced at the application layer.
A tune may appear on multiple lists simultaneously.

List membership is recorded in `TuneListEntry`, which carries:
- `setting_id` (nullable) — which setting to display during sessions using this
  list; also determines which `SettingProgress` record to use for effective status.

**Two list types:**

*Repertoire* — goal-driven learning list. Auto-removes a tune's `TuneListEntry`
when its effective status reaches or exceeds the list's `progress_goal`. This check
runs against **every** Repertoire list the tune belongs to whenever progress changes;
a tune may be removed from multiple lists in a single operation. Woodshed entries
are never auto-removed.

*Woodshed* — intensive focus list. Tunes are never auto-removed. Once a tune's
effective status reaches `progress_goal` it leaves the learning queue but becomes
a high-priority retention tune for sessions using that list. Woodshed-tagged tunes
in the retention queue bypass the SM-2 `next_suggested` gate and are weighted to
the top; untagged box tunes still require `next_suggested ≤ now`.

`progress_goal` must be strictly above `just_learning`. Default: `committed`.

**Session queue logic** (all scoped to the active TuneBox):

| Session type | Learning queue | Retention queue |
|---|---|---|
| Repertoire list | List entries where effective_status < goal; ordered by proximity to goal | Full box, status ≥ goal, next_suggested ≤ now; exclude session learning tunes |
| Woodshed list | List entries where effective_status < goal | Full box, status ≥ goal; woodshed-tagged tunes bypass SM-2 gate and are top-weighted; exclude session learning tunes |
| No active list | Full box, status < `committed`, weighted by proximity to `committed` | Full box, status ≥ `committed`, next_suggested ≤ now |

SM-2 fields (`interval_days`, `ease_factor`) update normally in all cases, including
when a Woodshed session triggers practice ahead of the scheduled interval.

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

1. **Every tune has exactly one `is_core = True` TuneSetting where
    `instrument` is null** — the traditional version valid for all
    instruments. Instrument-specific arrangements are non-core settings
    with `instrument` set explicitly. Never mark an instrument-specific
    setting as `is_core = True`.

2. **Progress is per student, per tune, per TuneBox.** The unique constraint on
   `StudentProgress` is `(user_id, tune_id, box_id)`. Never modify a `Tune`
   record to reflect a student's progress.

3. **Spaced repetition state lives in `StudentProgress`** (`next_suggested`,
   `interval_days`, `ease_factor`), scoped to a TuneBox.
   Never compute next review date in a route handler.

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

10. **Transposition is always applied at render time, never stored.**
    The ABC notation stored in `TuneSetting` is always the original
    untransposed version. Transposed versions are derived on request
    via `abc_utils.py` and returned to the client directly.
    Never write a transposed ABC string back to the database.

11. **`mutation_notation` format is not yet defined.**
    The field exists as a placeholder only. Do not implement any
    rendering, parsing, or transformation logic for `mutation_notation`
    until the format is decided in Phase 3. Store as raw text only.

12. **A TuneBox must have at least one instrument.** Enforce at the service
    layer; never create a TuneBox without at least one `TuneBoxInstrument` entry.

13. **Only one PracticeList per user may be `is_active = True` at any time.**
    Enforce at the application layer when activating a list.

14. **Repertoire auto-removal is triggered by any effective-status change**,
    not only explicit manual status updates. When `record_practice` or
    `set_status` is called, check every Repertoire list the tune belongs to
    (within the same box) and remove entries whose goal is now met.

15. **`SettingProgress.status` is always ≤ `StudentProgress.status`** for the
    same `(user, tune, box)`. A `SettingProgress` record that has caught up to
    the parent progress should be retired, not left in place.

16. **Session queue building is always scoped to the active TuneBox.**
    Never mix tunes from different boxes in a single session.

17. **Practice list type determines retention queue behaviour, not just learning
    queue behaviour.** See the session queue table in the PracticeList section.
    Implement retention builders as separate strategies, not one function with
    conditional overrides.

18. **Any tune/setting carrying a `thesession_tune_id` / `thesession_setting_id`
    must show an attribution link back to `https://thesession.org/tunes/{id}`
    wherever that data is displayed.** Required by TheSession-data's ODbL
    license — this must hold for any future page/view/export that surfaces
    the data, not just the ones built in TODO 8.3.

---

## Progress Status: Display Logic

| Status | Label | Bars shown | Suggested practice slot |
|---|---|---|---|
| `just_learning` | Just Learning | All bars | 10–15 min |
| `getting_there` | Getting There | All bars | 5–10 min |
| `nearly_there` | Nearly There | First 8 bars | 3–5 min |
| `session_ready` | Session Ready | First 4 bars | 2–3 min |
| `committed` | Committed | Title + key only | Spaced rep queue |
| `performance_ready` | Performance Ready | Title + key only | Spaced rep queue |
| `solo_ready` | Solo Ready | Title + key only | Spaced rep queue |

`bars_to_show` is always derived from `status` at render time — never stored.

---

## Logging

Logging is configured in `cairn/logging_config.py` and initialised once at startup in `main.py`.

### Per-module logger

Every module that logs gets its own logger at the top of the file:

```python
import logging
logger = logging.getLogger(__name__)
```

Never call `logging.info()` / `logging.debug()` directly — always use the module logger.

### Log levels

| Level | When to use |
|---|---|
| `DEBUG` | Diagnostic detail useful during development (query parameters, row counts, branch taken) |
| `INFO` | Normal business events worth knowing about in production (setting changed, tune added to list) |
| `WARNING` | Unexpected but recoverable conditions |
| `ERROR` | Failures that need investigation |

### Structured extra fields

Pass domain context as `extra={}` so it is indexed in Cloud Logging:

```python
logger.info("setting propagated", extra={"tune_id": tune_id, "list_ids": list_ids})
```

### Environment detection

| Environment | Output |
|---|---|
| GCP (Cloud Run, App Engine, etc.) | Structured JSON to stdout; ingested by Cloud Logging |
| Local interactive shell with `rich` | Rich pretty-printer with tracebacks |
| Non-interactive / CI | Plain timestamped text |

Set `CAIRN_LOG_LEVEL` env var to override the default `INFO` level.

---

## Git Workflow

- Always create a feature branch before committing (`git checkout -b fix/<slug>` or `feature/<slug>`)
- Check the current branch with `git branch` before staging any files — never assume the branch
- Push with `gh pr create` after committing; include the issue number in the PR body if applicable
- **Never commit directly to `main`**
- **Never merge or close a PR** — the user reviews, tests, and merges all PRs themselves

### Closing issues via PR

GitHub only auto-closes issues when a closing keyword (`closes`, `fixes`, `resolves`) appears
in the **PR body or a commit message** — the PR title is ignored for this purpose.
Always put the closing reference in the PR body:

```
## Summary
...

Closes #42
```

Never rely on a keyword in the PR title to close an issue.

### GitHub Issues

When creating issues with `gh issue create`, always apply the most appropriate type label:

- `bug` — something is broken or behaving incorrectly
- `enhancement` — new feature or improvement to existing behaviour
- `documentation` — docs-only change

If the user states or implies a priority level, also apply the matching label:

- `Priority - High` — blocking other work or urgent UX problem
- `Priority - Medium` — important but not blocking
- `Priority - Low` — nice to have, can wait

Example: `gh issue create --label "enhancement" --label "Priority - High" ...`

Omit the priority label when the user has not indicated one.

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
- Do not use `print()` for debug output — use `logging.getLogger(__name__)` and the appropriate level (`debug`, `info`, `warning`, `error`)

---

## Testing

- Framework: `pytest` with `pytest-asyncio`
- All tests use an in-memory SQLite database configured in `conftest.py`
- Every service function must have at least one test
- Use realistic domain data for test fixtures — actual Irish tune titles,
  correct keys, valid ABC notation snippets, plausible instrument names.
  Avoid placeholder values like "test", "foo", or "key_placeholder".
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
10. The corresponding `TODO.md` item is marked `[x]`
11. `DESIGN.md` is updated if the task changes the architecture, data model, key patterns, or domain invariants

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
make content    # Import markdown content pages from content/ (scripts/import_content.py)
make thesession-import  # Refresh TheSession.org tune reference side tables (scripts/import_thesession.py)
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
