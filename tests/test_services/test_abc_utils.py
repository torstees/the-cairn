from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, Tune, TuneSetting, TuneType
from cairn.services.abc_utils import build_abc, parse_key, truncate_to_bars

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
