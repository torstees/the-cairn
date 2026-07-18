"""Side-table mirror of TheSession-data's community CSVs (TODO 8.4).

Unrelated to the tune-linking wizard (TODO 8.2) — these cover real-world
session/recording/event metadata, not tune data — and nothing in the app
browses or depends on them yet; they exist purely so this data is available
to query without a later re-import project. See
cairn/models_thesession_tunes.py's docstring for the same "faithful,
lossless mirror" and "refreshable cache, no FKs into our own models"
philosophy, which applies here too.

Kept in its own module per the model file split rule in AGENTS.md (5
models here vs. 3 in models_thesession_tunes.py, each under the
per-file threshold).
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cairn.database import Base, TimestampMixin


class TheSessionSet(TimestampMixin, Base):
    """Mirrors the per-tuneset header fields of TheSession-data's sets.csv.

    sets.csv has one row per member tune of a set (see TheSessionSetMember),
    but `date`/`member_id`/`username`/`name` are the same across every row
    sharing one `tuneset` id — deduplicated to one row per tuneset here
    rather than repeated per member row.
    """

    __tablename__ = "thesession_sets"

    tuneset_id: Mapped[int] = mapped_column(primary_key=True)
    submitted_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    member_id: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class TheSessionSetMember(TimestampMixin, Base):
    """One member tune of a TheSessionSet — one row per sets.csv row.

    Deliberately doesn't duplicate name/type/meter/mode/abc from sets.csv —
    join to TheSessionSetting (8.1) via setting_id for those when needed.
    """

    __tablename__ = "thesession_set_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    tuneset_id: Mapped[int] = mapped_column(ForeignKey("thesession_sets.tuneset_id"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    tune_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    setting_id: Mapped[int] = mapped_column(Integer, nullable=False)


class TheSessionRecording(TimestampMixin, Base):
    """Mirrors TheSession-data's recordings.csv — one row per track.

    `recording_id` is the CSV's own `id` column and repeats across every
    track of the same recording, so it's a plain indexed column here, not
    the primary key (see TheSessionSetting's identical reasoning for
    `setting_id`). `artist` is the artist's name as a plain string — despite
    the CSV column being named `artist` with what the original TODO 8.4 spec
    assumed was a bare opaque numeric id (per TODO 9.2's note), real current
    data is actually the artist's name in all but a small legacy fraction
    (~0.07% of rows, verified against a live import) where it's still a
    bare leftover numeric id never backfilled with a name — stored as-is
    either way, since this is a faithful mirror, not a cleaned-up view.
    """

    __tablename__ = "thesession_recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    artist: Mapped[str] = mapped_column(String(200), nullable=False)
    recording_name: Mapped[str] = mapped_column(String(200), nullable=False)
    track_number: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    tune_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tune_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)


class TheSessionVenue(TimestampMixin, Base):
    """Mirrors TheSession-data's sessions.csv — real-world session venues.

    Named to avoid confusion with our own PracticeSession model.
    """

    __tablename__ = "thesession_venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    town: Mapped[str | None] = mapped_column(String(200), nullable=True)
    area: Mapped[str | None] = mapped_column(String(200), nullable=True)
    country: Mapped[str | None] = mapped_column(String(200), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TheSessionEvent(TimestampMixin, Base):
    """Mirrors TheSession-data's events.csv."""

    __tablename__ = "thesession_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    venue_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    town: Mapped[str | None] = mapped_column(String(200), nullable=True)
    area: Mapped[str | None] = mapped_column(String(200), nullable=True)
    country: Mapped[str | None] = mapped_column(String(200), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
