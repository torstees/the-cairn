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
- Use `str` as a mixin so values serialize naturally to JSON
- Always add a `.label` property for human-readable display in templates
- Keep storage values as `snake_case` strings; `.label` handles presentation

```python
class ProgressStatus(str, enum.Enum):
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
3. Any new model has a corresponding Alembic migration generated (not necessarily applied)
4. Any new route has a corresponding Jinja2 template or returns valid JSON
5. No business logic lives in a route handler
6. All new enums have a `.label` property
7. No rule in "What the Agent Must Not Do" has been violated
8. The agent has not split `models.py` unless the split rule threshold was reached

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

## Current Phase

**Phase 1 — Solo Tool**

Scope: single user, tune + setting management, ABC notation display,
manual progress tracking, basic practice session planning.
Sets schema is defined in Phase 1 but UI is Phase 2.
No teacher/student workflow, no group features yet.

See `TODO.md` for the current task list.

> ![note] You Said
>  I like this a lot, but I have a few questions: 
>  1) I'm not a fan of multiple classes in the same file for the model, but am OK with it if it is more efficient for the Agent. However, what determines when do the split? 
>  2) I like make and did C++ for many years, but I'm curious if this is a recent comeback due to the agentic stuff, or is there another reason? 
>  3) I've never used alembic before, does it manage the migrations by way of inspecting the SQLA models or does it somehow manipulate those models? I'm assuming that sits between the model and the schema, but just checking that I understand things correctly 
>  4) I think I understand the comments relating to routes vs services, but a little background could be helpful. I've used flask quite a bit, but haven't had a chance to try fast api 
>  5) Something I had forgotten about as far as the requirements go. There must be a thing called sets which will be a combination of one or more tunes that can be played together as a unit. I can imagine this could be another unique feature which could try putting the tunes for repetition together as a set and giving the user the ability to rate it 'keep' or 'never again'. 
>  6) I would like two additional ProgressStatus enums: performance_ready and solo_ready. Idea being if you are ready to play it in front of a crowd with a small group or entirely on your own. So, definitely more work put into those than committed to memory

## Claude responded: Great questions — let me work through each one:

Great questions — let me work through each one:

---

**1. Single file vs. splitting models**

The agent efficiency argument is real but secondary. The better rule is: **split when a file has more than one reason to change at the same time.** For models, that usually means when you have a clear subdomain boundary — e.g. everything related to `User`/`Auth` could live in `models/auth.py` while tune-related models live in `models/tunes.py`. The signal to split is when you find yourself scrolling past unrelated models to find the one you want, or when two developers (or two agent tasks) would plausibly need to edit the file simultaneously.

For Phase 1, one file is correct. I'd add a note to `AGENTS.md` that says "split into a `models/` package when any single domain group exceeds ~5 models" so the agent knows the rule rather than making a judgment call.

---

**2. Makefile**

Not really a comeback — `make` never left backend/systems work. The reason it's good here specifically is that agents need a stable, unambiguous vocabulary for "how do I run this." If you just write `uvicorn cairn.main:app --reload --port 8000` in your README, the agent might vary how it invokes things across sessions. `make dev` is a stable contract. It also means you can change what `make dev` _does_ (swap uvicorn for granian, add env var loading, etc.) without changing any prompt or any agent instruction.

---

**3. Alembic**

Your mental model is correct. Alembic sits between your SQLAlchemy models and the actual database. It works by **comparing your models (via SQLAlchemy metadata) against the current database schema**, then generating Python migration scripts that describe the diff. It does not touch your model code at all — it only reads from it. The flow is:

```
You change models.py
       ↓
alembic revision --autogenerate   # Alembic reads models, reads DB, diffs them
       ↓
alembic/versions/abc123_add_tune_settings.py  # Generated script
       ↓
alembic upgrade head              # Runs that script against the DB
```

The migration file is plain Python with `op.create_table()`, `op.add_column()` etc. That's why you never hand-edit them after the fact — the DB and the migration history have to stay in sync, and editing breaks the chain.

---

**4. Routes vs. Services in FastAPI**

In Flask you often write everything in the view function because Flask doesn't nudge you either way. FastAPI doesn't enforce separation either, but the pattern matters more at scale. Think of it this way:

- **Route handler** = the HTTP boundary. Its only job is: parse the request, call a service, return a response. It knows about HTTP status codes, request/response shapes, and nothing else.
- **Service function** = the business logic. It knows about your domain rules, your database, your algorithms. It has no idea it's being called from HTTP — it could equally be called from a CLI command, a test, or a background job.

Concrete example:

python

```python
# BAD — logic in route handler
@router.post("/progress/{tune_id}")
async def update_progress(tune_id: int, rating: int, db: AsyncSession = Depends(get_db)):
    progress = await db.get(StudentProgress, tune_id)
    progress.confidence = rating
    interval = progress.interval_days * (2.5 + 0.1 - (5 - rating) * 0.08)
    progress.next_suggested = datetime.now() + timedelta(days=interval)
    await db.commit()
    return progress

# GOOD — route delegates to service
@router.post("/progress/{tune_id}")
async def update_progress(tune_id: int, rating: int, db: AsyncSession = Depends(get_db)):
    return await progress_service.record_practice(db, tune_id, rating)

# services/spaced_rep.py — testable in isolation, no HTTP knowledge
async def record_practice(db: AsyncSession, tune_id: int, rating: int) -> StudentProgress:
    progress = await db.get(StudentProgress, tune_id)
    progress.confidence = rating
    progress.interval_days, progress.ease_factor = next_review(rating, progress.interval_days, progress.ease_factor)
    progress.next_suggested = datetime.now() + timedelta(days=progress.interval_days)
    await db.commit()
    return progress
```

The service version is trivial to unit test without spinning up HTTP at all.

---

**5. Sets**

Love this — it's musically authentic too, since traditional sessions almost always play tunes in sets of 2-3. A few design thoughts before I add it to the model:

- A `Set` is an **ordered** collection of tunes (order matters — the set has a feel and a key flow)
- Sets should have their own `StudentProgress`-equivalent, since you can know a tune individually but fall apart when chaining it
- The "keep / never again" rating you described is essentially a binary variant of the spaced rep rating — I'd model it as a `SetReview` with a `verdict` enum rather than shoehorning it into the numeric confidence scale
- A set's difficulty is probably derived (max of its tunes' difficulties) rather than stored separately

---

**6. Extended ProgressStatus**

Here's the updated enum with your additions slotted in at the right positions in the progression:

python

```python
class ProgressStatus(str, enum.Enum):
    just_learning    = "just_learning"     # Full notation, long practice slot
    getting_there    = "getting_there"     # First 8 bars shown
    nearly_there     = "nearly_there"      # First 4 bars shown
    session_ready    = "session_ready"     # Title + 2 bars; ready for a session
    committed        = "committed"         # In spaced repetition, title only
    performance_ready = "performance_ready" # Can hold it together in a small group
    solo_ready       = "solo_ready"        # Can carry it alone, front to back
```

`committed → performance_ready → solo_ready` is a clean arc. The distinction also implies something about ornamentation readiness — you probably don't worry about varying the tune until `performance_ready` at the earliest. Worth encoding that in the display logic later.

---

Want me to update the `AGENTS.md` with the Sets domain rules and the extended enum, then move on to `TODO.md` and the project scaffold?

> [!note] You Said
> Let me add that I don't want there to be an official upper limit to the length of a set, since I have definitely heard great recordings with 5 tunes in them, though 3 is far more common. I agree, there should be the ability for students to work on sets as a unit of work. I hadn't thought of it from a performative standpoint, but that is definitely a real thing...starting on the last few bars and working to get the transition smooth. Good catch!
> 
> I'm curious about the naming of the status. Why are the strings snake case when there is a snake_case attribute? Happy to accept a reasonable answer, just curious and didn't notice it when I was reviewing the file.
>
> Your suggestion for sets pushes them up as a first class CRUD type entity from a fairly eary stage, though, maybe not one fo the first models to work on.
> 
> For set/difficulty, I think by default, you are correct. But, there are plenty of examples where recordings start with a jig (or other 3) and then switch at some point to a reel (or other 4)...that's hard! I don't think we want the automatic set generator to torture students, but it definitely should be possible for someone to add them
> 
> This also reminds me that there might be some value in adding groups of users that allows a group ot easily identify which tunes they may be able to play at an upcoming performance. So, if 3 out of the four of them know Ballintore Fancy, that fourth person could easily start woodshedding.

## Claude responded: All great points.

All great points. Let me work through them:

---

**On the snake_case string values**

Honest answer: it's a convention carried over from database storage and API serialization. When this enum gets stored in SQLite or sent as JSON, the string value is what travels — and `"just_learning"` is unambiguous, readable, and safe across every layer (Python, SQL, JSON, HTML data attributes).

But your instinct is valid — the redundancy is a mild code smell. The alternative is to let the value be a cleaner human-readable string:

python

```python
class ProgressStatus(str, enum.Enum):
    just_learning     = "Just Learning"
    getting_there     = "Getting There"
    nearly_there      = "Nearly There"
    session_ready     = "Session Ready"
    committed         = "Committed"
    performance_ready = "Performance Ready"
    solo_ready        = "Solo Ready"
```

The tradeoff: now your database stores `"Just Learning"` with a space, which means you can't use it raw in CSS classes or HTML `id` attributes without a transform. The snake_case version works everywhere without conversion.

A third option that some teams prefer — keep snake_case values for storage, add a separate display property:

python

```python
class ProgressStatus(str, enum.Enum):
    just_learning = "just_learning"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

# Usage: status.label → "Just Learning"
```

That's probably the cleanest. I'll add that pattern to `AGENTS.md` as the convention for all enums that need display names.

---

**On set length**

Agreed — no upper limit. The data model just needs `order` on the join, and the UI can handle any length. I'll note "no enforced maximum" explicitly in the domain rules so the agent doesn't add a check constraint.

---

**On mixed meter sets**

Good distinction. The rule should be:

- **Auto-generated sets**: same meter only, keys should be compatible (same or closely related)
- **Manually composed sets**: anything goes, difficulty is explicitly set rather than derived
- **Derived difficulty**: only applies when all tunes share a meter; mixed-meter sets require a manual difficulty rating

That's a meaningful enough rule to go into the domain section of `AGENTS.md`.

---

**On groups / ensemble readiness**

This is a genuinely useful feature and fits naturally into the architecture. A `Group` is just a named collection of `User`s, and the interesting query is:

> "For this group, show me all tunes where at least N members are at `session_ready` or above"

That's a clean aggregate query, and the "fourth member could start woodshedding" workflow falls right out of it. It also ties back to Sets nicely — a group might curate a shared set list for a performance.

I'd frame it as a Phase 2 feature (after multi-user auth is solid) but design the schema to support it from the start, since adding a `group_memberships` join table later without planning for it can be awkward.

---

**On Sets as first-class CRUD**

Agreed on timing. I'd put Sets in Phase 1 schema (so the migration is there from the start) but Phase 2 UI. The model needs to exist before progress data does, or you'll have a migration mess later.

Here's the updated priority order that reflects everything:

**Phase 1 schema** (model + migration, even if no UI yet): `Tune`, `TuneSetting`, `TuneDifficulty`, `WarmupItem`, `StudentProgress`, `PracticeSession`, `PracticeSessionItem`, `TuneSet`, `TuneSetMember`

**Phase 1 UI**: Tune CRUD + ABC display, manual progress tracking, basic session planner

**Phase 2 schema**: `Group`, `GroupMembership`, `SetReview`

**Phase 2 UI**: Sets workflow, group ensemble view, spaced repetition scheduling

---

Want me to now produce the updated `AGENTS.md` incorporating all of this, plus a `TODO.md` that breaks Phase 1 into agent-sized tasks you can hand off one at a time?

> [!note] You Said
> A couple notes: 
> 1) I like your decision relating to enum string values. I think that's the best approach to provide the property. 
> 2) Let's have 2 difficulty ratings for sets. One is derived from the tune's difficulty at the instrument level and another is specific to the set itself and relates more to the tune's organization. There are other reasons for those transitions to trip folks up. If they are too similar, it can be really hard to switch or if the end or beginning of a pairing are too jarring, that might be worth rating as more difficulty so the person can know to plany more time working through it

That's a really nuanced distinction and it maps to something real — a set of three easy tunes in jarring keys is harder to play well than a set of three hard t…

That's a really nuanced distinction and it maps to something real — a set of three easy tunes in jarring keys is harder to play well than a set of three hard tunes that flow naturally. Let me name these clearly before we encode them:

- **Technical difficulty** — derived from the member tunes' per-instrument difficulty ratings. How hard are the tunes themselves to play?
- **Set cohesion difficulty** — manually rated, reflects how demanding the _transitions_ and _organization_ are. Similar-feeling tunes that blur together, awkward key shifts, meter changes, tempo mismatches — all of this lives here.

A set could be low technical / high cohesion (three easy reels that somehow feel jarring back to back) or high technical / low cohesion (three hard tunes that flow like water). Both matter and neither predicts the other.

I'd model it like this:

python

```python
class TuneSet(Base):
    # ... other fields

    # Derived: max (or average — worth deciding) of member tunes'
    # TuneDifficulty.difficulty for a given instrument
    # NOT stored — computed at query time

    cohesion_difficulty: Mapped[int | None] = mapped_column(
        Integer, nullable=True  # Null until manually rated
    )
    cohesion_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True  # "Key shift from Dmaj to Amin is abrupt"
    )
```

**One decision to make**: should technical difficulty be the **max** of the member tunes or the **average**?

Max is more honest for a student — the set is only as easy as its hardest tune. But average might be more useful for the auto-generator when it's trying to match a student's current level. I'd lean toward storing both as computed values: max for display ("this set contains a grade 4 tune"), average for the session planner's matching algorithm.

Also worth noting: `cohesion_difficulty` uses the same 1–5 scale as tune difficulty, but the _meaning_ is different. Should we give it its own label system? Something like:

|Rating|Tune difficulty means|Set cohesion means|
|---|---|---|
|1|Very easy|Flows naturally, obvious transitions|
|2|Easy|Minor adjustment needed|
|3|Moderate|Requires deliberate practice on transitions|
|4|Hard|Meter/key shifts demand significant work|
|5|Very hard|Expert-level set construction|

That table is worth putting in `AGENTS.md` so the agent never conflates the two scales when generating UI labels or session time estimates.

---

Shall I now write the final updated `AGENTS.md` and the `TODO.md` incorporating everything from this whole conversation? We've got enough decisions made to produce something solid that you could drop into a repo today and start working from.

> [!note] You Said
I like the choices you've made on both counts. I do like the choice of names for these sores for a model, but they should probably have different names for musicians who are using the app. As for the difficulty, that is a really good point and I think going with the maximum difficulty makes sense.

## Good call on both.

Good call on both. Let me nail down the display names before we write the final documents.

**Technical difficulty** is really about the hardest tune in the set — from a musician's perspective that's something like "ceiling" or "peak difficulty." Something like **"Peak Difficulty"** feels honest and musical people will immediately understand it.

**Cohesion difficulty** is about how demanding the set is _as a set_ — the transitions, the flow, the organization. Musicians talk about sets "sitting well together" or feeling "comfortable." I'd lean toward something like **"Flow Difficulty"** or **"Transition Difficulty"**.

My instinct is **"Flow Difficulty"** — it's the more musical word and captures both the key transitions _and_ the similar-feel problem you described earlier. "Transition Difficulty" is more precise but a bit clinical.

Do either of those work, or do you have a different term in mind? You're closer to the musician vocabulary here than I am — if there's a term session players actually use when they talk about whether a set sits well, that would be better than anything I'd invent.

Once you confirm those names I'll write the complete final `AGENTS.md` and `TODO.md` in one shot. At that point you'll have everything you need to initialize the repo and hand the first real task to the agent.

> [!note] You said
> I think Technical difficult is fine. The cohesion was my concern. The fiddlers I know would probably raise an eyebrow or two on seeing that. I agree, Flow Difficulty sounds right to me as well.
## "Peak Difficulty" and "Flow Difficulty" it is.

"Peak Difficulty" and "Flow Difficulty" it is. Those will read naturally to any musician using the app.

Let me now write the complete final versions of both documents:

Created 2 files, ran a command, read a file

Created 2 files, ran a command, read a file

A few things worth noting about how `TODO.md` is structured, because this directly teaches the agentic workflow:

**Each task is one agent session.** Task `2.1` is a complete, verifiable unit of work — the agent writes the service, you run the tests, you review the output, done. Task `2.2` builds on it. If you hand the agent `2.1` and `2.2` together, you lose the ability to catch a problem in `2.1` before it propagates.

**The dependency order is intentional.** Models before schemas, schemas before routes, services before routes, routes before templates. An agent that skips ahead will write code that imports things that don't exist yet.

**The "Phase 1 Complete Checklist" at the bottom is your integration test.** After the agent finishes individual tasks, you run through that list manually. It catches cases where each task passed in isolation but something broke in the wiring between them.

---

Your next concrete step is: drop both files into the root of a new git repo, then hand the agent task `0.1` with a prompt like:

> _"Complete task 0.1 from TODO.md. Read AGENTS.md first. Use `uv` to initialise the project and create `pyproject.toml` with all listed dependencies."_

That's it. The agent has everything it needs. Let me know when you're ready to work through the first few tasks together or if you want to talk through how to write the prompts effectively.
