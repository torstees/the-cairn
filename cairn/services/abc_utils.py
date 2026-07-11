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


# ── Transposition (#122) — render-time only, per AGENTS.md's domain invariant:
# "Transposition is always applied at render time, never stored." ──────────────

_NATURAL_PC: dict[str, int] = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SHARP_ORDER = "FCGDAEB"
_FLAT_ORDER = "BEADGCF"
_ACCIDENTAL_DELTA = {"^": 1, "^^": 2, "_": -1, "__": -2, "=": 0}

# Pitch class (0-11) of each supported root, keyed by KeyRoot.value; enharmonic
# pairs (C#/Db, F#/Gb) share a class.
_ROOT_PC: dict[str, int] = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "Eb": 3, "E": 4, "F": 5,
    "F#": 6, "Gb": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11,
}  # fmt: skip

# The canonical (minimal-accidental-count) root spelling for each pitch class —
# used to name the OUTPUT key after a transpose; always resolves the two
# enharmonic classes to Db and F# rather than trying to guess a "better" match
# for the input tune's own spelling.
_PC_TO_ROOT: dict[int, str] = {
    0: "C", 1: "Db", 2: "D", 3: "Eb", 4: "E", 5: "F",
    6: "F#", 7: "G", 8: "Ab", 9: "A", 10: "Bb", 11: "B",
}  # fmt: skip


def transpose_semitones_for(tune_key_root: KeyRoot, target_key_root: KeyRoot | None, octave: int) -> int:
    """Combine a target-key shift (via shortest_semitones_to_root(), or 0 if
    target_key_root is None) with a +/-1-octave nudge, clamped the same way
    the view-time transpose control (#159) clamps its own `octave` query
    param — shared so callers never re-derive this arithmetic themselves."""
    key_shift = shortest_semitones_to_root(tune_key_root, target_key_root) if target_key_root else 0
    return key_shift + max(-1, min(1, octave)) * 12


def shortest_semitones_to_root(current_root: KeyRoot, target_root: KeyRoot) -> int:
    """Signed semitone count from current_root to target_root, choosing
    whichever direction (up or down) has the smaller absolute distance —
    e.g. E to D is -2 (down a whole step), not +10. Mode is unaffected;
    transpose_abc() never changes it.

    A target exactly a tritone away (6 semitones either direction) is a genuine
    tie in pitch-class terms, but the two directions still land the melody an
    octave apart — this defaults to +6 (up) for that case; the caller is
    expected to offer an explicit octave adjustment on top of this for exactly
    that reason (#122's on-score octave toggle).
    """
    delta = (_ROOT_PC[target_root.value] - _ROOT_PC[current_root.value]) % 12
    return delta - 12 if delta > 6 else delta


# Major-key signature (+N sharps / -N flats) for the major key rooted at each
# pitch class, using the conventional minimal-accidental spelling.
_MAJOR_SIGNATURE: dict[int, int] = {
    0: 0, 1: -5, 2: 2, 3: -3, 4: 4, 5: -1,
    6: 6, 7: 1, 8: -4, 9: 3, 10: -2, 11: 5,
}  # fmt: skip

# Semitones to add to a mode's tonic to reach its relative major's tonic
# (e.g. D dorian's relative major is C, a whole tone below D — so +10, i.e.
# -2 mod 12).
_MODE_TO_MAJOR_OFFSET: dict[str, int] = {
    "major": 0,
    "lydian": 7,
    "mixolydian": 5,
    "dorian": 10,
    "minor": 3,
}

# Matches, in order of priority: a quoted chord/annotation string, a `!...!`
# bang decoration, a bar line, or a note token (optional accidental + letter +
# octave marks). Only the note-token alternative is ever rewritten — the
# others are copied through unchanged so transposition can't corrupt chord
# symbols, positioned text, or ornament decorations that happen to contain
# letters in the A-G range (e.g. "!fermata!").
_TRANSPOSE_TOKEN_RE = re.compile(r'"[^"]*"|![^!]*!|\||(?P<acc>\^{1,2}|_{1,2}|=)?(?P<letter>[A-Ga-g])(?P<marks>[,\']*)')


def _signature_for(root_value: str, mode_value: str) -> int:
    """Key signature (+sharps/-flats) for a root+mode combination."""
    parent_major_pc = (_ROOT_PC[root_value] + _MODE_TO_MAJOR_OFFSET[mode_value]) % 12
    return _MAJOR_SIGNATURE[parent_major_pc]


def _signature_accidentals(signature: int) -> dict[str, int]:
    """Per-letter default accidental (-1/0/+1) implied by a key signature."""
    acc = dict.fromkeys("CDEFGAB", 0)
    if signature > 0:
        for letter in _SHARP_ORDER[:signature]:
            acc[letter] = 1
    elif signature < 0:
        for letter in _FLAT_ORDER[:-signature]:
            acc[letter] = -1
    return acc


def _respell(pitch_class: int, signature: int) -> tuple[str, str]:
    """Choose a (letter, accidental) spelling for a pitch class in a given key.

    Prefers relying on the key signature (no explicit accidental) first. Next,
    an explicit natural ("=") that just cancels the signature on some letter —
    e.g. F-natural in a key that sharps F — since that's a smaller change than
    introducing an accidental on an different letter (E# is the same pitch as
    F-natural, but "=F" is the far more expected spelling). Only after that
    does it fall back to a new sharp/flat, biased toward sharps in sharp-side
    keys and flats in flat-side keys. Every pitch class has at least one
    single-accidental spelling given the 7 natural letters are 1-2 semitones
    apart, so this never needs a double sharp/flat for the output.
    """
    sig_acc = _signature_accidentals(signature)
    for letter in "CDEFGAB":
        if (_NATURAL_PC[letter] + sig_acc[letter]) % 12 == pitch_class:
            return letter, ""

    candidates: dict[str, tuple[str, str]] = {}
    for letter in "CDEFGAB":
        if (_NATURAL_PC[letter] + 1) % 12 == pitch_class:
            candidates["^"] = (letter, "^")
        if (_NATURAL_PC[letter] - 1) % 12 == pitch_class:
            candidates["_"] = (letter, "_")
        if _NATURAL_PC[letter] % 12 == pitch_class:
            candidates["="] = (letter, "=")
    order = ("=", "^", "_") if signature >= 0 else ("=", "_", "^")
    for key in order:
        if key in candidates:
            return candidates[key]
    raise AssertionError(f"no single-accidental spelling found for pitch class {pitch_class}")  # pragma: no cover


def _transpose_line(line: str, semitones: int, src_signature: int, dst_signature: int) -> str:
    """Transpose one music-body line. Chord symbols, annotations, and bang
    decorations pass through untouched; bar lines reset the per-bar
    accidental-carry tracking used to interpret notes with no explicit mark.
    """
    src_sig_acc = _signature_accidentals(src_signature)
    active: dict[tuple[str, int], int] = {}
    out: list[str] = []
    pos = 0
    for m in _TRANSPOSE_TOKEN_RE.finditer(line):
        out.append(line[pos : m.start()])
        pos = m.end()
        text = m.group(0)
        if text.startswith('"') or text.startswith("!"):
            out.append(text)
            continue
        if text == "|":
            active.clear()
            out.append(text)
            continue

        letter = m.group("letter")
        letter_upper = letter.upper()
        marks = m.group("marks") or ""
        acc = m.group("acc")

        absolute_octave = (1 if letter.islower() else 0) + marks.count("'") - marks.count(",")

        if acc is not None:
            accidental_offset = _ACCIDENTAL_DELTA[acc]
            active[(letter_upper, absolute_octave)] = accidental_offset
        else:
            accidental_offset = active.get((letter_upper, absolute_octave), src_sig_acc[letter_upper])

        absolute_pitch = absolute_octave * 12 + _NATURAL_PC[letter_upper] + accidental_offset
        new_absolute_octave, new_pitch_class = divmod(absolute_pitch + semitones, 12)
        new_letter, new_acc = _respell(new_pitch_class, dst_signature)

        if new_absolute_octave >= 1:
            new_marks = "'" * (new_absolute_octave - 1)
            new_letter_str = new_letter.lower()
        elif new_absolute_octave == 0:
            new_marks = ""
            new_letter_str = new_letter
        else:
            new_marks = "," * -new_absolute_octave
            new_letter_str = new_letter

        out.append(f"{new_acc}{new_letter_str}{new_marks}")

    out.append(line[pos:])
    return "".join(out)


def transpose_abc(abc: str, semitones: int) -> str:
    """Shift every pitch in a complete, already-assembled ABC string (e.g. from
    build_abc()) by `semitones`, updating K: to match and leaving a visible
    note in Z: (appended if Z: already has content, added fresh otherwise) so
    the change is obvious even on a printed/exported copy — #122.

    Render-time only: the result must never be written back to a tune's
    stored ABC (see AGENTS.md's transposition invariant).
    """
    if semitones == 0:
        return abc

    lines = abc.splitlines()
    key_line_idx = next(
        (i for i, line in enumerate(lines) if (s := line.strip())[:1].upper() == "K" and s[1:2] == ":"), None
    )
    if key_line_idx is None:
        return abc
    parsed = parse_key(lines[key_line_idx].strip()[2:].strip())
    if parsed is None:
        return abc
    key_root, key_mode = parsed

    new_root_pc = (_ROOT_PC[key_root.value] + semitones) % 12
    new_root_value = _PC_TO_ROOT[new_root_pc]
    src_signature = _signature_for(key_root.value, key_mode.value)
    dst_signature = _signature_for(new_root_value, key_mode.value)

    note = f"(transposed {semitones:+d} semitone{'s' if abs(semitones) != 1 else ''})"

    out_lines: list[str] = []
    z_line_idx = None
    for i, line in enumerate(lines):
        s = line.strip()
        is_header = len(s) >= 2 and s[1] == ":" and s[0].isalpha()
        if i == key_line_idx:
            out_lines.append(f"K:{new_root_value}{ABC_MODE_SUFFIX[key_mode.value]}")
        elif is_header and s[0].upper() == "Z":
            z_line_idx = i
            existing = s[2:].strip()
            out_lines.append(f"Z:{existing + '  ' if existing else ''}{note}")
        elif is_header:
            out_lines.append(line)
        else:
            out_lines.append(_transpose_line(line, semitones, src_signature, dst_signature))

    if z_line_idx is None:
        out_lines.insert(key_line_idx, f"Z:{note}")

    return "\n".join(out_lines) + ("\n" if abc.endswith("\n") else "")


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


def build_abc(tune: Tune, setting: TuneSetting, x: int = 1, display_name: str | None = None) -> str:
    """Assemble a complete ABC string from DB fields and the raw music body.

    Headers are built from Tune and TuneSetting in canonical order. Any
    user-supplied headers in setting.abc_notation (letters not in the
    DB-mapped set, e.g. L:) are preserved and inserted before K:. Mapped
    headers found in abc_notation are silently dropped. K: is always last.

    display_name overrides the T: header — used when a box or list entry has
    chosen an alias to display instead of the tune's own title (#119).
    """
    user_headers, music_lines = _parse_abc_notation(setting.abc_notation)

    headers: list[str] = [f"X:{x}"]
    headers.append(f"T:{display_name or tune.title}")
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
