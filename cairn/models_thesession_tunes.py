"""Side-table mirror of TheSession-data's tune-reference CSVs (TODO 8.1).

These are a faithful, lossless 1:1 mirror of their source CSVs — no
pre-aggregation or deduplication at import time (e.g. there is no separate
"tune-level" table for tunes.csv; query `DISTINCT tune_id` on
TheSessionSetting instead). They exist only to back the tune-linking wizard
(TODO 8.2); nothing in the app browses them directly, and they hold no
relationships back into our own models — Tune.thesession_tune_id and
TuneSetting.thesession_setting_id (TODO 8.2) are plain reference ids, not
FKs, since these side tables are a refreshable cache that can be dropped and
rebuilt independently.

Kept in a separate module from cairn/models.py per the model file split rule
in AGENTS.md: this domain group's models are unrelated to the rest of the
schema, so a scoped sibling file is used instead of growing the shared file
or converting it into a models/ package.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cairn.database import Base, TimestampMixin


class TheSessionSetting(TimestampMixin, Base):
    """Mirrors TheSession-data's tunes.csv — one row per setting, not per tune.

    `setting_id` is the source's own natural key but is a surrogate `id`
    here, not the primary key: real data has duplicate `setting_id` values
    with differing `composer` credits (e.g. setting_id 1892 attributed to
    both "Niel Gow" and "Jenna Reid" in separate rows), so treating it as
    unique would silently drop rows and break the "faithful mirror" goal.
    """

    __tablename__ = "thesession_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    setting_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    tune_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tune_type_raw: Mapped[str] = mapped_column(String(50), nullable=False)
    meter: Mapped[str] = mapped_column(String(20), nullable=False)
    mode_raw: Mapped[str] = mapped_column(String(50), nullable=False)
    abc: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    composer: Mapped[str | None] = mapped_column(String(200), nullable=True)


class TheSessionAlias(TimestampMixin, Base):
    """Mirrors TheSession-data's aliases.csv."""

    __tablename__ = "thesession_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    tune_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)


class TheSessionTunePopularity(TimestampMixin, Base):
    """Mirrors TheSession-data's tune_popularity.csv."""

    __tablename__ = "thesession_tune_popularity"

    tune_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tunebooks: Mapped[int] = mapped_column(Integer, nullable=False)
