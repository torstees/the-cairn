import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn.database import Base, TimestampMixin


class LabelledEnum(str, enum.Enum):
    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class TuneType(LabelledEnum):
    reel = "reel"
    jig = "jig"
    slip_jig = "slip_jig"
    hornpipe = "hornpipe"
    polka = "polka"
    slide = "slide"
    strathspey = "strathspey"
    waltz = "waltz"
    air = "air"
    march = "march"
    barndance = "barndance"
    mazurka = "mazurka"
    three_two = "three_two"


class Instrument(LabelledEnum):
    flute = "flute"
    tin_whistle = "tin_whistle"
    uilleann_pipes = "uilleann_pipes"
    fiddle = "fiddle"
    concertina = "concertina"
    accordion = "accordion"
    banjo = "banjo"
    mandolin = "mandolin"
    bouzouki = "bouzouki"
    guitar = "guitar"
    bodhrán = "bodhrán"
    harp = "harp"


class ProgressStatus(LabelledEnum):
    just_learning = "just_learning"
    getting_there = "getting_there"
    nearly_there = "nearly_there"
    session_ready = "session_ready"
    committed = "committed"
    performance_ready = "performance_ready"
    solo_ready = "solo_ready"


class PracticeListType(LabelledEnum):
    repertoire = "repertoire"
    woodshed = "woodshed"


class OrnamentationLevel(LabelledEnum):
    none = "none"
    minimal = "minimal"
    moderate = "moderate"
    full = "full"


class WarmupType(LabelledEnum):
    scale = "scale"
    snippet = "snippet"
    text_blurb = "text_blurb"


class Role(LabelledEnum):
    guest = "guest"  # never stored in users table; exists for authorization logic only
    student = "student"
    teacher = "teacher"
    admin = "admin"


class ContentVisibility(LabelledEnum):
    public = "public"
    enrolled = "enrolled"
    private = "private"


class ContentType(LabelledEnum):
    page = "page"
    lesson = "lesson"
    tutorial = "tutorial"
    technique_guide = "technique_guide"


class SessionItemType(LabelledEnum):
    warmup = "warmup"
    learning = "learning"
    retention = "retention"
    technique = "technique"


class KeyRoot(LabelledEnum):
    C = "C"
    C_sharp = "C#"
    D_flat = "Db"
    D = "D"
    E_flat = "Eb"
    E = "E"
    F = "F"
    F_sharp = "F#"
    G_flat = "Gb"
    G = "G"
    A_flat = "Ab"
    A = "A"
    B_flat = "Bb"
    B = "B"


class KeyMode(LabelledEnum):
    major = "major"
    minor = "minor"
    dorian = "dorian"
    mixolydian = "mixolydian"
    lydian = "lydian"


class Tune(TimestampMixin, Base):
    __tablename__ = "tunes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    tune_type: Mapped[TuneType] = mapped_column(Enum(TuneType), nullable=False)
    key_root: Mapped[KeyRoot] = mapped_column(Enum(KeyRoot), nullable=False)
    key_mode: Mapped[KeyMode] = mapped_column(Enum(KeyMode), nullable=False)
    time_signature: Mapped[str] = mapped_column(String(10), nullable=False)
    composer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Plain reference ids, not FKs into the thesession_* side tables (TODO 8.1) —
    # those are a refreshable cache; these are a permanent attribution link
    # that must survive a cache refresh/rebuild. See TODO 8.2.
    thesession_tune_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thesession_username: Mapped[str | None] = mapped_column(String(200), nullable=True)

    settings: Mapped[list["TuneSetting"]] = relationship(back_populates="tune", cascade="all, delete-orphan")
    aliases: Mapped[list["TuneAlias"]] = relationship(
        back_populates="tune", cascade="all, delete-orphan", order_by="TuneAlias.sort_name"
    )
    difficulties: Mapped[list["TuneDifficulty"]] = relationship(back_populates="tune", cascade="all, delete-orphan")
    set_members: Mapped[list["TuneSetMember"]] = relationship(back_populates="tune")
    box_entries: Mapped[list["TuneBoxEntry"]] = relationship(back_populates="tune")
    progress_records: Mapped[list["StudentProgress"]] = relationship(back_populates="tune")
    session_items: Mapped[list["PracticeSessionItem"]] = relationship(back_populates="tune")
    tempo_records: Mapped[list["TempoRecord"]] = relationship(back_populates="tune", cascade="all, delete-orphan")


class TuneSetting(TimestampMixin, Base):
    __tablename__ = "tune_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    abc_notation: Mapped[str] = mapped_column(Text, nullable=False)
    is_core: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    instrument: Mapped[Instrument | None] = mapped_column(Enum(Instrument), nullable=True)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ornamentation_level: Mapped[OrnamentationLevel] = mapped_column(
        Enum(OrnamentationLevel), default=OrnamentationLevel.none, nullable=False
    )
    source_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    mutation_notation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        # Format TBD — see Phase 3 mutation notation design notes
        # Do not implement rendering until format is decided
    )
    # Plain reference id, not a FK — see the matching note on Tune above.
    thesession_setting_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thesession_username: Mapped[str | None] = mapped_column(String(200), nullable=True)

    tune: Mapped["Tune"] = relationship(back_populates="settings")


class TuneAlias(TimestampMixin, Base):
    __tablename__ = "tune_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    tune: Mapped["Tune"] = relationship(back_populates="aliases")


class TuneDifficulty(TimestampMixin, Base):
    __tablename__ = "tune_difficulties"

    id: Mapped[int] = mapped_column(primary_key=True)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    instrument: Mapped[Instrument] = mapped_column(Enum(Instrument), nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (CheckConstraint("difficulty >= 1 AND difficulty <= 5", name="ck_tune_difficulty_range"),)

    tune: Mapped["Tune"] = relationship(back_populates="difficulties")


class WarmupItem(TimestampMixin, Base):
    __tablename__ = "warmup_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    warmup_type: Mapped[WarmupType] = mapped_column(Enum(WarmupType), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    default_tempo: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint("difficulty >= 1 AND difficulty <= 5", name="ck_warmup_difficulty_range"),
        CheckConstraint(
            "default_tempo IS NULL OR (default_tempo >= 20 AND default_tempo <= 300)",
            name="ck_warmup_default_tempo_range",
        ),
    )

    instruments: Mapped[list["WarmupInstrument"]] = relationship(back_populates="warmup", cascade="all, delete-orphan")
    session_items: Mapped[list["PracticeSessionItem"]] = relationship(back_populates="warmup")


class WarmupInstrument(TimestampMixin, Base):
    __tablename__ = "warmup_instruments"

    warmup_id: Mapped[int] = mapped_column(ForeignKey("warmup_items.id", ondelete="CASCADE"), primary_key=True)
    instrument: Mapped[Instrument] = mapped_column(Enum(Instrument), primary_key=True)

    warmup: Mapped["WarmupItem"] = relationship(back_populates="instruments")


class WarmupTempo(TimestampMixin, Base):
    __tablename__ = "warmup_tempos"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    warmup_id: Mapped[int] = mapped_column(ForeignKey("warmup_items.id"), primary_key=True)
    tempo: Mapped[int] = mapped_column(Integer, nullable=False)


class TuneSet(TimestampMixin, Base):
    __tablename__ = "tune_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    abc_header: Mapped[str | None] = mapped_column(Text, nullable=True)
    flow_difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flow_difficulty_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "flow_difficulty IS NULL OR (flow_difficulty >= 1 AND flow_difficulty <= 5)",
            name="ck_tuneset_flow_difficulty_range",
        ),
    )

    members: Mapped[list["TuneSetMember"]] = relationship(
        back_populates="tune_set", cascade="all, delete-orphan", order_by="TuneSetMember.order"
    )
    box_set_entries: Mapped[list["TuneBoxSetEntry"]] = relationship(
        back_populates="tune_set", cascade="all, delete-orphan"
    )


class TuneSetMember(TimestampMixin, Base):
    __tablename__ = "tune_set_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("tune_sets.id"), nullable=False)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    setting_id: Mapped[int | None] = mapped_column(ForeignKey("tune_settings.id"), nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)

    tune_set: Mapped["TuneSet"] = relationship(back_populates="members")
    tune: Mapped["Tune"] = relationship(back_populates="set_members")
    setting: Mapped["TuneSetting | None"] = relationship()


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False)
    primary_instrument: Mapped[Instrument | None] = mapped_column(Enum(Instrument), nullable=True)

    tune_boxes: Mapped[list["TuneBox"]] = relationship(back_populates="user")
    practice_lists: Mapped[list["PracticeList"]] = relationship(back_populates="user")
    progress_records: Mapped[list["StudentProgress"]] = relationship(back_populates="user")
    practice_sessions: Mapped[list["PracticeSession"]] = relationship(back_populates="user")


class TuneBox(TimestampMixin, Base):
    __tablename__ = "tune_boxes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    user: Mapped["User"] = relationship(back_populates="tune_boxes")
    instruments: Mapped[list["TuneBoxInstrument"]] = relationship(back_populates="box", cascade="all, delete-orphan")
    entries: Mapped[list["TuneBoxEntry"]] = relationship(back_populates="box", cascade="all, delete-orphan")
    box_set_entries: Mapped[list["TuneBoxSetEntry"]] = relationship(back_populates="box", cascade="all, delete-orphan")
    progress_records: Mapped[list["StudentProgress"]] = relationship(back_populates="box")


class TuneBoxInstrument(TimestampMixin, Base):
    __tablename__ = "tune_box_instruments"

    box_id: Mapped[int] = mapped_column(ForeignKey("tune_boxes.id"), primary_key=True)
    instrument: Mapped[Instrument] = mapped_column(Enum(Instrument), primary_key=True)

    box: Mapped["TuneBox"] = relationship(back_populates="instruments")


class TuneBoxEntry(TimestampMixin, Base):
    __tablename__ = "tune_box_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    box_id: Mapped[int] = mapped_column(ForeignKey("tune_boxes.id"), nullable=False)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    setting_id: Mapped[int | None] = mapped_column(ForeignKey("tune_settings.id"), nullable=True)
    display_alias_id: Mapped[int | None] = mapped_column(ForeignKey("tune_aliases.id"), nullable=True)
    transpose_key_root: Mapped[KeyRoot | None] = mapped_column(Enum(KeyRoot), nullable=True)
    transpose_octave: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (UniqueConstraint("box_id", "tune_id", name="uq_tune_box_entry_box_tune"),)

    box: Mapped["TuneBox"] = relationship(back_populates="entries")
    tune: Mapped["Tune"] = relationship(back_populates="box_entries")
    setting: Mapped["TuneSetting | None"] = relationship()
    display_alias: Mapped["TuneAlias | None"] = relationship()


class TuneBoxSetEntry(TimestampMixin, Base):
    __tablename__ = "tune_box_set_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    box_id: Mapped[int] = mapped_column(ForeignKey("tune_boxes.id"), nullable=False)
    set_id: Mapped[int] = mapped_column(ForeignKey("tune_sets.id"), nullable=False)

    __table_args__ = (UniqueConstraint("box_id", "set_id", name="uq_tune_box_set_entry_box_set"),)

    box: Mapped["TuneBox"] = relationship(back_populates="box_set_entries")
    tune_set: Mapped["TuneSet"] = relationship(back_populates="box_set_entries")


class TuneSetTempo(TimestampMixin, Base):
    __tablename__ = "tune_set_tempos"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    box_id: Mapped[int] = mapped_column(ForeignKey("tune_boxes.id"), primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("tune_sets.id"), primary_key=True)
    tempo: Mapped[int] = mapped_column(Integer, nullable=False)


class TuneBoxSetDifficulty(TimestampMixin, Base):
    """A user's override of a TuneSet's computed default difficulty, scoped to one box.

    A row only exists once a user has explicitly overridden the default
    (the hardest TuneDifficulty rating among the set's member tunes, for the
    box's own instrument(s), computed fresh — see
    services/tune_sets.py::compute_default_set_difficulty). Absence of a row
    means "use the computed default."
    """

    __tablename__ = "tune_box_set_difficulties"

    box_id: Mapped[int] = mapped_column(ForeignKey("tune_boxes.id"), primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("tune_sets.id"), primary_key=True)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (CheckConstraint("difficulty >= 1 AND difficulty <= 5", name="ck_tune_box_set_difficulty_range"),)


class PracticeList(TimestampMixin, Base):
    __tablename__ = "practice_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    box_id: Mapped[int] = mapped_column(ForeignKey("tune_boxes.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    list_type: Mapped[PracticeListType] = mapped_column(Enum(PracticeListType), nullable=False)
    progress_goal: Mapped[ProgressStatus] = mapped_column(
        Enum(ProgressStatus), default=ProgressStatus.committed, nullable=False
    )
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship(back_populates="practice_lists")
    box: Mapped["TuneBox"] = relationship()
    entries: Mapped[list["TuneListEntry"]] = relationship(back_populates="practice_list", cascade="all, delete-orphan")


class TuneListEntry(TimestampMixin, Base):
    __tablename__ = "tune_list_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("practice_lists.id"), nullable=False)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    setting_id: Mapped[int | None] = mapped_column(ForeignKey("tune_settings.id"), nullable=True)
    display_alias_id: Mapped[int | None] = mapped_column(ForeignKey("tune_aliases.id"), nullable=True)
    transpose_key_root: Mapped[KeyRoot | None] = mapped_column(Enum(KeyRoot), nullable=True)
    transpose_octave: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (UniqueConstraint("tune_id", "list_id", name="uq_tune_list_entry_tune_list"),)

    practice_list: Mapped["PracticeList"] = relationship(back_populates="entries")
    tune: Mapped["Tune"] = relationship()
    setting: Mapped["TuneSetting | None"] = relationship()
    display_alias: Mapped["TuneAlias | None"] = relationship()


class SettingProgress(TimestampMixin, Base):
    __tablename__ = "setting_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    setting_id: Mapped[int] = mapped_column(ForeignKey("tune_settings.id"), nullable=False)
    box_id: Mapped[int] = mapped_column(ForeignKey("tune_boxes.id"), nullable=False)
    status: Mapped[ProgressStatus] = mapped_column(Enum(ProgressStatus), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "setting_id", "box_id", name="uq_setting_progress_user_setting_box"),)

    user: Mapped["User"] = relationship()
    setting: Mapped["TuneSetting"] = relationship()
    box: Mapped["TuneBox"] = relationship()


class StudentProgress(TimestampMixin, Base):
    __tablename__ = "student_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    box_id: Mapped[int] = mapped_column(ForeignKey("tune_boxes.id"), nullable=False)
    status: Mapped[ProgressStatus] = mapped_column(Enum(ProgressStatus), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_days: Mapped[float] = mapped_column(Float, nullable=False)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    last_practiced: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_suggested: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    teacher_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        CheckConstraint("confidence >= 1 AND confidence <= 5", name="ck_student_progress_confidence_range"),
        UniqueConstraint("user_id", "tune_id", "box_id", name="uq_student_progress_user_tune_box"),
    )

    user: Mapped["User"] = relationship(back_populates="progress_records")
    tune: Mapped["Tune"] = relationship(back_populates="progress_records")
    box: Mapped["TuneBox"] = relationship(back_populates="progress_records")


class PracticeSession(TimestampMixin, Base):
    __tablename__ = "practice_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    box_id: Mapped[int | None] = mapped_column(ForeignKey("tune_boxes.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped["User"] = relationship(back_populates="practice_sessions")
    items: Mapped[list["PracticeSessionItem"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class TempoRecord(TimestampMixin, Base):
    __tablename__ = "tempo_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    box_id: Mapped[int | None] = mapped_column(ForeignKey("tune_boxes.id"), nullable=True)
    tempo: Mapped[int] = mapped_column(Integer, nullable=False)

    user: Mapped["User"] = relationship()
    tune: Mapped["Tune"] = relationship(back_populates="tempo_records")


class PracticeSessionItem(TimestampMixin, Base):
    __tablename__ = "practice_session_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("practice_sessions.id"), nullable=False)
    item_type: Mapped[SessionItemType] = mapped_column(Enum(SessionItemType), nullable=False)
    tune_id: Mapped[int | None] = mapped_column(ForeignKey("tunes.id"), nullable=True)
    warmup_id: Mapped[int | None] = mapped_column(ForeignKey("warmup_items.id"), nullable=True)
    minutes_allocated: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rating_given: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped["PracticeSession"] = relationship(back_populates="items")
    tune: Mapped["Tune | None"] = relationship(back_populates="session_items")
    warmup: Mapped["WarmupItem | None"] = relationship(back_populates="session_items")


class Content(TimestampMixin, Base):
    __tablename__ = "content"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[ContentType] = mapped_column(Enum(ContentType), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[ContentVisibility] = mapped_column(
        Enum(ContentVisibility), default=ContentVisibility.public, nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Mapped attribute is named metadata_ (not metadata) since `metadata` is
    # reserved on declarative Base for the table's MetaData registry; the
    # column itself is still named "metadata" in the database.
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
