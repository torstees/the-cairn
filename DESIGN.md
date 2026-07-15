# The Cairn — Design Reference

A living document covering architecture, data model, and key patterns.
Update this alongside any PR that changes structure or introduces a new pattern.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Web framework | FastAPI (async) |
| Templates | Jinja2 |
| ORM | SQLAlchemy 2.0 async (`aiosqlite`) |
| Migrations | Alembic |
| Frontend reactivity | HTMX 2.0.4 + Alpine.js v3 |
| Styling | Tailwind CSS (CDN) |
| ABC rendering / playback | abcjs (CDN) |
| Test runner | pytest with `asyncio_mode = "auto"` |
| Package / task runner | `uv` |

Database is SQLite (`cairn.db`) for all phases. The async driver means every
database call must be `await`ed and live inside an `async` function.

---

## Layer Architecture

```
Browser
  ├─ HTMX        declarative HTTP requests, partial DOM replacement
  ├─ Alpine.js   local component state (dropdowns, toggles, forms)
  └─ app.js      abcjs score rendering and audio playback

        ↕  HTTP

FastAPI routers  (cairn/routers/)
  Route handlers validate inputs, call services, return template responses.
  No business logic lives here — only routing and template rendering.

        ↕  async function calls

Service layer  (cairn/services/)
  All business logic. Functions receive an AsyncSession and return model
  instances or primitives. Never return HTTP responses or render templates.

        ↕  SQLAlchemy 2.0 async

Models  (cairn/models.py)
  Single file. All SQLAlchemy ORM models and Python enums.

        ↕

SQLite  (cairn.db)
```

---

## Directory Structure

```
cairn/
  main.py           app factory, router mounts, static files
  config.py         GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / SESSION_SECRET_KEY
  database.py       async engine, AsyncSession factory, Base, TimestampMixin
  dependencies.py   get_db, get_current_user FastAPI dependencies
  models.py         all SQLAlchemy models and enums
  schemas.py        Pydantic Create / Update / Read schemas
  templating.py     Jinja2 environment setup
  routers/
    auth.py         /auth — Google OAuth login/callback/logout
    tunes.py        /tunes
    boxes.py        /boxes
    lists.py        /lists
    progress.py     /progress
  services/
    tunes.py        tune CRUD, sort_key(), alias management
    boxes.py        tune box CRUD, preferred setting
    lists.py        practice list CRUD, activate/deactivate
    spaced_rep.py   SM-2 scheduling, record_practice, get_effective_status
    abc_utils.py    build_abc() — sole ABC assembler
  templates/
    base.html
    tunes/
      index.html, detail.html, form.html
      partials/  _tune_list.html, _settings.html, _aliases.html, _difficulty.html
    boxes/
      index.html, detail.html, form.html
      partials/  _tune_row.html
    lists/
      index.html, detail.html, form.html
    components/
      _progress_badge.html
alembic/
  versions/         one file per migration, named with a short description
static/
  js/app.js
tests/
  conftest.py       async DB session fixture
  test_services/
  test_routers/
```

---

## Data Model

### Enums

| Enum | Values |
|---|---|
| `TuneType` | reel, jig, slip_jig, hornpipe, polka, slide, strathspey, waltz, air, march, barndance |
| `Instrument` | flute, tin_whistle, uilleann_pipes, fiddle, concertina, accordion, banjo, mandolin, bouzouki, guitar, bodhrán, harp |
| `ProgressStatus` | just_learning → getting_there → nearly_there → session_ready → committed → performance_ready → solo_ready |
| `OrnamentationLevel` | none, minimal, moderate, full |
| `WarmupType` | scale, snippet, text_blurb |
| `Role` | guest\*, student, teacher, admin |
| `ContentVisibility` | public, enrolled, private |
| `ContentType` | page, lesson, tutorial, technique_guide |
| `SessionItemType` | warmup, learning, retention, technique |
| `KeyRoot` | full chromatic set including enharmonics (C, C#, Db, D, Eb, E, F, F#, Gb, G, Ab, A, Bb, B) |
| `KeyMode` | major, minor, dorian, mixolydian, lydian |
| `PracticeListType` | repertoire, woodshed |

\* `guest` is never stored in the `users` table — it exists only for authorization logic.

All enums inherit `LabelledEnum(str, enum.Enum)` which provides a `.label`
property that title-cases the value and replaces underscores with spaces.

### Entity Relationships

```
User
 ├─< TuneBox              one user, many boxes
 │    ├─< TuneBoxInstrument   composite PK (box_id, instrument); box must have ≥ 1
 │    └─< TuneBoxEntry        links a tune into the box + optional preferred setting
 ├─< PracticeList          one user, many lists; at most one is_active at a time
 │    └─< TuneListEntry        links a tune into the list + optional display setting
 ├─< StudentProgress        one record per (user, tune, box); SM-2 state lives here
 └─< PracticeSession
      └─< PracticeSessionItem

Tune
 ├─< TuneSetting           one must be is_core=True with instrument=None (invariant)
 ├─< TuneAlias             alternate names, ordered by sort_name
 ├─< TuneDifficulty        one per instrument (1–5 scale)
 └─< TuneSetMember         many-to-many with TuneSet via explicit order field

TuneSet
 └─< TuneSetMember

Content                    standalone; created_by FK → users.id is nullable
                            (null = system/built-in, e.g. imported via
                            scripts/import_content.py)
```

### Key Constraints and Invariants

- **Core setting invariant**: every `Tune` must have exactly one `TuneSetting`
  where `is_core = True` and `instrument = None`. This is enforced in the service
  layer (`cairn/services/tunes.py`), not the DB.

- **Box instrument requirement**: `create_box` raises `ValueError` if `instruments`
  is empty. Enforced in the service, not a DB constraint.

- **Unique constraints** (DB-enforced):
  - `TuneBoxEntry`: `(box_id, tune_id)`
  - `TuneListEntry`: `(tune_id, list_id)`
  - `StudentProgress`: `(user_id, tune_id, box_id)`
  - `TuneBoxInstrument`: composite primary key `(box_id, instrument)`

- **Active list**: at most one `PracticeList` per user has `is_active = True`.
  `activate_list()` deactivates the current active list before setting the new one.
  Not enforced at DB level — enforced in the service.

- **Phase 1 stubs**: `_STUB_USER_ID = 1` and `_STUB_BOX_ID = 1` are used
  throughout routers and services in place of real auth. All stubs are named
  with the `_STUB_` prefix so they are easy to find and replace in Phase 2.

- **Authentication (Phase 2, in progress)**: Google OAuth via `authlib`.
  `routers/auth.py` handles `/auth/login` (redirect to Google), `/auth/callback`
  (verify ID token, look up `User` by `google_sub`, auto-provision on first
  login with `role=student`), and `/auth/logout`. Session state (`user_id`)
  lives in a signed cookie via Starlette's `SessionMiddleware`.
  `dependencies.get_current_user` reads it and raises `NotAuthenticatedError`
  on a missing/invalid session, which `main.py` turns into a redirect to
  `/auth/login?next=...`. Not yet wired onto the existing routers — until
  that lands (replacing `_STUB_USER_ID` with the real logged-in user), the
  stub above is still what every route actually uses.

---

## Key Patterns

### HTMX Partial Replacement

Sections that can be updated in place carry an `id` attribute on their outermost
element. Route handlers that handle HTMX actions return a
`TemplateResponse` for the partial template, not the full page.

```html
<!-- in the full page template -->
<section id="aliases-section">
  {% include "tunes/partials/_aliases.html" %}
</section>

<!-- _aliases.html starts with the same id so swap replaces the whole section -->
<section id="aliases-section" ...>
```

```python
# route handler for add/remove returns the partial directly
return templates.TemplateResponse(request, "tunes/partials/_aliases.html", {"tune": tune})
```

The HTMX attribute on the triggering element points at the section id:

```html
<button hx-delete="/tunes/{{ tune.id }}/aliases/{{ alias.id }}"
        hx-target="#aliases-section"
        hx-swap="outerHTML">
```

### Alpine.js + HTMX Coordination

When Alpine manages local state that HTMX needs to update (e.g. the tune
combobox on the box detail page), the two sides communicate via a window-level
custom event rather than shared DOM state:

```javascript
// HTMX fires after a successful request; reads the hidden input value
hx-on::after-request="if(event.detail.successful){ window.dispatchEvent(new CustomEvent('cairn-tune-added', {detail: {id: parseInt(...)}})) }"

// Alpine listens on the window
@cairn-tune-added.window="tunes = tunes.filter(t => t.id !== $event.detail.id)"
```

This keeps the Alpine component self-contained and avoids direct DOM manipulation
from HTMX event handlers.

### Passing Server Data to Alpine

Data that originates on the server and needs to be available to Alpine on page
load is written as a synchronous `<script>` block **before** `app.js` loads:

```html
<script>window.__cairnAddableTunes = {{ addable_tunes_json | safe }};</script>
<script>window.__cairnActiveSettingId = {{ active_setting_id }};</script>
```

The JSON is serialized in the route with `json.dumps` (not Jinja's `tojson`)
so it is correctly escaped. The `| safe` filter prevents double-escaping.
Alpine reads these globals in its `x-data` initializer.

### CSS Grid as a Table (`role="table"`)

Introduced by #164 for the box/list tune tables. A `<table>`'s default
column-layout algorithm sizes every column to its widest cell across *all*
rows, which stretches narrow `<select>`s to match the longest option text
anywhere in the column. Using `display:grid` divs instead sizes columns by
declared fractions (`grid-template-columns`), independent of cell content.

Table semantics are preserved via explicit ARIA roles — `role="table"` /
`role="rowgroup"` / `role="row"` / `role="columnheader"` / `role="cell"` —
**not** `role="grid"`/`gridcell`, which implies a roving-tabindex
arrow-key-navigable widget; assigning it without implementing that
navigation is worse for screen readers than no role at all.

The column-width declaration itself lives in one shared CSS class
(`.cairn-row-grid` in `base.html`) reused by the header row and every body
row, so the two can't drift out of alignment. Row-targeting JS (sort/filter)
selects on a dedicated class (`.cairn-row`), not the ARIA role — keeping
accessibility markup and behavioral hooks decoupled.

### Per-Row Dropdown Menu (Alpine `@click.outside`)

Introduced by #164 for the box/list row overflow ("⋮") menu. Each row owns
its own `x-data="{ menuOpen: false }"` — no shared/store state is needed for
"only one menu open at a time": a row's `@click.outside="menuOpen=false"`
fires when *any other* row's button is clicked, closing it independently of
that row's own click handler opening its own menu.

```html
<div x-data="{ menuOpen: false }" @click.outside="menuOpen = false" @keydown.escape="menuOpen = false">
  <button @click="menuOpen = !menuOpen" aria-haspopup="menu" :aria-expanded="menuOpen">&#8942;</button>
  <div x-show="menuOpen" x-cloak role="menu">...</div>
</div>
```

### Badge Chip with Embedded Delete

Introduced by #180 for the tune detail page's alias list. A pill (the same
neutral `bg-stone-100`/`rounded-full` styling already used for display-only
badges elsewhere) with a small `×` button embedded at its trailing edge,
rather than a separate row with a text "Remove" action:

```html
<span class="group relative inline-flex items-center gap-1.5 bg-stone-100 text-stone-700 text-sm pl-3 pr-1.5 py-1 rounded-full">
  {{ item.name }}
  <button type="button" hx-delete="..." hx-target="#section-id" hx-swap="outerHTML"
          class="shrink-0 w-4 h-4 flex items-center justify-center rounded-full text-stone-400 hover:text-red-600 hover:bg-red-50 leading-none">
    &times;
  </button>
</span>
```

Any per-item detail that doesn't fit in the compact pill (e.g. alias
`notes`) goes in the same custom hover-tooltip pattern used elsewhere in the
app (`hidden group-hover:block absolute ...`), not a native `title=`
attribute. The "add new" control is a small round dashed-border `+` button
sitting inline in the same flex-wrap row as the chips, reusing the existing
`x-data="{ open: false }"` reveal-a-form pattern (see `_difficulty.html`/
`_settings.html`) for the form itself.

### Lazy ABC Rendering (`IntersectionObserver`)

Introduced by #164 for the box/list row preview column. Rendering an ABCJS
score for every row on page load is a real per-row cost that adds up for a
box/list with many tunes; `IntersectionObserver` (`static/js/app.js`'s
`initColumnPreviewObserver`) renders each one only once it scrolls into
view, then unobserves it (render-once, not continuous tracking). A
`data-*-rendered` flag plus `:not([data-*-rendered])` in the re-scan
selector lets the same `htmx:afterSwap`-driven re-observe pattern used
elsewhere in `app.js` skip already-rendered rows while still picking up
freshly swapped-in ones.

### ABC Assembly (`build_abc`)

`cairn/services/abc_utils.py` contains the single function `build_abc(tune, setting, x=1) -> str`.
**This is the only place in the codebase that produces ABC for rendering or export.**

`TuneSetting.abc_notation` stores only the music body (notes) plus any
user-supplied headers that are not covered by DB fields (e.g. `L:`). All
standard headers (`T:`, `K:`, `M:`, `R:`, etc.) are assembled from DB fields
at render time. Headers in the mapped set that appear in `abc_notation` are
silently dropped (DB value takes precedence).

### Alphabetical Sort Without Leading Articles

Any field that is displayed in sorted order stores a companion `sort_*` column:

| Display column | Sort column | Where |
|---|---|---|
| `Tune.title` | `Tune.sort_title` | `tunes` table |
| `TuneAlias.name` | `TuneAlias.sort_name` | `tune_aliases` table |

Both are populated by `sort_key()` in `cairn/services/tunes.py`, which strips
a leading "the ", "a ", or "an " (case-insensitive) before storing. Relationships
and queries order by the `sort_*` column, not the display column.

### Async SQLAlchemy — Eager Loading

SQLAlchemy's async driver does not support lazy loading. Every relationship
that is accessed outside the originating query must be declared in a
`selectinload()` call. The rule: **if you access `obj.relation`, the query
that loaded `obj` must have included `selectinload(Model.relation)`.**

```python
stmt = (
    select(Tune)
    .where(Tune.id == tune_id)
    .options(
        selectinload(Tune.settings),
        selectinload(Tune.aliases),
        selectinload(Tune.difficulties),
    )
)
```

Accessing an unloaded relationship in an async context raises `MissingGreenlet`.

### `metadata` Column Naming

`Base.metadata` is reserved by SQLAlchemy's declarative base for the table's
`MetaData` registry, so a model attribute literally named `metadata` raises
`InvalidRequestError` at class-definition time. Where a column is
conceptually "metadata" (e.g. `Content.metadata`), name the mapped attribute
`metadata_` and pass the real column name explicitly:

```python
metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
```

### Markdown Rendering Without the Tailwind Typography Plugin

The Tailwind CDN build has no Typography (`prose`) plugin, so raw HTML from
`markdown.markdown()` renders with no visual distinction between headings,
body text, links, etc. `render_markdown()` in `cairn/services/content.py`
post-processes the rendered HTML with a regex substitution that injects a
default Tailwind utility class onto each bare `h1`–`h6`, `a`, `table`, `th`,
`td`, `img`, `ul`, `ol`, `blockquote`, `code`, and `pre` tag. Authors can
override any single element with the `attr_list` extension's `{.class}`
syntax; the author's class is merged with (not replaced by) the default so
both apply.

### Static File Cache Busting

`app.js` is served by FastAPI `StaticFiles`, which browsers aggressively cache.
When `app.js` changes in a way that affects page behaviour, bump the `?v=N`
query string on the `<script>` tag in `base.html`:

```html
<script src="/static/js/app.js?v=2"></script>
```

---

## Phase Roadmap Summary

| Phase | Theme | Status |
|---|---|---|
| 1 | Solo tool — tune library, boxes, practice lists, session planner | In progress |
| 2 | Practice intelligence — spaced rep UI, tempo tracking, session history | Planned |
| 3 | Ornamentation system — ABC transformation, ornament library | Planned |
| 4 | Pedagogy layer — teacher content, lesson sessions | Design pending |

Phase 1 task completion (see `TODO.md` for full spec):

| # | Task | Done |
|---|---|---|
| 0.4 | Base template | ✓ |
| 1.1–1.9 | Core models, schemas, migrations | ✓ |
| 2.1–2.5 | Tune management, ABC rendering, settings | ✓ |
| 3.1–3.4 | Spaced repetition, progress tracking, per-box progress | ✓ |
| 4.1 | TuneBox models and service | ✓ |
| 4.2 | TuneBox routes and templates | ✓ |
| 4.3 | PracticeList models and service | ✓ |
| 4.4 | PracticeList routes and templates | — |
| 4.5 | SettingProgress model and service integration | — |
| 5–6 | Session planner, dashboard, warmup library | — |
