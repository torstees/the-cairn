from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, Tune, TuneSetting, TuneType
from cairn.services.abc_utils import _signature_for, build_abc, parse_key, transpose_abc, truncate_to_bars

MUSIC = "|:DEFG ABcd|efge dcAG:|\n"


def _tune(**kwargs) -> Tune:
    defaults = dict(
        title="The Morning Dew",
        tune_type=TuneType.reel,
        key_root=KeyRoot.D,
        key_mode=KeyMode.major,
        time_signature="4/4",
        composer=None,
        origin=None,
        region=None,
        notes=None,
    )
    return Tune(**{**defaults, **kwargs})


def _setting(**kwargs) -> TuneSetting:
    defaults = dict(
        tune_id=1,
        label="Standard",
        abc_notation=MUSIC,
        is_core=True,
        instrument=None,
        source=None,
        source_notes=None,
        ornamentation_level=OrnamentationLevel.none,
    )
    return TuneSetting(**{**defaults, **kwargs})


def _headers(result: str) -> list[str]:
    return [l for l in result.splitlines() if len(l) >= 2 and l[1] == ":" and l[0].isalpha()]


# ── canonical structure ───────────────────────────────────────────────────────


def test_x_is_first_header() -> None:
    result = build_abc(_tune(), _setting())
    assert result.splitlines()[0] == "X:1"


def test_x_uses_supplied_index() -> None:
    result = build_abc(_tune(), _setting(), x=3)
    assert result.splitlines()[0] == "X:3"


def test_k_is_last_header() -> None:
    result = build_abc(_tune(), _setting())
    headers = _headers(result)
    assert headers[-1].startswith("K:")


def test_music_follows_headers() -> None:
    result = build_abc(_tune(), _setting())
    lines = result.splitlines()
    last_header_idx = max(i for i, l in enumerate(lines) if len(l) >= 2 and l[1] == ":" and l[0].isalpha())
    assert lines[last_header_idx + 1] == "|:DEFG ABcd|efge dcAG:|"


def test_result_ends_with_newline() -> None:
    assert build_abc(_tune(), _setting()).endswith("\n")


# ── DB-derived headers ────────────────────────────────────────────────────────


def test_title_in_output() -> None:
    result = build_abc(_tune(title="Banish Misfortune"), _setting())
    assert "T:Banish Misfortune" in result


def test_display_name_overrides_title() -> None:
    result = build_abc(_tune(title="Banish Misfortune"), _setting(), display_name="The Rambling Pitchfork")
    assert "T:The Rambling Pitchfork" in result
    assert "T:Banish Misfortune" not in result


def test_display_name_none_falls_back_to_title() -> None:
    result = build_abc(_tune(title="Banish Misfortune"), _setting(), display_name=None)
    assert "T:Banish Misfortune" in result


def test_tune_type_as_r_header() -> None:
    result = build_abc(_tune(tune_type=TuneType.jig), _setting())
    assert "R:jig" in result


def test_time_signature_as_m_header() -> None:
    result = build_abc(_tune(time_signature="6/8"), _setting())
    assert "M:6/8" in result


def test_key_major() -> None:
    result = build_abc(_tune(key_root=KeyRoot.G, key_mode=KeyMode.major), _setting())
    assert "K:G" in result


def test_key_dorian() -> None:
    result = build_abc(_tune(key_root=KeyRoot.A, key_mode=KeyMode.dorian), _setting())
    assert "K:Ador" in result


def test_key_mixolydian() -> None:
    result = build_abc(_tune(key_root=KeyRoot.G, key_mode=KeyMode.mixolydian), _setting())
    assert "K:Gmix" in result


def test_key_minor() -> None:
    result = build_abc(_tune(key_root=KeyRoot.E, key_mode=KeyMode.minor), _setting())
    assert "K:Em" in result


def test_key_sharp_root() -> None:
    result = build_abc(_tune(key_root=KeyRoot.C_sharp, key_mode=KeyMode.minor), _setting())
    assert "K:C#m" in result


# ── nullable fields omitted ───────────────────────────────────────────────────


def test_nullable_tune_fields_omitted() -> None:
    tune = _tune(composer=None, origin=None, region=None, notes=None)
    result = build_abc(tune, _setting(source=None, source_notes=None, instrument=None))
    assert "C:" not in result
    assert "O:" not in result
    assert "A:" not in result
    assert "S:" not in result
    assert "Z:" not in result
    assert "N:" not in result


def test_composer_present_when_set() -> None:
    result = build_abc(_tune(composer="Trad."), _setting())
    assert "C:Trad." in result


def test_origin_present_when_set() -> None:
    result = build_abc(_tune(origin="O'Neill's 1001"), _setting())
    assert "O:O'Neill's 1001" in result


def test_region_as_a_header() -> None:
    result = build_abc(_tune(region="Clare"), _setting())
    assert "A:Clare" in result


def test_setting_source_as_s_header() -> None:
    result = build_abc(_tune(), _setting(source="Tommy Peoples"))
    assert "S:Tommy Peoples" in result


def test_setting_source_notes_as_z_header() -> None:
    result = build_abc(_tune(), _setting(source_notes="Transcribed by ear"))
    assert "Z:Transcribed by ear" in result


# ── N: header combinations ────────────────────────────────────────────────────


def test_tune_notes_as_n_header() -> None:
    result = build_abc(_tune(notes="A lively Clare reel"), _setting())
    assert "N:A lively Clare reel" in result


def test_instrument_as_n_header() -> None:
    result = build_abc(_tune(), _setting(instrument=Instrument.fiddle))
    assert "N:Arranged for Fiddle" in result


def test_both_n_lines_when_notes_and_instrument_set() -> None:
    tune = _tune(notes="A lively Clare reel")
    setting = _setting(instrument=Instrument.fiddle)
    result = build_abc(tune, setting)
    n_lines = [l for l in result.splitlines() if l.startswith("N:")]
    assert len(n_lines) == 2
    assert n_lines[0] == "N:A lively Clare reel"
    assert n_lines[1] == "N:Arranged for Fiddle"


def test_only_tune_notes_when_no_instrument() -> None:
    n_lines = [l for l in build_abc(_tune(notes="Traditional"), _setting()).splitlines() if l.startswith("N:")]
    assert len(n_lines) == 1
    assert n_lines[0] == "N:Traditional"


def test_only_instrument_when_no_tune_notes() -> None:
    n_lines = [l for l in build_abc(_tune(), _setting(instrument=Instrument.flute)).splitlines() if l.startswith("N:")]
    assert len(n_lines) == 1
    assert n_lines[0] == "N:Arranged for Flute"


# ── user-supplied headers in abc_notation ─────────────────────────────────────


def test_l_header_preserved() -> None:
    setting = _setting(abc_notation="L:1/8\n" + MUSIC)
    result = build_abc(_tune(), setting)
    assert "L:1/8" in result


def test_l_header_appears_before_k() -> None:
    setting = _setting(abc_notation="L:1/8\n" + MUSIC)
    result = build_abc(_tune(), setting)
    lines = result.splitlines()
    l_idx = next(i for i, l in enumerate(lines) if l == "L:1/8")
    k_idx = next(i for i, l in enumerate(lines) if l.startswith("K:"))
    assert l_idx < k_idx


def test_mapped_header_in_abc_notation_is_dropped() -> None:
    # K: in abc_notation must not appear — DB value always wins
    setting = _setting(abc_notation="K:G\n" + MUSIC)
    tune = _tune(key_root=KeyRoot.D, key_mode=KeyMode.major)
    result = build_abc(tune, setting)
    k_lines = [l for l in result.splitlines() if l.startswith("K:")]
    assert len(k_lines) == 1
    assert k_lines[0] == "K:D"


def test_title_in_abc_notation_is_dropped() -> None:
    setting = _setting(abc_notation="T:Wrong Title\n" + MUSIC)
    result = build_abc(_tune(title="Correct Title"), setting)
    assert result.count("T:") == 1
    assert "T:Correct Title" in result


def test_multiple_user_headers_preserved() -> None:
    setting = _setting(abc_notation="L:1/8\nQ:120\n" + MUSIC)
    result = build_abc(_tune(), setting)
    assert "L:1/8" in result
    assert "Q:120" in result


# ── default tempo ─────────────────────────────────────────────────────────────


def test_default_tempo_added_when_no_q() -> None:
    result = build_abc(_tune(tune_type=TuneType.reel), _setting())
    assert "Q:" in result


def test_default_tempo_appears_before_k() -> None:
    result = build_abc(_tune(), _setting())
    lines = result.splitlines()
    q_idx = next(i for i, l in enumerate(lines) if l.startswith("Q:"))
    k_idx = next(i for i, l in enumerate(lines) if l.startswith("K:"))
    assert q_idx < k_idx


def test_user_q_not_duplicated_by_default() -> None:
    setting = _setting(abc_notation="Q:1/4=200\n" + MUSIC)
    result = build_abc(_tune(), setting)
    q_lines = [l for l in result.splitlines() if l.startswith("Q:")]
    assert len(q_lines) == 1
    assert q_lines[0] == "Q:1/4=200"


def test_user_q_takes_precedence_over_default() -> None:
    setting = _setting(abc_notation="Q:1/4=200\n" + MUSIC)
    result = build_abc(_tune(tune_type=TuneType.reel), setting)
    assert "Q:1/4=200" in result
    assert "Q:1/4=100" not in result


# ── truncate_to_bars ───────────────────────────────────────────────────────────


def test_truncate_keeps_n_bars_with_leading_barline() -> None:
    abc = "K:D\n|:DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA:|\n"
    result = truncate_to_bars(abc, 4)
    assert result.count("|") == 5  # leading "|:" + 4 bar-closing pipes
    assert "DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|" in result
    assert result.count("DEFA BAFA") == 4


def test_truncate_keeps_n_bars_without_leading_barline() -> None:
    # Regression test: a tune whose body opens directly with notes (no
    # leading "|") previously got one extra bar, since the leading pipe of
    # a barred tune was implicitly relied on to absorb an off-by-one.
    abc = "K:Ador\n~A3B A2GE|A2GA BGDB|~A3B AGEF|G2GA BGDB|\n~A3B A2GE|A2GA BGDB|A2dB AGEF|G2GA Bdd2||\n"
    result = truncate_to_bars(abc, 4)
    assert result == "K:Ador\n~A3B A2GE|A2GA BGDB|~A3B AGEF|G2GA BGDB|\n"
    assert result.count("|") == 4


def test_truncate_returns_unchanged_when_fewer_bars_than_requested() -> None:
    abc = "K:D\n|:DEFA BAFA:|\n"
    result = truncate_to_bars(abc, 4)
    assert result == abc


def test_truncate_no_k_header_returns_unchanged() -> None:
    abc = "T:x\nDEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA\n"
    assert truncate_to_bars(abc, 4) == abc


# ── parse_key ────────────────────────────────────────────────────────────────


def test_parse_key_bare_major() -> None:
    assert parse_key("D") == (KeyRoot.D, KeyMode.major)


def test_parse_key_minor_shorthand() -> None:
    assert parse_key("Bm") == (KeyRoot.B, KeyMode.minor)


def test_parse_key_dorian_abbreviation() -> None:
    assert parse_key("Ador") == (KeyRoot.A, KeyMode.dorian)


def test_parse_key_thesession_style_full_word() -> None:
    # TheSession's mode_raw values spell modes out in full with no separator, e.g. "Gmajor"/"Edorian".
    assert parse_key("Gmajor") == (KeyRoot.G, KeyMode.major)
    assert parse_key("Edorian") == (KeyRoot.E, KeyMode.dorian)


def test_parse_key_flat_root() -> None:
    assert parse_key("Bbdor") == (KeyRoot.B_flat, KeyMode.dorian)


def test_parse_key_sharp_root() -> None:
    assert parse_key("F#") == (KeyRoot.F_sharp, KeyMode.major)


def test_parse_key_unrecognized_mode_returns_none() -> None:
    assert parse_key("Dlocrian") is None


def test_parse_key_unparseable_returns_none() -> None:
    assert parse_key("nonsense") is None


# ── transpose_abc (#122) ───────────────────────────────────────────────────────


def _abc(key: str, body: str, extra_headers: str = "") -> str:
    return f"X:1\nT:Test\nL:1/8\n{extra_headers}K:{key}\n{body}\n"


def test_transpose_zero_is_identity() -> None:
    abc = _abc("D", "DEFG ABcd")
    assert transpose_abc(abc, 0) == abc


def test_transpose_updates_key_header() -> None:
    result = transpose_abc(_abc("D", "DEFG"), 2)
    assert "K:E\n" in result


def test_transpose_shifts_note_letters_up_a_tone() -> None:
    result = transpose_abc(_abc("D", "DEFG ABcd"), 2)
    body = result.splitlines()[-1]
    assert body == "EFGA Bcde"


def test_transpose_shifts_note_letters_down() -> None:
    result = transpose_abc(_abc("D", "DEFG ABcd"), -2)
    body = result.splitlines()[-1]
    assert body == "CDEF GABc"


def test_transpose_adds_z_header_when_absent() -> None:
    result = transpose_abc(_abc("D", "DEFG"), 1)
    lines = result.splitlines()
    z_lines = [l for l in lines if l.startswith("Z:")]
    assert len(z_lines) == 1
    assert "transposed +1 semitone)" in z_lines[0]


def test_transpose_appends_to_existing_z_header() -> None:
    result = transpose_abc(_abc("D", "DEFG", extra_headers="Z:Collected from Joe Blow\n"), 1)
    lines = result.splitlines()
    z_lines = [l for l in lines if l.startswith("Z:")]
    assert len(z_lines) == 1
    assert z_lines[0].startswith("Z:Collected from Joe Blow")
    assert "transposed +1 semitone)" in z_lines[0]


def test_transpose_negative_note_says_semitones_plural() -> None:
    result = transpose_abc(_abc("D", "DEFG"), -3)
    assert "transposed -3 semitones)" in result


def test_transpose_octave_up_preserves_letters_exactly() -> None:
    body = "B=c|:B2EF G2AG|F2EF D2B,A,|B,EEF GABc|d2cB ABcd:|"
    result = transpose_abc(_abc("D", body), 12)
    result_body = result.splitlines()[-1]
    # Every letter should be one case-step higher (or gain an apostrophe/lose
    # a comma) but the underlying note-name sequence must be identical.
    assert result_body.replace("'", "").lower().replace(",", "") == body.lower().replace(",", "").replace("'", "")


def test_transpose_natural_preferred_over_enharmonic_sharp() -> None:
    # Bb in C major, up a fifth (+7) lands on pitch class 5 in G major, which
    # has two valid single-accidental spellings: "=F" (cancelling G major's
    # own F# signature) or the enharmonic "^E". "=F" is the far more expected
    # one, since it's the same letter the source note was already using.
    result = transpose_abc(_abc("C", "_BCDE"), 7)
    body = result.splitlines()[-1]
    assert "=f" in body
    assert "^e" not in body


def test_transpose_bar_scoped_accidental_carries_within_bar() -> None:
    # An implicit repeat of a flatted note within the same bar (no explicit
    # accidental the second time) must carry the same flat as the first.
    result = transpose_abc(_abc("C", "_BCDB"), 7)
    body = result.splitlines()[-1]
    assert body.count("=f") == 2


def test_transpose_accidental_does_not_carry_across_bar_line() -> None:
    # The same note in a new bar, with no explicit accidental, must fall back
    # to the source key's own signature default rather than the previous
    # bar's carried flat.
    result = transpose_abc(_abc("C", "_BCD|B"), 7)
    bar1, bar2 = result.splitlines()[-1].split("|")
    assert "=f" in bar1
    assert bar2 == "f"


def test_transpose_chord_symbol_untouched() -> None:
    result = transpose_abc(_abc("D", '"G"DEFG "Em"ABcd'), 2)
    body = result.splitlines()[-1]
    assert '"G"' in body
    assert '"Em"' in body


def test_transpose_bang_decoration_untouched() -> None:
    result = transpose_abc(_abc("D", "!fermata!DEFG"), 2)
    body = result.splitlines()[-1]
    assert "!fermata!" in body


def test_transpose_preserves_dorian_mode() -> None:
    result = transpose_abc(_abc("Ador", "ABcd"), 2)
    assert "K:Bdor\n" in result


def test_transpose_preserves_minor_mode() -> None:
    result = transpose_abc(_abc("Am", "ABcd"), 2)
    assert "K:Bm\n" in result


def test_transpose_no_key_header_returns_unchanged() -> None:
    abc = "X:1\nT:No Key\nL:1/8\nDEFG\n"
    assert transpose_abc(abc, 2) == abc


def test_transpose_tritone_from_c_major_uses_sharp_bias() -> None:
    result = transpose_abc(_abc("C", "C"), 6)
    assert "K:F#\n" in result


def test_signature_for_modes_share_relative_major() -> None:
    # D dorian, A minor, and G mixolydian are all "white notes" (0 sharps/flats),
    # matching C major's signature.
    assert _signature_for("D", "dorian") == 0
    assert _signature_for("A", "minor") == 0
    assert _signature_for("G", "mixolydian") == 0
    assert _signature_for("F", "lydian") == 0


def test_transpose_round_trip_up_then_down_restores_key_and_notes() -> None:
    # Transposing up then back down by the same amount must restore the
    # original key and (for a body with no accidentals to complicate things)
    # the exact note sequence.
    abc = _abc("D", "DEFG ABcd|efga bagf")
    up = transpose_abc(abc, 3)
    back = transpose_abc(up, -3)
    assert "K:D\n" in back
    assert back.splitlines()[-1] == abc.splitlines()[-1]
