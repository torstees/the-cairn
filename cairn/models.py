import enum
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, Float, ForeignKey, Integer, String, Text
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


class SessionItemType(LabelledEnum):
    warmup = "warmup"
    learning = "learning"
    retention = "retention"
    technique = "technique"


class Tune(TimestampMixin, Base):
    __tablename__ = "tunes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    tune_type: Mapped[TuneType] = mapped_column(Enum(TuneType), nullable=False)
    key: Mapped[str] = mapped_column(String(50), nullable=False)
    time_signature: Mapped[str] = mapped_column(String(10), nullable=False)
    origin: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    settings: Mapped[list["TuneSetting"]] = relationship(back_populates="tune", cascade="all, delete-orphan")
    difficulties: Mapped[list["TuneDifficulty"]] = relationship(back_populates="tune", cascade="all, delete-orphan")
    set_members: Mapped[list["TuneSetMember"]] = relationship(back_populates="tune")
    progress_records: Mapped[list["StudentProgress"]] = relationship(back_populates="tune")
    session_items: Mapped[list["PracticeSessionItem"]] = relationship(back_populates="tune")


class TuneSetting(TimestampMixin, Base):
    __tablename__ = "tune_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    abc_notation: Mapped[str] = mapped_column(Text, nullable=False)
    is_core: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ornamentation_level: Mapped[OrnamentationLevel] = mapped_column(
        Enum(OrnamentationLevel), default=OrnamentationLevel.none, nullable=False
    )
    source_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    tune: Mapped["Tune"] = relationship(back_populates="settings")


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
    instrument: Mapped[Instrument | None] = mapped_column(Enum(Instrument), nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (CheckConstraint("difficulty >= 1 AND difficulty <= 5", name="ck_warmup_difficulty_range"),)

    session_items: Mapped[list["PracticeSessionItem"]] = relationship(back_populates="warmup")


class TuneSet(TimestampMixin, Base):
    __tablename__ = "tune_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class TuneSetMember(TimestampMixin, Base):
    __tablename__ = "tune_set_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("tune_sets.id"), nullable=False)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)

    tune_set: Mapped["TuneSet"] = relationship(back_populates="members")
    tune: Mapped["Tune"] = relationship(back_populates="set_members")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False)
    primary_instrument: Mapped[Instrument | None] = mapped_column(Enum(Instrument), nullable=True)

    progress_records: Mapped[list["StudentProgress"]] = relationship(back_populates="user")
    practice_sessions: Mapped[list["PracticeSession"]] = relationship(back_populates="user")


class StudentProgress(TimestampMixin, Base):
    __tablename__ = "student_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tune_id: Mapped[int] = mapped_column(ForeignKey("tunes.id"), nullable=False)
    status: Mapped[ProgressStatus] = mapped_column(Enum(ProgressStatus), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_days: Mapped[float] = mapped_column(Float, nullable=False)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    last_practiced: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_suggested: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    teacher_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        CheckConstraint("confidence >= 1 AND confidence <= 5", name="ck_student_progress_confidence_range"),
    )

    user: Mapped["User"] = relationship(back_populates="progress_records")
    tune: Mapped["Tune"] = relationship(back_populates="progress_records")


class PracticeSession(TimestampMixin, Base):
    __tablename__ = "practice_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped["User"] = relationship(back_populates="practice_sessions")
    items: Mapped[list["PracticeSessionItem"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class PracticeSessionItem(TimestampMixin, Base):
    __tablename__ = "practice_session_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("practice_sessions.id"), nullable=False)
    item_type: Mapped[SessionItemType] = mapped_column(Enum(SessionItemType), nullable=False)
    tune_id: Mapped[int | None] = mapped_column(ForeignKey("tunes.id"), nullable=True)
    warmup_id: Mapped[int | None] = mapped_column(ForeignKey("warmup_items.id"), nullable=True)
    minutes_allocated: Mapped[int] = mapped_column(Integer, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rating_given: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped["PracticeSession"] = relationship(back_populates="items")
    tune: Mapped["Tune | None"] = relationship(back_populates="session_items")
    warmup: Mapped["WarmupItem | None"] = relationship(back_populates="session_items")
