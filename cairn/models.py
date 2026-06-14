import enum


class TuneType(str, enum.Enum):
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

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class Instrument(str, enum.Enum):
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

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class ProgressStatus(str, enum.Enum):
    just_learning = "just_learning"
    getting_there = "getting_there"
    nearly_there = "nearly_there"
    session_ready = "session_ready"
    committed = "committed"
    performance_ready = "performance_ready"
    solo_ready = "solo_ready"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class OrnamentationLevel(str, enum.Enum):
    none = "none"
    minimal = "minimal"
    moderate = "moderate"
    full = "full"

    @property
    def label(self) -> str:
        return self.value.title()


class WarmupType(str, enum.Enum):
    scale = "scale"
    snippet = "snippet"
    text_blurb = "text_blurb"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class Role(str, enum.Enum):
    guest = "guest"  # never stored in users table; exists for authorization logic only
    student = "student"
    teacher = "teacher"
    admin = "admin"

    @property
    def label(self) -> str:
        return self.value.title()


class ContentVisibility(str, enum.Enum):
    public = "public"
    enrolled = "enrolled"
    private = "private"

    @property
    def label(self) -> str:
        return self.value.title()
