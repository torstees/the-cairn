from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cairn.models import Tune, TuneSetting

if TYPE_CHECKING:
    from cairn.models import TuneBox, TuneSet

_MAPPED_HEADERS = frozenset("XTCOARMSZNK")

_ABC_MODE_SUFFIX: dict[str, str] = {
    "major": "",
    "minor": "m",
    "dorian": "dor",
    "mixolydian": "mix",
    "lydian": "lyd",
}

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

    key_suffix = _ABC_MODE_SUFFIX[tune.key_mode.value]
    headers.append(f"K:{tune.key_root.value}{key_suffix}")

    while music_lines and not music_lines[0].strip():
        music_lines.pop(0)
    while music_lines and not music_lines[-1].strip():
        music_lines.pop()

    return "\n".join(headers + music_lines) + "\n"


def build_set_abc(tune_set: TuneSet, box: TuneBox | None = None) -> str:
    """Assemble a multi-tune ABC string for a TuneSet.

    A file-header block (T:, S:, G: plus any user-supplied abc_header lines)
    precedes the individual X: sections produced by build_abc() for each member.
    User-supplied lines that share a letter with an auto-header replace that
    header; other user-supplied lines are appended after the auto-headers.
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

    parts: list[str] = []
    for i, member in enumerate(tune_set.members, start=1):
        tune = member.tune
        if member.setting is not None:
            setting = member.setting
        else:
            setting = next((s for s in tune.settings if s.is_core), None)
            if setting is None and tune.settings:
                setting = tune.settings[0]
        if setting is None:
            continue
        parts.append(build_abc(tune, setting, x=i))

    if not parts:
        return file_header + "\n"

    return file_header + "\n\n" + "\n".join(parts)


def truncate_to_bars(abc: str, n_bars: int) -> str:
    """Return abc truncated to approximately the first n_bars measures.

    Counts `|` characters in the music body (after K:) and stops after the
    (n_bars+1)th one — the extra `|` closes the last retained bar.  The count
    is intentionally simple: each `|` in the music body is treated as one bar
    boundary, so repeat markers (`|:`, `:|`) count too, which is close enough
    for the practice-session display purpose.
    """
    k_match = re.search(r"^K:.*$", abc, re.MULTILINE)
    if not k_match:
        return abc
    header = abc[: k_match.end()]
    body = abc[k_match.end() :]
    pipe_count = 0
    for i, ch in enumerate(body):
        if ch == "|":
            pipe_count += 1
            if pipe_count > n_bars:
                return header + body[: i + 1].rstrip() + "\n"
    return abc
