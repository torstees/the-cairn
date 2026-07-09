from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cairn.models import KeyMode, KeyRoot, Tune, TuneSetting

if TYPE_CHECKING:
    from cairn.models import TuneBox, TuneSet

_MAPPED_HEADERS = frozenset("XTCOARMSZNK")

ABC_MODE_SUFFIX: dict[str, str] = {
    "major": "",
    "minor": "m",
    "dorian": "dor",
    "mixolydian": "mix",
    "lydian": "lyd",
}

KEY_ROOT_MAP: dict[str, KeyRoot] = {
    "c": KeyRoot.C,
    "c#": KeyRoot.C_sharp,
    "db": KeyRoot.D_flat,
    "d": KeyRoot.D,
    "eb": KeyRoot.E_flat,
    "e": KeyRoot.E,
    "f": KeyRoot.F,
    "f#": KeyRoot.F_sharp,
    "gb": KeyRoot.G_flat,
    "g": KeyRoot.G,
    "ab": KeyRoot.A_flat,
    "a": KeyRoot.A,
    "bb": KeyRoot.B_flat,
    "b": KeyRoot.B,
}

KEY_MODE_MAP: dict[str, KeyMode] = {
    "": KeyMode.major,
    "maj": KeyMode.major,
    "major": KeyMode.major,
    "m": KeyMode.minor,
    "min": KeyMode.minor,
    "minor": KeyMode.minor,
    "dor": KeyMode.dorian,
    "dorian": KeyMode.dorian,
    "mix": KeyMode.mixolydian,
    "mixolydian": KeyMode.mixolydian,
    "lyd": KeyMode.lydian,
    "lydian": KeyMode.lydian,
}


def parse_key(raw: str) -> tuple[KeyRoot, KeyMode] | None:
    """Parse an ABC/TheSession-style key string: 'Dmaj', 'Ador', 'Bbdor',
    'A mixolydian', 'G', 'Bm', 'Gmajor', 'Edorian', etc."""
    m = re.match(r"^([A-Ga-g][b#]?)\s*(.*)", raw.strip())
    if not m:
        return None
    root = KEY_ROOT_MAP.get(m.group(1).lower())
    mode = KEY_MODE_MAP.get(m.group(2).strip().lower())
    if root is None or mode is None:
        return None
    return root, mode


# Q:1/4=N anchors tempo to quarter notes regardless of L:, avoiding ambiguity.
_DEFAULT_TEMPO: dict[str, str] = {
    "reel": "Q:1/4=80",
    "jig": "Q:3/8=80",  # counted in 2; dotted quarter = 80
    "slip_jig": "Q:3/8=80",  # counted in 3; dotted quarter = 80
    "hornpipe": "Q:1/4=70",
    "polka": "Q:1/4=90",
    "slide": "Q:3/8=80",  # counted in 2; dotted quarter = 80
    "strathspey": "Q:1/4=70",
    "waltz": "Q:1/4=80",
    "air": "Q:1/4=60",
    "march": "Q:1/4=80",
    "barndance": "Q:1/4=80",
}


def _parse_abc_notation(abc_notation: str) -> tuple[list[str], list[str]]:
    """Split abc_notation into (user_headers, music_lines).

    Scans lines from the top. Lines matching ^[A-Z]: are header lines:
    those whose letter is not in the DB-mapped set are kept as user-supplied
    headers; those in the mapped set are silently dropped. The first
    non-header line starts the music section; everything from that point on
    (including blank lines) is treated as music.
    """
    lines = abc_notation.splitlines()
    user_headers: list[str] = []
    music_lines: list[str] = []
    in_music = False

    for line in lines:
        if not in_music:
            s = line.strip()
            if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
                if s[0].upper() not in _MAPPED_HEADERS:
                    user_headers.append(line)
                # mapped header → drop (DB value takes precedence)
            else:
                in_music = True
                music_lines.append(line)
        else:
            music_lines.append(line)

    return user_headers, music_lines


def build_abc(tune: Tune, setting: TuneSetting, x: int = 1) -> str:
    """Assemble a complete ABC string from DB fields and the raw music body.

    Headers are built from Tune and TuneSetting in canonical order. Any
    user-supplied headers in setting.abc_notation (letters not in the
    DB-mapped set, e.g. L:) are preserved and inserted before K:. Mapped
    headers found in abc_notation are silently dropped. K: is always last.
    """
    user_headers, music_lines = _parse_abc_notation(setting.abc_notation)

    headers: list[str] = [f"X:{x}"]
    headers.append(f"T:{tune.title}")
    if tune.composer:
        headers.append(f"C:{tune.composer}")
    if tune.origin:
        headers.append(f"O:{tune.origin}")
    if tune.region:
        headers.append(f"A:{tune.region}")
    headers.append(f"R:{tune.tune_type.value}")
    headers.append(f"M:{tune.time_signature}")
    has_q = any(len(h.strip()) >= 2 and h.strip()[0].upper() == "Q" and h.strip()[1] == ":" for h in user_headers)
    if not has_q:
        headers.append(_DEFAULT_TEMPO.get(tune.tune_type.value, "Q:1/4=100"))
    if setting.source:
        headers.append(f"S:{setting.source}")
    if setting.source_notes:
        headers.append(f"Z:{setting.source_notes}")
    if tune.notes:
        headers.append(f"N:{tune.notes}")
    if setting.instrument:
        headers.append(f"N:Arranged for {setting.instrument.label}")

    headers.extend(user_headers)

    key_suffix = ABC_MODE_SUFFIX[tune.key_mode.value]
    headers.append(f"K:{tune.key_root.value}{key_suffix}")

    while music_lines and not music_lines[0].strip():
        music_lines.pop(0)
    while music_lines and not music_lines[-1].strip():
        music_lines.pop()

    return "\n".join(headers + music_lines) + "\n"


def build_set_abc(tune_set: TuneSet, box: TuneBox | None = None, n_bars: int | None = None) -> str:
    """Assemble a multi-tune ABC string for a TuneSet.

    A file-header block (T:, S:, G: plus any user-supplied abc_header lines)
    precedes the individual X: sections produced by build_abc() for each member.
    User-supplied lines that share a letter with an auto-header replace that
    header; other user-supplied lines are appended after the auto-headers.

    If n_bars is given, each member's music body is truncated to that many bars.
    """
    auto: dict[str, str] = {}
    auto["T"] = f"T:{tune_set.title}"
    if tune_set.source:
        auto["S"] = f"S:{tune_set.source}"
    if box is not None:
        auto["G"] = f"G:{box.name}"

    extra: list[str] = []
    if tune_set.abc_header:
        for line in tune_set.abc_header.splitlines():
            s = line.strip()
            if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
                letter = s[0].upper()
                if letter in auto:
                    auto[letter] = line
                else:
                    extra.append(line)

    file_header = "\n".join(list(auto.values()) + extra)

    resolved: list[tuple[Tune, TuneSetting]] = []
    for member in tune_set.members:
        tune = member.tune
        if member.setting is not None:
            setting = member.setting
        else:
            setting = next((s for s in tune.settings if s.is_core), None)
            if setting is None and tune.settings:
                setting = tune.settings[0]
        if setting is None:
            continue
        resolved.append((tune, setting))

    if not resolved:
        return file_header + "\n"

    first_tune, first_setting = resolved[0]
    first_abc = build_abc(first_tune, first_setting, x=1)
    # Insert set title as the first T: inside X:1 so ABCJS renders it as the
    # primary title; the tune's own T: (from build_abc) becomes the subtitle.
    first_abc = first_abc.replace("X:1\n", f"X:1\nT:{tune_set.title}\n", 1)
    if n_bars is not None:
        first_abc = truncate_to_bars(first_abc, n_bars)
    sections: list[str] = [first_abc.rstrip("\n")]

    prev_key = f"{first_tune.key_root.value}{ABC_MODE_SUFFIX[first_tune.key_mode.value]}"
    prev_time = first_tune.time_signature
    prev_type = first_tune.tune_type.value

    for tune, setting in resolved[1:]:
        _, music_lines = _parse_abc_notation(setting.abc_notation)
        while music_lines and not music_lines[0].strip():
            music_lines.pop(0)
        while music_lines and not music_lines[-1].strip():
            music_lines.pop()

        current_key = f"{tune.key_root.value}{ABC_MODE_SUFFIX[tune.key_mode.value]}"

        if n_bars is not None:
            mini = f"K:{current_key}\n" + "\n".join(music_lines)
            mini = truncate_to_bars(mini, n_bars)
            k_match = re.search(r"^K:.*$", mini, re.MULTILINE)
            if k_match:
                body = mini[k_match.end() :]
                music_lines = [l for l in body.splitlines() if l.strip()]

        compact: list[str] = [f"T:{tune.title}"]
        if tune.tune_type.value != prev_type:
            compact.append(f"R:{tune.tune_type.value}")
            prev_type = tune.tune_type.value
        if tune.time_signature != prev_time:
            compact.append(f"M:{tune.time_signature}")
            prev_time = tune.time_signature
        if current_key != prev_key:
            compact.append(f"K:{current_key}")
            prev_key = current_key

        sections.append("\n".join(compact + music_lines))

    return file_header + "\n\n" + "\n".join(sections) + "\n"


def truncate_to_bars(abc: str, n_bars: int) -> str:
    """Return abc truncated to approximately the first n_bars measures.

    Counts `|` characters in the music body (after K:) as bar boundaries and
    stops after the n_bars-th one. A leading barline before any notes (e.g.
    the opening `|` of `|:DEFG...` or a plain `|DEFG...`) is a delimiter, not
    a bar boundary, and is skipped so tunes that don't open with one aren't
    off by one bar. The count is intentionally simple: every other `|` is
    treated as one bar boundary, so repeat markers (`|:`, `:|`) count too,
    which is close enough for the practice-session display purpose.
    """
    k_match = re.search(r"^K:.*$", abc, re.MULTILINE)
    if not k_match:
        return abc
    header = abc[: k_match.end()]
    body = abc[k_match.end() :]
    lead_match = re.match(r"\s*\|+:?", body)
    start = lead_match.end() if lead_match else 0
    pipe_count = 0
    for i in range(start, len(body)):
        if body[i] == "|":
            pipe_count += 1
            if pipe_count >= n_bars:
                return header + body[: i + 1].rstrip() + "\n"
    return abc
