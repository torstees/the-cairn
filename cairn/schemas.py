from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, ProgressStatus, TuneType, WarmupType


class _ReadBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ── Tune ──────────────────────────────────────────────────────────────────────


class TuneCreate(BaseModel):
    title: str
    tune_type: TuneType
    key_root: KeyRoot
    key_mode: KeyMode
    time_signature: str
    composer: str | None = None
    origin: str | None = None
    region: str | None = None
    notes: str | None = None
    created_by: int | None = None


class TuneUpdate(BaseModel):
    title: str | None = None
    tune_type: TuneType | None = None
    key_root: KeyRoot | None = None
    key_mode: KeyMode | None = None
    time_signature: str | None = None
    composer: str | None = None
    origin: str | None = None
    region: str | None = None
    notes: str | None = None


class TuneRead(_ReadBase):
    title: str
    tune_type: TuneType
    key_root: KeyRoot
    key_mode: KeyMode
    time_signature: str
    composer: str | None
    origin: str | None
    region: str | None
    notes: str | None
    created_by: int | None


# ── TuneSetting ───────────────────────────────────────────────────────────────


class TuneSettingCreate(BaseModel):
    tune_id: int
    label: str
    abc_notation: str
    is_core: bool = False
    instrument: Instrument | None = None
    source: str | None = None
    ornamentation_level: OrnamentationLevel = OrnamentationLevel.none
    source_notes: str | None = None
    mutation_notation: str | None = None


class TuneSettingUpdate(BaseModel):
    label: str | None = None
    abc_notation: str | None = None
    is_core: bool | None = None
    instrument: Instrument | None = None
    source: str | None = None
    ornamentation_level: OrnamentationLevel | None = None
    source_notes: str | None = None
    mutation_notation: str | None = None


class TuneSettingRead(_ReadBase):
    tune_id: int
    label: str
    abc_notation: str
    is_core: bool
    instrument: Instrument | None
    source: str | None
    ornamentation_level: OrnamentationLevel
    source_notes: str | None
    mutation_notation: str | None


# ── TuneDifficulty ────────────────────────────────────────────────────────────


class TuneDifficultyCreate(BaseModel):
    tune_id: int
    instrument: Instrument
    difficulty: int = Field(ge=1, le=5)
    notes: str | None = None


class TuneDifficultyUpdate(BaseModel):
    difficulty: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = None


class TuneDifficultyRead(_ReadBase):
    tune_id: int
    instrument: Instrument
    difficulty: int
    notes: str | None


# ── TuneSet ───────────────────────────────────────────────────────────────────


class TuneSetCreate(BaseModel):
    title: str
    description: str | None = None
    flow_difficulty: int | None = Field(default=None, ge=1, le=5)
    flow_difficulty_notes: str | None = None


class TuneSetUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    flow_difficulty: int | None = Field(default=None, ge=1, le=5)
    flow_difficulty_notes: str | None = None


class TuneSetRead(_ReadBase):
    title: str
    description: str | None
    flow_difficulty: int | None
    flow_difficulty_notes: str | None


# ── TuneSetMember ─────────────────────────────────────────────────────────────


class TuneSetMemberCreate(BaseModel):
    set_id: int
    tune_id: int
    order: int


class TuneSetMemberUpdate(BaseModel):
    order: int | None = None


class TuneSetMemberRead(_ReadBase):
    set_id: int
    tune_id: int
    order: int


# ── StudentProgress ───────────────────────────────────────────────────────────


class StudentProgressCreate(BaseModel):
    user_id: int
    tune_id: int
    status: ProgressStatus
    confidence: int = Field(ge=1, le=5)
    interval_days: float
    ease_factor: float = 2.5
    last_practiced: datetime | None = None
    next_suggested: datetime | None = None
    teacher_approved: bool = False


class StudentProgressUpdate(BaseModel):
    status: ProgressStatus | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)
    interval_days: float | None = None
    ease_factor: float | None = None
    last_practiced: datetime | None = None
    next_suggested: datetime | None = None
    teacher_approved: bool | None = None


class StudentProgressRead(_ReadBase):
    user_id: int
    tune_id: int
    status: ProgressStatus
    confidence: int
    interval_days: float
    ease_factor: float
    last_practiced: datetime | None
    next_suggested: datetime | None
    teacher_approved: bool


# ── WarmupItem ────────────────────────────────────────────────────────────────


class WarmupItemCreate(BaseModel):
    title: str
    warmup_type: WarmupType
    content: str
    instruments: list[Instrument] = []
    difficulty: int = Field(ge=1, le=5)
    default_tempo: int | None = Field(default=None, ge=20, le=300)


class WarmupItemUpdate(BaseModel):
    title: str | None = None
    warmup_type: WarmupType | None = None
    content: str | None = None
    instruments: list[Instrument] = []
    difficulty: int | None = Field(default=None, ge=1, le=5)
    default_tempo: int | None = Field(default=None, ge=20, le=300)


class WarmupItemRead(_ReadBase):
    title: str
    warmup_type: WarmupType
    content: str
    instruments: list[Instrument]
    difficulty: int
    default_tempo: int | None
