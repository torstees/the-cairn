(function () {
  var RENDER_OPTS = {
    responsive: "resize",
    add_classes: true,
    wrap: { preferredMeasuresPerLine: 4, minSpacing: 1.5, maxSpacing: 2.5 },
    clickListener: handleScoreClick,
  };

  var PREVIEW_OPTS = {
    responsive: "resize",
    add_classes: true,
    wrap: { preferredMeasuresPerLine: 4, minSpacing: 1.5, maxSpacing: 2.5 },
  };

  // Shared ABC constants — must match cairn/services/abc_utils.py
  var MAPPED_HEADERS = new Set(["X","T","C","O","A","R","M","S","Z","N","K"]);
  var MODE_SUFFIX = { major: "", minor: "m", dorian: "dor", mixolydian: "mix", lydian: "lyd" };
  var DEFAULT_TEMPO = {
    reel: "Q:1/4=80", jig: "Q:3/8=80", slip_jig: "Q:3/8=80",
    hornpipe: "Q:1/4=70", polka: "Q:1/4=90", slide: "Q:3/8=80",
    strathspey: "Q:1/4=70", waltz: "Q:1/4=80", air: "Q:1/4=60",
    march: "Q:1/4=80", barndance: "Q:1/4=80",
  };

  var visualObj = null;
  var activeSynth = null;
  var activeAudioCtx = null;
  var currentAbcString = "";
  var naturalBpm = null;
  var activeSettingId = null;
  var cursorHighlightEl = null;
  var rebuildMapTimer = null;

  // ── tablature (guitar/banjo/mandolin/bouzouki) ─────────────────────────────
  // Rendering-only — never touches the stored ABC string. See #233.
  var currentTablature = null;

  // Always-available "Standard" tuning per instrument, with no saved-tunings
  // round trip needed. Bouzouki and (tenor) banjo share mandolin's 4-string
  // GDAE layout, matching services/tunings.py's PRESET_TUNINGS.
  var TABLATURE_STANDARD_TUNINGS = {
    guitar: ["E,", "A,", "D", "G", "B", "e"],
    mandolin: ["G,", "D", "A", "e"],
    bouzouki: ["G,", "D", "A", "e"],
    banjo: ["G,", "D", "A", "e"],
  };

  // abcjs's own `instrument` option only recognizes a handful of layouts —
  // derived from string count, not from the Cairn instrument name, so a
  // custom tuning with an unexpected string count still renders sensibly.
  function tablatureLayoutFor(stringCount) {
    if (stringCount === 6) return "guitar";
    if (stringCount === 5) return "fiveString";
    return "mandolin";
  }

  // Shared AudioContext — drone and metronome use the same context to avoid
  // browser volume normalisation side-effects from concurrent contexts.
  var sharedAudioCtx = null;

  function getAudioCtx() {
    if (!sharedAudioCtx || sharedAudioCtx.state === "closed") {
      sharedAudioCtx = new AudioContext();
    }
    if (sharedAudioCtx.state === "suspended") {
      sharedAudioCtx.resume();
    }
    return sharedAudioCtx;
  }

  var droneOsc = null;
  var droneGain = null;
  var droneKeys = [];
  var droneKeyIndex = 0;

  var NOTE_FREQ = {
    "C": 261.63, "C#": 277.18, "Db": 277.18,
    "D": 293.66, "D#": 311.13, "Eb": 311.13,
    "E": 329.63,
    "F": 349.23, "F#": 369.99, "Gb": 369.99,
    "G": 392.00, "G#": 415.30, "Ab": 415.30,
    "A": 440.00, "A#": 466.16, "Bb": 466.16,
    "B": 493.88,
  };

  // ── ABC helpers ────────────────────────────────────────────────────────────

  function extractBpm(abcString) {
    var m = abcString.match(/^Q:[^=\n]*=(\d+)/m) || abcString.match(/^Q:(\d+)/m);
    return m ? parseInt(m[1], 10) : null;
  }

  function setQBpm(abcString, bpm) {
    if (/^Q:[^=\n]+=\d+/m.test(abcString)) {
      return abcString.replace(/^(Q:[^=\n]+=)\d+/m, "$1" + bpm);
    }
    if (/^Q:\d+/m.test(abcString)) {
      return abcString.replace(/^Q:\d+/m, "Q:" + bpm);
    }
    return abcString.replace(/^K:/m, "Q:1/4=" + bpm + "\nK:");
  }

  // Length of the Q: line that was stripped for display (to convert between
  // textarea char positions and visualObj char positions).
  function qLineLength(abcString) {
    var m = (abcString || "").match(/^Q:[^\n]*\n/m);
    return m ? m[0].length : 0;
  }

  // ── cursor highlighting ────────────────────────────────────────────────────

  // Builds a [{start, end, el}] map by zipping parsed note elements (in order)
  // with .abcjs-note SVG elements (in DOM order). Best-effort — may misalign
  // on chords or grace notes.
  function buildCharMap(tuneObj, renderDivId) {
    var parsed = [];
    if (tuneObj && tuneObj.lines) {
      tuneObj.lines.forEach(function (line) {
        (line.staff || []).forEach(function (staff) {
          (staff.voices || []).forEach(function (voice) {
            voice.forEach(function (elem) {
              if (elem.el_type === "note" && typeof elem.startChar === "number") {
                parsed.push({ start: elem.startChar, end: elem.endChar || elem.startChar });
              }
            });
          });
        });
      });
    }
    var svgEls = document.querySelectorAll("#" + renderDivId + " .abcjs-note, #" + renderDivId + " .abcjs-rest");
    var map = [];
    var len = Math.min(parsed.length, svgEls.length);
    for (var i = 0; i < len; i++) {
      map.push({ start: parsed[i].start, end: parsed[i].end, el: svgEls[i] });
    }
    return map;
  }

  var charMap = [];

  function clearCursorHighlight() {
    if (cursorHighlightEl) {
      cursorHighlightEl.classList.remove("abcjs-cursor-active");
      cursorHighlightEl = null;
    }
  }

  // Score note click → highlight that note, move textarea cursor there.
  // NOTE: mouseEvent.currentTarget is the SVG container (ABCJS uses event
  // delegation), NOT the individual note <g> element. Use charMap instead.
  function handleScoreClick(abcElem, tuneNumber, classes, analysis, drag, mouseEvent) {
    clearCursorHighlight();
    if (abcElem && typeof abcElem.startChar === "number") {
      for (var i = 0; i < charMap.length; i++) {
        if (charMap[i].start === abcElem.startChar) {
          charMap[i].el.classList.add("abcjs-cursor-active");
          cursorHighlightEl = charMap[i].el;
          break;
        }
      }
      var editor = document.getElementById("abc-editor");
      if (editor) {
        var pos = abcElem.startChar + qLineLength(currentAbcString);
        editor.focus();
        editor.setSelectionRange(pos, pos);
      }
    }
  }

  // Textarea cursor move → highlight the corresponding note in the score.
  function syncCursorToScore() {
    var editor = document.getElementById("abc-editor");
    if (!editor) return;
    // Lazy rebuild: ABCJS responsive: "resize" re-renders after layout, invalidating
    // the charMap that was built synchronously during render(). Rebuild if empty.
    if (!charMap.length && visualObj && visualObj[0]) {
      charMap = buildCharMap(visualObj[0], "abc-render");
    }
    if (!charMap.length) return;
    var displayPos = editor.selectionStart - qLineLength(currentAbcString);
    clearCursorHighlight();
    // Find the note whose start is closest to and <= cursor position (nearest-left).
    var best = null;
    for (var i = 0; i < charMap.length; i++) {
      var entry = charMap[i];
      if (entry.start <= displayPos && (best === null || entry.start > best.start)) {
        best = entry;
      }
    }
    if (best && best.el) {
      best.el.classList.add("abcjs-cursor-active");
      cursorHighlightEl = best.el;
    }
  }

  // ── detail page ────────────────────────────────────────────────────────────

  function applyActiveCard(settingId) {
    document.querySelectorAll("[data-setting-id]").forEach(function (el) {
      el.classList.remove("ring-2", "ring-stone-400", "bg-stone-50");
    });
    var card = document.querySelector('[data-setting-id="' + settingId + '"]');
    if (card) card.classList.add("ring-2", "ring-stone-400", "bg-stone-50");
  }

  function selectSetting(settingId) {
    activeSettingId = settingId;
    applyActiveCard(settingId);

    var tmpl = document.getElementById("abc-setting-" + settingId);
    if (!tmpl) { updateDroneDisplay(); return; }
    var abc = tmpl.content.textContent.trim();
    if (!abc) { updateDroneDisplay(); return; }

    if (activeSynth) {
      activeSynth.stop();
      teardownAudio();
      var btn = document.getElementById("abc-play");
      if (btn) btn.textContent = "▶ Play";
    }

    render(abc);

    var editor = document.getElementById("abc-editor");
    if (editor) editor.value = abc;

    naturalBpm = extractBpm(abc);
    var tempoSlider = document.getElementById("abc-tempo");
    var tempoLabel = document.getElementById("abc-tempo-label");
    if (naturalBpm) {
      var seededBpm = clampTempo(naturalBpm, tempoSlider);
      if (tempoSlider) tempoSlider.value = seededBpm;
      if (tempoLabel) tempoLabel.value = seededBpm;
    }
  }

  // Anchors the two octave-nudge hitboxes (#122) to the clef of the first
  // rendered staff line, since ABCJS's title/rhythm text block above the
  // staff varies in height per tune — a fixed top offset would drift off
  // the staff for tunes with e.g. a composer line. "Down" only widens
  // leftward from the clef (toward the always note-free margin before it);
  // "up" widens generously both ways since a note high enough to collide is
  // effectively never used in practice (see template comment).
  function positionOctaveOverlays() {
    var upLink = document.getElementById("octave-up-link");
    var downLink = document.getElementById("octave-down-link");
    if (!upLink || !downLink) return;
    var container = upLink.offsetParent;
    var clef = document.querySelector("#abc-render .abcjs-clef");
    if (!container || !clef) return;
    var containerBox = container.getBoundingClientRect();
    var clefBox = clef.getBoundingClientRect();
    var left = clefBox.left - containerBox.left;
    var top = clefBox.top - containerBox.top;
    var bottom = clefBox.bottom - containerBox.top;

    upLink.style.left = (left - 60) + "px";
    upLink.style.top = (top - 22) + "px";
    upLink.style.width = "220px";
    upLink.style.height = "24px";

    downLink.style.left = (left - 60) + "px";
    downLink.style.top = bottom + "px";
    downLink.style.width = "60px";
    downLink.style.height = "24px";
  }

  function render(abcString) {
    currentAbcString = abcString;
    updateDroneDisplay();
    clearCursorHighlight();
    charMap = [];
    if (rebuildMapTimer) { clearTimeout(rebuildMapTimer); rebuildMapTimer = null; }
    // Strip Q: from the visual render — tempo annotation is misleading since
    // it never updates when the slider moves. Audio uses currentAbcString.
    // Global flag: a combined set ABC concatenates one Q: line per member tune.
    var displayAbc = abcString.replace(/^Q:[^\n]*\n?/gm, "");
    var opts = currentTablature ? Object.assign({}, RENDER_OPTS, { tablature: [currentTablature] }) : RENDER_OPTS;
    visualObj = ABCJS.renderAbc("abc-render", displayAbc, opts);
    positionOctaveOverlays();
    if (visualObj && visualObj[0]) {
      charMap = buildCharMap(visualObj[0], "abc-render");
      // ABCJS responsive:"resize" fires a ResizeObserver callback after layout,
      // replacing the initial SVG and making the charMap stale. Rebuild after
      // the next paint to capture the final DOM elements.
      rebuildMapTimer = setTimeout(function () {
        charMap = buildCharMap(visualObj[0], "abc-render");
        positionOctaveOverlays();
        rebuildMapTimer = null;
      }, 150);
    }
  }

  function renderScore() {
    var abcSource = document.getElementById("abc-source");
    if (!abcSource) return;
    var abcString = abcSource.content.textContent.trim();
    if (!abcString) return;

    render(abcString);

    var coreCard = document.querySelector("[data-setting-id][data-is-core='true']") ||
                   document.querySelector("[data-setting-id]");
    if (coreCard) {
      activeSettingId = parseInt(coreCard.dataset.settingId, 10);
      applyActiveCard(activeSettingId);
    }
    if (window.__cairnActiveSettingId && window.__cairnActiveSettingId !== activeSettingId) {
      selectSetting(window.__cairnActiveSettingId);
    }

    var btn = document.getElementById("abc-play");
    var tempoSlider = document.getElementById("abc-tempo");
    var tempoLabel = document.getElementById("abc-tempo-label");

    naturalBpm = extractBpm(abcString);
    if (naturalBpm) {
      var seededBpm = clampTempo(naturalBpm, tempoSlider);
      if (tempoSlider) tempoSlider.value = seededBpm;
      if (tempoLabel) tempoLabel.value = seededBpm;
    }

    if (tempoSlider && tempoLabel) {
      tempoSlider.addEventListener("input", function () {
        tempoLabel.value = this.value;
        setLiveMetroTempo(parseInt(this.value, 10));
        if (activeSynth) {
          activeSynth.stop();
          teardownAudio();
          if (btn) btn.textContent = "▶ Play";
        }
      });
      wireTempoLabelEditing(tempoSlider, tempoLabel);
    }

    if (btn && visualObj && visualObj[0]) {
      if (!ABCJS.synth.supportsAudio()) {
        btn.disabled = true;
        btn.title = "Audio is not supported in this browser";
      } else {
        btn.addEventListener("click", handlePlayStop);
      }
    }

    var editor = document.getElementById("abc-editor");
    if (editor) {
      editor.addEventListener("input", function () {
        if (activeSynth) {
          activeSynth.stop();
          teardownAudio();
          if (btn) btn.textContent = "▶ Play";
        }
        render(editor.value);
      });
      editor.addEventListener("keyup", syncCursorToScore);
      editor.addEventListener("click", syncCursorToScore);
    }

    initDrone();
    initMetronome();
    initTablatureControls();
  }

  // Wires the "Show tablature" checkbox + instrument/tuning <select>s on
  // tunes/detail.html (see #233) -- a pure client-side re-render, no HTMX
  // round trip, since tablature is only an abcjs rendering option. Restores
  // the last-used instrument/tuning from localStorage so it's remembered
  // across tunes without any new server-side state.
  function initTablatureControls() {
    var toggle = document.getElementById("tablature-toggle");
    var instrumentSelect = document.getElementById("tablature-instrument");
    var tuningSelect = document.getElementById("tablature-tuning");
    if (!toggle || !instrumentSelect || !tuningSelect) return;

    // Read fresh each call, not snapshotted -- window.__cairnTunings is
    // reassigned after an add/delete via the tunings-section HTMX partial
    // (see the htmx:afterSwap listener below), and this needs to see that.
    function tuningsForInstrument(instrument) {
      var myTunings = window.__cairnTunings || [];
      return myTunings.filter(function (t) { return t.instrument === instrument; });
    }

    function populateTuningSelect() {
      var instrument = instrumentSelect.value;
      tuningSelect.innerHTML = "";
      var standardOpt = document.createElement("option");
      standardOpt.value = "__standard__";
      standardOpt.textContent = "Standard";
      tuningSelect.appendChild(standardOpt);
      tuningsForInstrument(instrument).forEach(function (t) {
        var opt = document.createElement("option");
        opt.value = t.name;
        opt.textContent = t.name;
        tuningSelect.appendChild(opt);
      });
    }

    function currentStrings() {
      var instrument = instrumentSelect.value;
      var name = tuningSelect.value;
      if (name && name !== "__standard__") {
        var match = tuningsForInstrument(instrument).filter(function (t) { return t.name === name; })[0];
        if (match) return match.strings;
      }
      return TABLATURE_STANDARD_TUNINGS[instrument] || TABLATURE_STANDARD_TUNINGS.guitar;
    }

    function savePreference() {
      try {
        localStorage.setItem("cairnTablature", JSON.stringify({
          on: toggle.checked, instrument: instrumentSelect.value, tuning: tuningSelect.value,
        }));
      } catch (e) {
        // localStorage unavailable (private browsing etc.) -- just skip persistence.
      }
    }

    function applyTablature() {
      if (!toggle.checked) {
        currentTablature = null;
      } else {
        var strings = currentStrings();
        var instrumentLabel = instrumentSelect.options[instrumentSelect.selectedIndex].text;
        currentTablature = {
          instrument: tablatureLayoutFor(strings.length),
          tuning: strings,
          label: instrumentLabel + " (%T)",
        };
      }
      render(currentAbcString);
      savePreference();
    }

    instrumentSelect.addEventListener("change", function () { populateTuningSelect(); applyTablature(); });
    tuningSelect.addEventListener("change", applyTablature);
    toggle.addEventListener("change", function () {
      instrumentSelect.disabled = !toggle.checked;
      tuningSelect.disabled = !toggle.checked;
      applyTablature();
    });

    // Refreshed via the htmx:afterSwap listener below whenever the
    // tunings-section partial reloads (a tuning was added/deleted) --
    // repopulates the <select> from the now-current window.__cairnTunings.
    window.__cairnRefreshTuningSelect = populateTuningSelect;

    var restored = null;
    try {
      restored = JSON.parse(localStorage.getItem("cairnTablature") || "null");
    } catch (e) {
      // Ignore -- treat as no saved preference.
    }
    if (restored && restored.instrument) instrumentSelect.value = restored.instrument;
    populateTuningSelect();
    if (restored && restored.tuning) tuningSelect.value = restored.tuning;
    if (restored && restored.on) {
      toggle.checked = true;
      instrumentSelect.disabled = false;
      tuningSelect.disabled = false;
      applyTablature();
    }
  }

  function handlePlayStop() {
    var btn = document.getElementById("abc-play");
    if (!btn) return;

    if (activeSynth) {
      activeSynth.stop();
      teardownAudio();
      btn.textContent = "▶ Play";
      return;
    }

    if (!currentAbcString) return;

    btn.textContent = "Loading…";
    btn.disabled = true;

    var sliderBpm = parseInt((document.getElementById("abc-tempo") || {}).value, 10)
                    || naturalBpm || 100;
    var audioVisual = ABCJS.renderAbc("abc-audio", setQBpm(currentAbcString, sliderBpm), {});

    var ctx = new AudioContext();
    activeAudioCtx = ctx;
    var synth = new ABCJS.synth.CreateSynth();
    activeSynth = synth;

    synth.init({
      audioContext: ctx,
      visualObj: audioVisual[0],
      options: {
        onEnded: function () {
          teardownAudio();
          if (btn) btn.textContent = "▶ Play";
        },
      },
    }).then(function () {
      return synth.prime();
    }).then(function () {
      synth.start();
      btn.textContent = "■ Stop";
      btn.disabled = false;
    }).catch(function (err) {
      console.error("abcjs audio error:", err);
      teardownAudio();
      btn.textContent = "▶ Play";
      btn.disabled = false;
    });
  }

  function teardownAudio() {
    activeSynth = null;
    if (activeAudioCtx) {
      activeAudioCtx.close();
      activeAudioCtx = null;
    }
  }

  // ── drone ──────────────────────────────────────────────────────────────────

  function extractKeyRoots(abcString) {
    // Match both standalone header lines (K:D) and inline key changes ([K:D]).
    var re = /(?:^|\[)K:\s*([A-G][b#]?)/gm;
    var seen = {};
    var roots = [];
    var m;
    while ((m = re.exec(abcString || "")) !== null) {
      var key = m[1];
      if (key && !seen[key]) { seen[key] = true; roots.push(key); }
    }
    return roots;
  }

  function startDrone(freq) {
    stopDrone();
    var ctx = getAudioCtx();
    droneGain = ctx.createGain();
    droneGain.gain.setValueAtTime(0.35, ctx.currentTime);
    droneOsc = ctx.createOscillator();
    droneOsc.type = "sine";
    droneOsc.frequency.setValueAtTime(freq, ctx.currentTime);
    droneOsc.connect(droneGain);
    droneGain.connect(ctx.destination);
    droneOsc.start();
  }

  function stopDrone() {
    if (droneOsc) { try { droneOsc.stop(); } catch (e) {} droneOsc = null; }
    droneGain = null;
  }

  function updateDroneDisplay() {
    var controls = document.getElementById("drone-controls");
    if (!controls) return;

    droneKeys = extractKeyRoots(currentAbcString);

    // Fall back to the tune's key root from the settings section metadata
    // when the ABC hasn't been loaded yet or yielded no K: header.
    if (!droneKeys.length) {
      var sec = document.getElementById("settings-section");
      var rootAttr = sec && sec.dataset.keyRoot;
      if (rootAttr) droneKeys = [rootAttr];
    }

    droneKeyIndex = 0;

    var keyLabel = document.getElementById("drone-key");
    var prevBtn = document.getElementById("drone-prev");
    var nextBtn = document.getElementById("drone-next");
    var playBtn = document.getElementById("drone-play");

    if (!droneKeys.length) {
      controls.classList.add("hidden");
      stopDrone();
      if (playBtn) playBtn.textContent = "♪ Drone";
      return;
    }

    controls.classList.remove("hidden");
    if (keyLabel) keyLabel.textContent = droneKeys[droneKeyIndex];

    var multi = droneKeys.length > 1;
    if (prevBtn) prevBtn.classList.toggle("hidden", !multi);
    if (nextBtn) nextBtn.classList.toggle("hidden", !multi);

    // If drone is currently playing, update frequency to match the new key
    if (droneOsc && sharedAudioCtx) {
      droneOsc.frequency.setValueAtTime(NOTE_FREQ[droneKeys[droneKeyIndex]] || 440, sharedAudioCtx.currentTime);
    }
  }

  function initDrone() {
    var playBtn = document.getElementById("drone-play");
    var prevBtn = document.getElementById("drone-prev");
    var nextBtn = document.getElementById("drone-next");
    if (!playBtn) return;

    playBtn.addEventListener("click", function () {
      if (droneOsc) {
        stopDrone();
        playBtn.textContent = "♪ Drone";
      } else {
        startDrone(NOTE_FREQ[droneKeys[droneKeyIndex]] || 440);
        playBtn.textContent = "■ Drone";
      }
    });

    function shiftDroneKey(delta) {
      if (!droneKeys.length) return;
      droneKeyIndex = (droneKeyIndex + delta + droneKeys.length) % droneKeys.length;
      var keyLabel = document.getElementById("drone-key");
      if (keyLabel) keyLabel.textContent = droneKeys[droneKeyIndex];
      if (droneOsc && sharedAudioCtx) {
        droneOsc.frequency.setValueAtTime(NOTE_FREQ[droneKeys[droneKeyIndex]] || 440, sharedAudioCtx.currentTime);
      }
    }

    if (prevBtn) prevBtn.addEventListener("click", function () { shiftDroneKey(-1); });
    if (nextBtn) nextBtn.addEventListener("click", function () { shiftDroneKey(1); });
  }

  // ── metronome ──────────────────────────────────────────────────────────────

  // Beat patterns keyed by TuneType value.
  // Each entry is an array of { freq, gain } objects representing one measure.
  // H = primary downbeat, M = secondary downbeat, L = off-beat subdivision.
  var H = { freq: 1320, gain: 0.45 };
  var M = { freq: 1050, gain: 0.32 };
  var L = { freq:  820, gain: 0.20 };

  var METRO_PATTERNS = {
    // 6/8 — two groups of three: strong, 2 light, medium, 2 light
    jig:        [H, L, L, M, L, L],
    // 9/8 — three groups of three
    slip_jig:   [H, L, L, M, L, L, M, L, L],
    // 12/8 — four groups of three; three equal secondary downbeats
    slide:      [H, L, L, M, L, L, M, L, L, M, L, L],
    // 4/4 / cut time — strong, off, medium, off
    reel:       [H, L, M, L],
    hornpipe:   [H, L, M, L],
    barndance:  [H, L, M, L],
    // 2/4 — treat as two-beat for practice purposes
    march:      [H, L, M, L],
    polka:      [H, L, M, L],
    // 3/4
    waltz:      [H, L, L],
    // Strathspey is in 4/4 with a dotted feel — same macro-shape as reel
    strathspey: [H, L, M, L],
    // Air has no fixed metre; default 4-beat keeps things usable
    air:        [H, L, M, L],
  };

  // Compound-meter types display/accept tempo as the dotted-quarter (main
  // beat) rate, but METRO_PATTERNS above has one slot per eighth note — 3
  // slots per beat for these types. metroSchedule() divides the beat
  // interval by this to get the actual per-slot click interval, so the
  // number the user sees and types always means beats per minute, never a
  // raw per-slot rate. Anything not listed here is 1 (one slot per beat).
  var METRO_SUBDIVISION = {
    jig: 3,
    slip_jig: 3,
    slide: 3,
  };

  var metroPattern = METRO_PATTERNS.reel;  // resolved in initMetronome
  var metroSubdivision = 1;                // resolved alongside metroPattern
  var metroBpm = 100;                      // live tempo metroSchedule reads each tick
  var metroTimer = null;
  var metroNextBeat = 0;
  // Time the metronome was started, OR last had its tempo live-changed
  // (setLiveMetroTempo resets this too) — "how long has this *specific*
  // tempo actually been running," used by the click handlers' record-this-
  // tempo threshold. Distinct from metroNextBeat/metroBeatCount, which track
  // audible beat phase and must never reset from a live tempo change.
  var metroStartTime = 0;
  var metroBeatCount = 0;
  var metroNodes = [];          // scheduled oscillators — cancelled on stop
  var metroGains = [];          // corresponding gain nodes — disconnected on stop
  var METRO_LOOKAHEAD = 25;    // ms between scheduler ticks
  var METRO_SCHEDULE = 0.25;   // seconds to schedule ahead — must exceed worst-case GC pause

  function metroSchedule() {
    var ctx = sharedAudioCtx;
    // Read the live tempo/subdivision fresh on every tick (rather than
    // capturing them as of when the metronome started) so a slider drag or
    // tempo-field edit applies with no stop/restart and no beat-phase reset.
    // Beats already scheduled up to METRO_SCHEDULE seconds ahead in a prior
    // tick still play at the old interval, so the audible change lands
    // within METRO_SCHEDULE, not METRO_LOOKAHEAD — imperceptible in practice
    // at METRO_SCHEDULE's current 0.25s, but worth naming precisely. metroBpm
    // is the displayed beats-per-minute rate; metroSubdivision (3 for
    // jig/slip_jig/slide, 1 otherwise) converts that into the actual
    // per-pattern-slot interval, since METRO_PATTERNS has one slot per
    // eighth note for those meters.
    var interval = (60.0 / metroBpm) / metroSubdivision;
    // If the JS timer fired late (tab hidden, busy thread), skip forward rather
    // than flooding with catch-up beats that all land within milliseconds.
    while (metroNextBeat < ctx.currentTime - interval) {
      metroNextBeat += interval;
      metroBeatCount++;
    }
    while (metroNextBeat < ctx.currentTime + METRO_SCHEDULE) {
      var t = Math.max(metroNextBeat, ctx.currentTime + 0.005);
      var beat = metroPattern[metroBeatCount % metroPattern.length];
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.frequency.value = beat.freq;
      // 2 ms linear ramp from 0 avoids the onset click from a hard gain step.
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(beat.gain, t + 0.002);
      gain.gain.setTargetAtTime(0.0001, t + 0.002, 0.02);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.1);
      // Disconnect both nodes when done — zombie gain nodes left in the graph
      // accumulate across beats and cause volume drift and render-thread pressure.
      (function(node, gainNode) {
        node.onended = function() {
          try { gainNode.disconnect(); } catch (e) {}
          var i = metroNodes.indexOf(node);
          if (i !== -1) { metroNodes.splice(i, 1); metroGains.splice(i, 1); }
        };
      }(osc, gain));
      metroNodes.push(osc);
      metroGains.push(gain);
      metroNextBeat += interval;
      metroBeatCount++;
    }
    metroTimer = setTimeout(metroSchedule, METRO_LOOKAHEAD);
  }

  function startMetronome(bpm) {
    stopMetronome();
    var ctx = getAudioCtx();
    metroNextBeat = ctx.currentTime;
    metroStartTime = ctx.currentTime;
    metroBeatCount = 0;
    metroBpm = bpm;
    metroSchedule();
  }

  function stopMetronome() {
    if (metroTimer) { clearTimeout(metroTimer); metroTimer = null; }
    metroNodes.forEach(function(osc) { try { osc.stop(); } catch(e) {} });
    metroGains.forEach(function(g) { try { g.disconnect(); } catch(e) {} });
    metroNodes = [];
    metroGains = [];
  }

  // __cairnBeatsPerBar is the time signature's numerator (e.g. 6 for a 6/8
  // jig) — a slot count, not a beat count, for compound meters. Divide by
  // the subdivision to get actual dotted-quarter beats/bar, matching bpm's
  // beats-per-minute meaning, for the Metro click handlers' recording-
  // duration threshold.
  function currentBeatsPerBar() {
    return (window.__cairnBeatsPerBar || 4) / metroSubdivision;
  }

  // SMuFL (Bravura Text) codepoints for the metronome-mark label — "tail up"
  // quarter note, plus an augmentation dot for the compound-meter (3-per-
  // beat) types, so the label always shows the same beat unit metroSchedule
  // is actually counting. Derived from metroSubdivision directly (rather
  // than a second tune-type lookup) so the two can't drift out of sync.
  var SMUFL_QUARTER_NOTE = "";
  var SMUFL_AUGMENTATION_DOT = "";

  function metroTempoGlyph() {
    return metroSubdivision === 3 ? SMUFL_QUARTER_NOTE + SMUFL_AUGMENTATION_DOT : SMUFL_QUARTER_NOTE;
  }

  // Refresh the #abc-tempo-unit glyph to match the currently-resolved
  // metroSubdivision. Called wherever metroPattern/metroSubdivision are
  // (re)resolved for a tune type, so the glyph and the audible click never
  // disagree about what the tempo number means.
  function updateTempoGlyph() {
    var el = document.getElementById("abc-tempo-unit");
    if (el) el.textContent = metroTempoGlyph();
  }

  // Update the metronome's live tempo without stopping/restarting it — no
  // beat-phase reset, no audible restart click. A no-op if it isn't running;
  // callers don't need to check metroTimer themselves before calling this.
  //
  // metroStartTime also resets here (deliberately — see its declaration):
  // without this, "elapsed time since metroStartTime" — the gate the Metro
  // click handlers use to decide whether a tempo is worth recording — would
  // keep counting time spent at a *different*, earlier tempo, letting a
  // last-second tempo jump right before stopping satisfy that tempo's
  // (smaller, since duration scales inversely with bpm) threshold despite
  // never actually having been played at that speed for long. Resetting it
  // here doesn't touch metroNextBeat/metroBeatCount, so it has no effect on
  // beat continuity — only on how "long enough at this tempo" is measured.
  function setLiveMetroTempo(bpm) {
    if (!metroTimer) return;
    metroBpm = bpm;
    metroStartTime = sharedAudioCtx.currentTime;
  }

  // Clamp a bpm value to the tempo slider's own min/max, falling back to
  // 40-250 if the slider isn't on the page yet.
  function clampTempo(value, slider) {
    var min = slider ? parseInt(slider.min, 10) : NaN;
    var max = slider ? parseInt(slider.max, 10) : NaN;
    if (isNaN(min)) min = 40;
    if (isNaN(max)) max = 250;
    return Math.min(max, Math.max(min, value));
  }

  // Makes the #abc-tempo-label <input type="number"> editable in place: typing
  // a value and pressing Enter (or blurring) clamps it to the slider's range
  // and syncs both controls. Non-numeric input is ignored, restoring the
  // previous value. Updates the metronome's tempo live if it's running.
  function wireTempoLabelEditing(tempoSlider, tempoLabel) {
    if (!tempoSlider || !tempoLabel) return;

    tempoLabel.addEventListener("change", function () {
      // valueAsNumber (rather than parseInt on the string) correctly handles
      // whatever a number input actually accepts, e.g. "1e2" for 100.
      var parsed = tempoLabel.valueAsNumber;
      if (isNaN(parsed)) {
        tempoLabel.value = tempoSlider.value;
        return;
      }
      var clamped = clampTempo(Math.round(parsed), tempoSlider);
      tempoSlider.value = clamped;
      tempoLabel.value = clamped;
      setLiveMetroTempo(clamped);
    });

    tempoLabel.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); tempoLabel.blur(); }
    });
  }

  function initMetronome() {
    var btn = document.getElementById("metro-play");
    if (!btn) return;

    metroPattern = METRO_PATTERNS[window.__cairnTuneType] || METRO_PATTERNS.reel;
    metroSubdivision = METRO_SUBDIVISION[window.__cairnTuneType] || 1;
    updateTempoGlyph();

    if (window.__cairnLastTempo) {
      var slider = document.getElementById("abc-tempo");
      var label  = document.getElementById("abc-tempo-label");
      var seeded = clampTempo(window.__cairnLastTempo, slider);
      if (slider) slider.value = seeded;
      if (label)  label.value = seeded;
    }

    btn.addEventListener("click", function () {
      var slider = document.getElementById("abc-tempo");
      var bpm = slider ? parseInt(slider.value, 10) : 100;

      if (metroTimer) {
        var elapsed = sharedAudioCtx ? sharedAudioCtx.currentTime - metroStartTime : 0;
        var minDuration = (currentBeatsPerBar() * 4 / bpm) * 60;
        var shouldRecord = elapsed >= minDuration;
        stopMetronome();
        btn.textContent = "♩ Metro";
        if (shouldRecord && window.__cairnTuneId) {
          var params = new URLSearchParams();
          params.append("tempo", bpm);
          if (window.__cairnBoxId) params.append("box_id", window.__cairnBoxId);
          fetch("/tunes/" + window.__cairnTuneId + "/tempo", { method: "POST", body: params })
            .then(function (r) { return r.ok ? r.text() : null; })
            .then(function (html) {
              if (!html) return;
              var el = document.getElementById("tempo-history");
              if (el) el.outerHTML = html;
            })
            .catch(function () {});
        }
      } else {
        startMetronome(bpm);
        btn.textContent = "■ Metro";
      }
    });
  }

  // ── edit/new tune form preview ─────────────────────────────────────────────

  function parseUserHeaders(raw) {
    var lines = raw.split("\n");
    var userHeaders = [];
    var musicLines = [];
    var inMusic = false;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (!inMusic) {
        if (!line.trim() || line[0] === "%") continue; // blank lines and ABC comments
        if (line.length >= 2 && line[1] === ":" && /[A-Za-z]/.test(line[0])) {
          if (!MAPPED_HEADERS.has(line[0].toUpperCase())) {
            userHeaders.push(line);
          }
          continue;
        }
      }
      inMusic = true;
      musicLines.push(line);
    }
    return { userHeaders: userHeaders, musicLines: musicLines };
  }

  function getVal(id) {
    var el = document.getElementById(id);
    return el ? el.value.trim() : "";
  }

  function buildFormAbc() {
    var abcRaw = getVal("abc_notation");
    var parsed = parseUserHeaders(abcRaw);
    var userHeaders = parsed.userHeaders;
    var musicLines = parsed.musicLines;

    var tuneType = getVal("tune_type");
    var keyRoot = getVal("key_root");
    var keyMode = getVal("key_mode");
    var timeSig = getVal("time_signature");
    var title = getVal("title");
    var origin = getVal("origin");
    var region = getVal("region");
    var notes = getVal("notes");

    var headers = ["X:1"];
    if (title) headers.push("T:" + title);
    if (origin) headers.push("O:" + origin);
    if (region) headers.push("A:" + region);
    if (tuneType) headers.push("R:" + tuneType);
    if (timeSig) headers.push("M:" + timeSig);

    var hasQ = userHeaders.some(function (h) {
      return h.length >= 2 && h[0].toUpperCase() === "Q" && h[1] === ":";
    });
    if (!hasQ && tuneType) {
      headers.push(DEFAULT_TEMPO[tuneType] || "Q:1/4=100");
    }

    if (notes) headers.push("N:" + notes);
    for (var i = 0; i < userHeaders.length; i++) headers.push(userHeaders[i]);
    if (keyRoot) headers.push("K:" + keyRoot + (MODE_SUFFIX[keyMode] || ""));

    while (musicLines.length && !musicLines[0].trim()) musicLines.shift();
    while (musicLines.length && !musicLines[musicLines.length - 1].trim()) musicLines.pop();

    return headers.join("\n") + (musicLines.length ? "\n" + musicLines.join("\n") : "") + "\n";
  }

  function initFormPreview() {
    var renderDiv = document.getElementById("form-abc-render");
    if (!renderDiv) return;

    function updatePreview() {
      ABCJS.renderAbc("form-abc-render", buildFormAbc(), PREVIEW_OPTS);
    }

    updatePreview();

    var form = document.querySelector("form");
    if (form) {
      form.addEventListener("input", updatePreview);
      form.addEventListener("change", updatePreview);
    }
  }

  // ── setting add/edit preview ───────────────────────────────────────────────

  // Returns the char offset in an ABC string where the music body begins
  // (i.e., after all header lines).
  function musicStartIn(abcString) {
    var lines = abcString.split("\n");
    var pos = 0;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (!line.trim() || line[0] === "%") { pos += line.length + 1; continue; }
      if (line.length >= 2 && line[1] === ":" && /[A-Za-z]/.test(line[0])) {
        pos += line.length + 1; continue;
      }
      return pos;
    }
    return pos;
  }

  // Build a minimal ABC string from the user-typed notation and the tune's
  // metadata (read from data-* attributes on #settings-section).
  function buildSettingAbc(notation, tuneData) {
    var parsed = parseUserHeaders(notation);
    var headers = ["X:1", "T:Preview"];
    if (tuneData.tuneType) headers.push("R:" + tuneData.tuneType);
    if (tuneData.timeSig) headers.push("M:" + tuneData.timeSig);
    var hasQ = parsed.userHeaders.some(function (h) {
      return h.length >= 2 && h[0].toUpperCase() === "Q" && h[1] === ":";
    });
    if (!hasQ && tuneData.tuneType) {
      headers.push(DEFAULT_TEMPO[tuneData.tuneType] || "Q:1/4=100");
    }
    for (var i = 0; i < parsed.userHeaders.length; i++) headers.push(parsed.userHeaders[i]);
    var modeSuffix = MODE_SUFFIX[tuneData.keyMode] || "";
    headers.push("K:" + (tuneData.keyRoot || "C") + modeSuffix);
    var music = parsed.musicLines.join("\n").trim();
    return headers.join("\n") + (music ? "\n" + music : "") + "\n";
  }

  // Wire up a textarea to render a live preview and sync the cursor to the
  // rendered score. Call once per form open (Alpine $nextTick ensures the
  // textarea is visible before this runs).
  function initSettingPreview(textareaId, previewDivId) {
    var textarea = document.getElementById(textareaId);
    var section = document.getElementById("settings-section");
    if (!textarea || !section) return;

    var tuneData = {
      tuneType: section.dataset.tuneType || "",
      keyRoot:  section.dataset.keyRoot  || "C",
      keyMode:  section.dataset.keyMode  || "major",
      timeSig:  section.dataset.timeSig  || "4/4",
    };

    var previewVisualObj = null;
    var previewCharMap = [];
    var previewCursorEl = null;
    var previewRebuildTimer = null;

    function clearPreviewHighlight() {
      if (previewCursorEl) {
        previewCursorEl.classList.remove("abcjs-cursor-active");
        previewCursorEl = null;
      }
    }

    function rebuildPreviewCharMap() {
      previewCharMap = [];
      if (previewVisualObj && previewVisualObj[0]) {
        previewCharMap = buildCharMap(previewVisualObj[0], previewDivId);
      }
    }

    function updatePreview() {
      var abc = buildSettingAbc(textarea.value, tuneData);
      clearPreviewHighlight();
      previewCharMap = [];
      if (previewRebuildTimer) { clearTimeout(previewRebuildTimer); previewRebuildTimer = null; }
      previewVisualObj = ABCJS.renderAbc(previewDivId, abc, PREVIEW_OPTS);
      rebuildPreviewCharMap();
      previewRebuildTimer = setTimeout(function () {
        rebuildPreviewCharMap();
        previewRebuildTimer = null;
      }, 150);
    }

    function syncPreviewCursor() {
      if (!previewCharMap.length) rebuildPreviewCharMap();
      if (!previewCharMap.length) return;
      // Compute where music starts in the textarea and in the built ABC,
      // then translate the cursor position to a built-ABC char offset.
      var rawValue = textarea.value;
      var builtAbc = buildSettingAbc(rawValue, tuneData);
      var relPos = textarea.selectionStart - musicStartIn(rawValue);
      var builtPos = musicStartIn(builtAbc) + relPos;
      clearPreviewHighlight();
      var best = null;
      for (var i = 0; i < previewCharMap.length; i++) {
        var e = previewCharMap[i];
        if (e.start <= builtPos && (best === null || e.start > best.start)) best = e;
      }
      if (best && best.el) {
        best.el.classList.add("abcjs-cursor-active");
        previewCursorEl = best.el;
      }
    }

    // Remove previous listeners if this form was opened before.
    if (textarea._settingPreviewFn) textarea.removeEventListener("input", textarea._settingPreviewFn);
    if (textarea._settingCursorFn) {
      textarea.removeEventListener("keyup", textarea._settingCursorFn);
      textarea.removeEventListener("click", textarea._settingCursorFn);
    }
    textarea._settingPreviewFn = updatePreview;
    textarea._settingCursorFn = syncPreviewCursor;
    textarea.addEventListener("input", updatePreview);
    textarea.addEventListener("keyup", syncPreviewCursor);
    textarea.addEventListener("click", syncPreviewCursor);

    if (textarea.value.trim()) updatePreview();
  }

  function clearCairnModal() {
    var m = document.getElementById("box-setting-modal");
    if (m) m.innerHTML = "";
    document.querySelectorAll(".cairn-modal-backdrop").forEach(function (el) { el.remove(); });
  }

  function closeTheSessionWizard() {
    var m = document.getElementById("thesession-wizard");
    if (m) m.innerHTML = "";
  }

  // Wire up the warmup form textarea to render a live ABCJS preview and sync
  // the cursor to the nearest note. Simpler than initSettingPreview because
  // warmup content is complete ABC — no header prepend or offset translation.
  // Returns { update } so callers can trigger a render on type-select change.
  function initWarmupPreview(textareaId, previewDivId) {
    var textarea = document.getElementById(textareaId);
    if (!textarea) return { update: function () {} };

    var previewVisualObj = null;
    var previewCharMap = [];
    var previewCursorEl = null;
    var previewRebuildTimer = null;

    function clearHighlight() {
      if (previewCursorEl) {
        previewCursorEl.classList.remove("abcjs-cursor-active");
        previewCursorEl = null;
      }
    }

    function rebuildCharMap() {
      previewCharMap = [];
      if (previewVisualObj && previewVisualObj[0]) {
        previewCharMap = buildCharMap(previewVisualObj[0], previewDivId);
      }
    }

    function updatePreview() {
      var src = textarea.value.trim();
      clearHighlight();
      previewCharMap = [];
      if (previewRebuildTimer) { clearTimeout(previewRebuildTimer); previewRebuildTimer = null; }
      if (!src) {
        var div = document.getElementById(previewDivId);
        if (div) div.innerHTML = '<p class="text-sm text-stone-400 italic">Preview will appear here.</p>';
        return;
      }
      previewVisualObj = ABCJS.renderAbc(previewDivId, src, PREVIEW_OPTS);
      rebuildCharMap();
      previewRebuildTimer = setTimeout(function () {
        rebuildCharMap();
        previewRebuildTimer = null;
      }, 150);
    }

    function syncCursor() {
      if (!previewCharMap.length) rebuildCharMap();
      if (!previewCharMap.length) return;
      var pos = textarea.selectionStart;
      clearHighlight();
      var best = null;
      for (var i = 0; i < previewCharMap.length; i++) {
        var e = previewCharMap[i];
        if (e.start <= pos && (best === null || e.start > best.start)) best = e;
      }
      if (best && best.el) {
        best.el.classList.add("abcjs-cursor-active");
        previewCursorEl = best.el;
      }
    }

    textarea.addEventListener("input", updatePreview);
    textarea.addEventListener("keyup", syncCursor);
    textarea.addEventListener("click", syncCursor);

    if (textarea.value.trim()) updatePreview();

    return { update: updatePreview };
  }

  // Initialise the set detail page: score render, metro, play, drone, and
  // a global bars-to-show cycling control that limits all tunes uniformly.
  // The three set ABC variants are pre-built server-side in compact format
  // (single X:1 block with T: continuations) so ABCJS renders all tunes.
  function initSetTools() {
    var members = window.__cairnSetMembers || [];

    // Seed barsMode from the most restrictive default across members with ABC.
    var barsOrder = { "2": 0, "8": 1, "full": 2 };
    var barsMode = members.reduce(function (best, m) {
      if (!m.has_abc) return best;
      return barsOrder[m.default_bars] < barsOrder[best] ? m.default_bars : best;
    }, "full");

    function getSetAbc() {
      if (barsMode === "2") return window.__cairnSetAbc2 || window.__cairnSetAbcFull || "";
      if (barsMode === "8") return window.__cairnSetAbc8 || window.__cairnSetAbcFull || "";
      return window.__cairnSetAbcFull || "";
    }

    function renderCombined() {
      render(getSetAbc());
      var editor = document.getElementById("abc-editor");
      if (editor) editor.value = currentAbcString;
    }

    renderCombined();
    initDrone();

    // A set mixes tune types with no single subdivision, so metroPattern/
    // metroSubdivision are left at their module defaults (reel / 1) rather
    // than resolved per-member — updateTempoGlyph() just confirms the label
    // matches that default rather than leaving it unset.
    updateTempoGlyph();

    var playBtn     = document.getElementById("abc-play");
    var tempoSlider = document.getElementById("abc-tempo");
    var tempoLabel  = document.getElementById("abc-tempo-label");

    naturalBpm = extractBpm(currentAbcString);
    var seedBpm = clampTempo(window.__cairnLastTempo || naturalBpm || 100, tempoSlider);
    if (tempoSlider) tempoSlider.value = seedBpm;
    if (tempoLabel)  tempoLabel.value = seedBpm;

    if (tempoSlider && tempoLabel) {
      tempoSlider.addEventListener("input", function () {
        tempoLabel.value = this.value;
        setLiveMetroTempo(parseInt(this.value, 10));
        if (activeSynth) { activeSynth.stop(); teardownAudio(); if (playBtn) playBtn.textContent = "▶ Play"; }
      });
      wireTempoLabelEditing(tempoSlider, tempoLabel);
    }

    if (playBtn) {
      if (!ABCJS.synth.supportsAudio()) {
        playBtn.disabled = true;
        playBtn.title = "Audio is not supported in this browser";
      } else {
        playBtn.addEventListener("click", handlePlayStop);
      }
    }

    var metroBtn = document.getElementById("metro-play");
    if (metroBtn) {
      metroBtn.addEventListener("click", function () {
        var bpm = tempoSlider ? parseInt(tempoSlider.value, 10) : 100;
        if (metroTimer) {
          var elapsed = sharedAudioCtx ? sharedAudioCtx.currentTime - metroStartTime : 0;
          var minDuration = (4 * 4 / bpm) * 60;
          var shouldRecord = elapsed >= minDuration && window.__cairnSetId && window.__cairnBoxId;
          stopMetronome();
          metroBtn.textContent = "♩ Metro";
          if (shouldRecord) {
            var params = new URLSearchParams();
            params.append("tempo", bpm);
            params.append("box_id", window.__cairnBoxId);
            fetch("/sets/" + window.__cairnSetId + "/tempo", { method: "POST", body: params })
              .catch(function () {});
          }
        } else {
          startMetronome(bpm);
          metroBtn.textContent = "■ Metro";
        }
      });
    }

    // ── Global bars-to-show cycling control ───────────────────────────────────
    function barLabel(bars) {
      return bars === "2" ? "2 bars" : bars === "8" ? "8 bars" : "Full";
    }

    var barsBtn = document.getElementById("set-bars-toggle");
    if (barsBtn) {
      barsBtn.textContent = "Bars: " + barLabel(barsMode);
      barsBtn.addEventListener("click", function () {
        barsMode = barsMode === "2" ? "8" : barsMode === "8" ? "full" : "2";
        barsBtn.textContent = "Bars: " + barLabel(barsMode);
        renderCombined();
      });
    }

    var editor = document.getElementById("abc-editor");
    if (editor) {
      editor.addEventListener("input", function () {
        if (activeSynth) {
          activeSynth.stop();
          teardownAudio();
          if (playBtn) playBtn.textContent = "▶ Play";
        }
        render(editor.value);
      });
      editor.addEventListener("keyup", syncCursorToScore);
      editor.addEventListener("click", syncCursorToScore);
    }
  }

  // Initialise play, metronome, and drone on the warmup detail page.
  function initWarmupTools(abcString) {
    currentAbcString = abcString || "";
    updateDroneDisplay();
    initDrone();
    initMetronome();

    var playBtn = document.getElementById("abc-play");
    var tempoSlider = document.getElementById("abc-tempo");
    var tempoLabel = document.getElementById("abc-tempo-label");

    naturalBpm = extractBpm(currentAbcString);
    // Priority: user's last tempo → author default → ABC Q: field → 100
    var seedBpm = clampTempo(window.__cairnLastTempo || window.__cairnDefaultTempo || naturalBpm || 100, tempoSlider);
    if (tempoSlider) tempoSlider.value = seedBpm;
    if (tempoLabel) tempoLabel.value = seedBpm;

    if (tempoSlider && tempoLabel) {
      tempoSlider.addEventListener("input", function () {
        tempoLabel.value = this.value;
        setLiveMetroTempo(parseInt(this.value, 10));
        if (activeSynth) {
          activeSynth.stop();
          teardownAudio();
          if (playBtn) playBtn.textContent = "▶ Play";
        }
      });
      wireTempoLabelEditing(tempoSlider, tempoLabel);
    }

    if (playBtn) {
      if (!ABCJS.synth.supportsAudio()) {
        playBtn.disabled = true;
        playBtn.title = "Audio is not supported in this browser";
      } else {
        playBtn.addEventListener("click", handlePlayStop);
      }
    }

    var metroBtn = document.getElementById("metro-play");
    if (metroBtn && window.__cairnWarmupId) {
      metroBtn.addEventListener("click", function () {
        if (!metroTimer) {
          var bpm = tempoSlider ? parseInt(tempoSlider.value, 10) : 100;
          var elapsed = sharedAudioCtx ? sharedAudioCtx.currentTime - metroStartTime : 0;
          var minDuration = (4 * 4 / bpm) * 60;
          if (elapsed < minDuration) return;
          var params = new URLSearchParams();
          params.append("tempo", bpm);
          fetch("/warmups/" + window.__cairnWarmupId + "/tempo", { method: "POST", body: params })
            .catch(function () {});
        }
      });
    }
  }

  // ── chromatic tuner ────────────────────────────────────────────────────────

  var tunerMicStream = null;
  var tunerAudioCtx = null;
  var tunerAnalyser = null;
  var tunerAnimFrame = null;
  var tunerActive = false;
  var tunerSmoothedFreq = null;

  var TUNER_NOTES = ['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];

  // McLeod Pitch Method (MPM): Normalized Square Difference Function (NSDF)
  // plus threshold-based peak picking. Replaces a fixed-threshold
  // autocorrelation that mistook a harmonic's taller correlation peak for
  // the fundamental on flute recordings (messy overtones -> octave errors).
  // MPM's fix is to accept the *first* (shortest-lag) NSDF peak that comes
  // within TUNER_MPM_THRESHOLD of the tallest one, rather than the tallest
  // peak outright — see https://docs.rs/pitch-detection (McLeod detector)
  // for the reference algorithm this was ported from.
  var TUNER_MPM_THRESHOLD = 0.8;
  var TUNER_MPM_CLARITY_MIN = 0.3;

  function tunerNsdf(buffer, maxLag) {
    var size = buffer.length;
    var out = new Float32Array(maxLag);
    for (var lag = 0; lag < maxLag; lag++) {
      var acf = 0, m = 0;
      for (var i = 0; i < size - lag; i++) {
        acf += buffer[i] * buffer[i + lag];
        m += buffer[i] * buffer[i] + buffer[i + lag] * buffer[i + lag];
      }
      out[lag] = m > 0 ? (2 * acf) / m : 0;
    }
    return out;
  }

  // Local maxima of the NSDF, one per positive-going lobe (the "key maxima"
  // MPM picks among) — skips the trivial lobe around lag 0.
  function tunerNsdfKeyMaxima(nsdf) {
    var size = nsdf.length;
    var maxPositions = [];
    var pos = 0;
    while (pos < size - 1 && nsdf[pos] > 0) pos++;
    while (pos < size - 1) {
      while (pos < size - 1 && nsdf[pos] <= 0) pos++;
      var curMaxPos = 0;
      while (pos < size - 1 && nsdf[pos] > 0) {
        if (nsdf[pos] > nsdf[pos - 1] && nsdf[pos] >= nsdf[pos + 1]) {
          if (curMaxPos === 0 || nsdf[pos] > nsdf[curMaxPos]) curMaxPos = pos;
        }
        pos++;
      }
      if (curMaxPos !== 0) maxPositions.push(curMaxPos);
    }
    return maxPositions;
  }

  function tunerParabolicShift(vals, pos) {
    if (pos <= 0 || pos >= vals.length - 1) return 0;
    var y0 = vals[pos - 1], y1 = vals[pos], y2 = vals[pos + 1];
    var denom = 2 * y1 - y0 - y2;
    return denom !== 0 ? (y2 - y0) / (2 * denom) : 0;
  }

  function tunerDetectPitch(buffer, sampleRate) {
    var SIZE = buffer.length;
    var rms = 0;
    for (var i = 0; i < SIZE; i++) rms += buffer[i] * buffer[i];
    rms = Math.sqrt(rms / SIZE);
    if (rms < 0.01) return null;

    var maxLag = Math.floor(SIZE / 2);
    var nsdf = tunerNsdf(buffer, maxLag);
    var maxPositions = tunerNsdfKeyMaxima(nsdf);
    if (maxPositions.length === 0) return null;

    var highest = -Infinity;
    for (var i = 0; i < maxPositions.length; i++) highest = Math.max(highest, nsdf[maxPositions[i]]);
    var cutoff = TUNER_MPM_THRESHOLD * highest;
    var best = -1;
    for (var i = 0; i < maxPositions.length; i++) {
      if (nsdf[maxPositions[i]] >= cutoff) { best = maxPositions[i]; break; }
    }
    if (best === -1 || nsdf[best] < TUNER_MPM_CLARITY_MIN) return null;

    var shift = tunerParabolicShift(nsdf, best);
    var freq = sampleRate / (best + shift);
    return (freq >= 60 && freq <= 2100) ? freq : null;
  }

  function tunerFreqToNote(freq, a4) {
    var semitones = 12 * Math.log2(freq / a4) + 69;
    var midi = Math.round(semitones);
    var cents = Math.round((semitones - midi) * 100);
    return { name: TUNER_NOTES[((midi % 12) + 12) % 12], cents: cents };
  }

  function tunerUpdateDisplay(result) {
    var noteEl = document.getElementById('tuner-note');
    var accEl  = document.getElementById('tuner-accidental');
    var centsEl = document.getElementById('tuner-cents');
    var needleEl = document.getElementById('tuner-needle');

    if (result) {
      var sharp = result.name.indexOf('♯') !== -1;
      if (noteEl) noteEl.textContent = sharp ? result.name[0] : result.name;
      if (accEl)  accEl.textContent  = sharp ? '♯' : '';
      var c = result.cents;
      if (centsEl) centsEl.textContent = (c >= 0 ? '+' : '') + c + '¢';
      if (needleEl) {
        var pct = Math.max(0, Math.min(100, c + 50));
        needleEl.style.left = 'calc(' + pct + '% - 2px)';
        needleEl.style.backgroundColor =
          Math.abs(c) <= 10 ? '#16a34a' : Math.abs(c) <= 25 ? '#d97706' : '#dc2626';
      }
    } else {
      if (noteEl) noteEl.textContent = '—';
      if (accEl)  accEl.textContent  = '';
      if (centsEl) centsEl.textContent = '—';
      if (needleEl) {
        needleEl.style.left = 'calc(50% - 2px)';
        needleEl.style.backgroundColor = '#a8a29e';
      }
    }
  }

  function tunerTick() {
    if (!tunerActive || !tunerAnalyser) return;
    var buf = new Float32Array(tunerAnalyser.fftSize);
    tunerAnalyser.getFloatTimeDomainData(buf);
    var a4 = parseFloat((document.getElementById('tuner-a4') || {}).value) || 440;
    var freq = tunerDetectPitch(buf, tunerAudioCtx.sampleRate);
    if (freq !== null) {
      // Smooth the raw frequency rather than cents — this stabilises the note
      // name too, since note + cents are both derived from the smoothed value.
      tunerSmoothedFreq = tunerSmoothedFreq === null
        ? freq
        : tunerSmoothedFreq * 0.8 + freq * 0.2;
      tunerUpdateDisplay(tunerFreqToNote(tunerSmoothedFreq, a4));
    } else {
      tunerSmoothedFreq = null;
      tunerUpdateDisplay(null);
    }
    tunerAnimFrame = requestAnimationFrame(tunerTick);
  }

  function startTuner() {
    if (tunerActive) return;
    var statusEl = document.getElementById('tuner-status');
    var errorEl  = document.getElementById('tuner-error');
    var btn      = document.getElementById('tuner-toggle');
    if (statusEl) statusEl.textContent = 'Requesting mic…';
    if (errorEl)  errorEl.classList.add('hidden');

    navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      .then(function (stream) {
        tunerMicStream = stream;
        tunerAudioCtx  = new AudioContext();
        tunerAnalyser  = tunerAudioCtx.createAnalyser();
        tunerAnalyser.fftSize = 2048;
        tunerAudioCtx.createMediaStreamSource(stream).connect(tunerAnalyser);
        tunerActive = true;
        tunerSmoothedFreq = null;
        if (statusEl) statusEl.textContent = '';
        if (btn) btn.textContent = 'Stop listening';
        tunerTick();
      })
      .catch(function () {
        if (statusEl) statusEl.textContent = '';
        if (errorEl) {
          errorEl.textContent = 'Microphone access denied. Allow mic access in browser settings to use the tuner.';
          errorEl.classList.remove('hidden');
        }
      });
  }

  function stopTuner() {
    tunerActive = false;
    if (tunerAnimFrame) { cancelAnimationFrame(tunerAnimFrame); tunerAnimFrame = null; }
    if (tunerMicStream) { tunerMicStream.getTracks().forEach(function (t) { t.stop(); }); tunerMicStream = null; }
    if (tunerAudioCtx)  { tunerAudioCtx.close().catch(function () {}); tunerAudioCtx = null; }
    tunerAnalyser = null;
    tunerSmoothedFreq = null;
    var btn = document.getElementById('tuner-toggle');
    if (btn) btn.textContent = 'Start listening';
    var statusEl = document.getElementById('tuner-status');
    if (statusEl) statusEl.textContent = 'Tap to start';
    tunerUpdateDisplay(null);
  }

  function tunerToggle() {
    if (tunerActive) stopTuner(); else startTuner();
  }

  // ── practice session (one-at-a-time view) ─────────────────────────────────

  // Wire up persistent listeners for the session tool panel. Called once at
  // DOMContentLoaded on the session page. Listeners read module-level state
  // (currentAbcString, window.__cairnTuneId, etc.) at click time so they
  // stay current as initSessionTools() updates those values between items.
  function initSessionPage() {
    var playBtn     = document.getElementById("abc-play");
    var tempoSlider = document.getElementById("abc-tempo");
    var tempoLabel  = document.getElementById("abc-tempo-label");
    var metroBtn    = document.getElementById("metro-play");

    if (playBtn) {
      if (ABCJS.synth.supportsAudio()) {
        playBtn.addEventListener("click", handlePlayStop);
      } else {
        playBtn.disabled = true;
        playBtn.title = "Audio not supported in this browser";
      }
    }

    if (tempoSlider && tempoLabel) {
      tempoSlider.addEventListener("input", function () {
        tempoLabel.value = this.value;
        setLiveMetroTempo(parseInt(this.value, 10));
        if (activeSynth) { activeSynth.stop(); teardownAudio(); if (playBtn) playBtn.textContent = "▶ Play"; }
      });
      wireTempoLabelEditing(tempoSlider, tempoLabel);
    }

    if (metroBtn) {
      metroBtn.addEventListener("click", function () {
        var slider = document.getElementById("abc-tempo");
        var bpm = slider ? parseInt(slider.value, 10) : 100;
        if (metroTimer) {
          var elapsed = sharedAudioCtx ? sharedAudioCtx.currentTime - metroStartTime : 0;
          var minDuration = (currentBeatsPerBar() * 4 / bpm) * 60;
          var shouldRecord = elapsed >= minDuration && window.__cairnTuneId;
          stopMetronome();
          metroBtn.textContent = "♩ Metro";
          if (shouldRecord) {
            var params = new URLSearchParams();
            params.append("tempo", bpm);
            if (window.__cairnBoxId) params.append("box_id", window.__cairnBoxId);
            fetch("/tunes/" + window.__cairnTuneId + "/tempo", { method: "POST", body: params })
              .then(function (r) { return r.ok ? r.text() : null; })
              .then(function (html) {
                if (!html) return;
                var el = document.getElementById("tempo-history");
                if (el) el.outerHTML = html;
              })
              .catch(function () {});
          }
        } else {
          startMetronome(bpm);
          metroBtn.textContent = "■ Metro";
        }
      });
    }

    initDrone();
  }

  // Update module-level state for the next session item and re-render the score.
  // Stops any active audio first. Called by Alpine when navigating between items.
  function initSessionTools(opts) {
    if (activeSynth) { activeSynth.stop(); teardownAudio(); }
    stopMetronome();
    stopDrone();

    var playBtn  = document.getElementById("abc-play");
    var metroBtn = document.getElementById("metro-play");
    var droneBtn = document.getElementById("drone-play");
    if (playBtn)  playBtn.textContent  = "▶ Play";
    if (metroBtn) metroBtn.textContent = "♩ Metro";
    if (droneBtn) droneBtn.textContent = "♪ Drone";

    window.__cairnTuneId      = opts.tuneId;
    window.__cairnTuneType    = opts.tuneType;
    window.__cairnBeatsPerBar = opts.beatsPerBar;
    window.__cairnLastTempo   = opts.lastTempo || null;
    window.__cairnBoxId       = opts.boxId || null;

    metroPattern = METRO_PATTERNS[opts.tuneType] || METRO_PATTERNS.reel;
    metroSubdivision = METRO_SUBDIVISION[opts.tuneType] || 1;
    updateTempoGlyph();

    var slider = document.getElementById("abc-tempo");
    var label  = document.getElementById("abc-tempo-label");
    var bpm = clampTempo(opts.lastTempo || extractBpm(opts.abc) || 100, slider);
    if (slider) slider.value = bpm;
    if (label)  label.value = bpm;

    render(opts.abc);
  }

  function stopSessionAudio() {
    if (activeSynth) { activeSynth.stop(); teardownAudio(); }
    stopMetronome();
    stopDrone();
    var playBtn  = document.getElementById("abc-play");
    var metroBtn = document.getElementById("metro-play");
    var droneBtn = document.getElementById("drone-play");
    if (playBtn)  playBtn.textContent  = "▶ Play";
    if (metroBtn) metroBtn.textContent = "♩ Metro";
    if (droneBtn) droneBtn.textContent = "♪ Drone";
  }

  function rerenderSessionAbc(abc) {
    render(abc);
  }

  function cairnApp() {
    return {
      tunerOpen: false,
      openTuner:    function () { this.tunerOpen = true; },
      closeTuner:   function () { this.tunerOpen = false; stopTuner(); },
      toggleTuner:  function () { if (this.tunerOpen) this.closeTuner(); else this.openTuner(); },
    };
  }

  // Expose to Alpine and templates
  window.clearCairnModal    = clearCairnModal;
  window.closeTheSessionWizard = closeTheSessionWizard;
  window.selectSetting      = selectSetting;
  window.initSettingPreview = initSettingPreview;
  window.initWarmupPreview  = initWarmupPreview;
  window.initSetTools       = initSetTools;
  window.initWarmupTools    = initWarmupTools;
  window.initSessionPage    = initSessionPage;
  window.initSessionTools   = initSessionTools;
  window.stopSessionAudio   = stopSessionAudio;
  window.rerenderSessionAbc = rerenderSessionAbc;
  window.cairnApp    = cairnApp;
  window.tunerToggle = tunerToggle;
  window.startTuner  = startTuner;
  window.stopTuner   = stopTuner;

  // ── tune list hover preview ──────────────────────────────────────────────
  // Shows a small popover with an ABCJS rendering of a tune's opening bars
  // when hovering its title in the tune index. Delegated at the document
  // level (rather than bound per-element) so it keeps working after HTMX
  // swaps the list for a new filter.

  function initTuneHoverPreview() {
    var popover = null;
    var canvas = null;
    var renderCache = {};
    var activeTrigger = null;
    var hoverTimer = null;
    var pendingTrigger = null;

    function ensurePopover() {
      if (popover) return popover;
      popover = document.createElement("div");
      popover.id = "tune-hover-popover";
      popover.style.cssText =
        "position:fixed; z-index:60; width:300px; max-height:70vh; overflow-y:auto; display:none; pointer-events:none;";
      popover.className = "bg-white border border-stone-200 rounded-lg shadow-lg p-2";
      canvas = document.createElement("div");
      canvas.id = "tune-hover-abc-canvas";
      popover.appendChild(canvas);
      document.body.appendChild(popover);
      return popover;
    }

    function position(trigger) {
      var rect = trigger.getBoundingClientRect();
      var width = popover.offsetWidth;
      var height = popover.offsetHeight;
      var left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
      var top = rect.bottom + 6;
      if (top + height > window.innerHeight - 8) {
        top = Math.max(rect.top - height - 6, 8);
      }
      popover.style.left = left + "px";
      popover.style.top = top + "px";
    }

    function show(trigger) {
      var previewId = trigger.dataset.abcPreviewId;
      // Both bail-outs below can be reached mid-hover, moving from a real
      // trigger straight into one with no preview (e.g. the alias-tooltip
      // area carved out of a row's trigger via data-abc-preview-id="") —
      // hide() clears any popover left over from the trigger just departed.
      if (!previewId) { hide(); return; }
      var tmpl = document.getElementById("tune-abc-preview-" + previewId);
      if (!tmpl) { hide(); return; }
      var abc = tmpl.content.textContent;
      activeTrigger = trigger;
      ensurePopover();
      popover.style.visibility = "hidden";
      popover.style.display = "block";
      if (Object.prototype.hasOwnProperty.call(renderCache, abc)) {
        canvas.innerHTML = renderCache[abc];
      } else {
        ABCJS.renderAbc(canvas.id, abc, PREVIEW_OPTS);
        renderCache[abc] = canvas.innerHTML;
      }
      position(trigger);
      popover.style.visibility = "visible";
    }

    function hide() {
      activeTrigger = null;
      if (popover) popover.style.display = "none";
    }

    // data-abc-preview-delay opts a trigger into a delayed show (#164's
    // column-preview cells, so a quick mouse pass over the tune table
    // doesn't pop up a full-tune render for every row) — defaults to 0
    // (instant, today's behavior) for every other existing trigger.
    document.addEventListener("mouseover", function (e) {
      var trigger = e.target.closest("[data-abc-preview-id]");
      if (!trigger || trigger === activeTrigger || trigger === pendingTrigger) return;
      var delay = parseInt(trigger.dataset.abcPreviewDelay || "0", 10);
      clearTimeout(hoverTimer);
      if (delay > 0) {
        pendingTrigger = trigger;
        hoverTimer = setTimeout(function () {
          pendingTrigger = null;
          show(trigger);
        }, delay);
      } else {
        show(trigger);
      }
    });

    document.addEventListener("mouseout", function (e) {
      var trigger = e.target.closest("[data-abc-preview-id]");
      if (!trigger || (e.relatedTarget && trigger.contains(e.relatedTarget))) return;
      clearTimeout(hoverTimer);
      pendingTrigger = null;
      hide();
    });

    // A swap can remove the currently-hovered trigger without ever firing
    // mouseout on it, leaving a stale popover stuck on screen.
    document.addEventListener("htmx:afterSwap", hide);
  }

  // ── ABC notation inside rendered markdown (issue #68) ───────────────────────
  // render_markdown() passes ```abc fenced blocks through as
  // <pre><code class="language-abc">; replace each with an ABCJS rendering.
  // Scoped to `root` (default document) so it can be re-run on just the
  // swapped-in subtree after an HTMX swap, e.g. the warmup markdown preview pane.

  var markdownAbcBlockCounter = 0;

  function renderMarkdownAbcBlocks(root) {
    (root || document).querySelectorAll("pre code.language-abc").forEach(function (block) {
      var div = document.createElement("div");
      div.id = "markdown-abc-" + markdownAbcBlockCounter++;
      block.parentElement.replaceWith(div);
      try {
        ABCJS.renderAbc(div.id, block.textContent, { responsive: "resize" });
      } catch (e) {
        // Malformed ABC — leave the empty div rather than crashing the page.
      }
    });
  }

  // ── Transpose popup live preview (#158) ─────────────────────────────────────
  // The popup's key/octave <select>s re-render the whole popup over HTMX on
  // change, each time embedding the pending (unsaved) transposed ABC in a
  // <template>; re-render it into the adjacent canvas div on every swap, same
  // technique as the hover preview above. A no-op when the popup isn't open —
  // this listener is global so it doesn't need separate wiring per swap target.
  //
  // Deliberately omits PREVIEW_OPTS' `responsive: "resize"` — that mode's
  // ResizeObserver-based sizing gets confused when it's asked to re-render
  // into a div that HTMX has replaced (via innerHTML swap) since the last
  // render: the second render falls back to full window width instead of
  // the container's, blowing the preview out past the modal and over the
  // Save button. Uses a fixed `staffwidth` instead — that produces a properly
  // viewBox-scaled SVG (so it still shrinks to fit via the CSS max-width rule
  // in _transpose_popup.html) without any DOM measurement, sidestepping the
  // whole class of bug; 360 comfortably fits the modal's ~400px content width.
  var TRANSPOSE_PREVIEW_OPTS = {
    add_classes: true,
    staffwidth: 360,
    wrap: { preferredMeasuresPerLine: 4, minSpacing: 1.5, maxSpacing: 2.5 },
  };

  function renderTransposePreview() {
    var tmpl = document.getElementById("transpose-preview-abc");
    var canvas = document.getElementById("transpose-preview-canvas");
    if (!tmpl || !canvas) return;
    try {
      ABCJS.renderAbc(canvas.id, tmpl.content.textContent, TRANSPOSE_PREVIEW_OPTS);
      // Same fix as _renderColumnPreview() below: ABCJS's SVG has no
      // viewBox, so the CSS max-width:100% rule (_transpose_popup.html)
      // only resizes the SVG's own box, not the drawing inside it — a
      // viewBox gives it a coordinate system to actually scale against.
      var svg = canvas.querySelector("svg");
      if (svg && !svg.hasAttribute("viewBox")) {
        var w = svg.getAttribute("width");
        var h = svg.getAttribute("height");
        if (w && h) svg.setAttribute("viewBox", "0 0 " + w + " " + h);
      }
    } catch (e) {
      // Malformed/unrenderable ABC — leave the canvas empty rather than crash.
    }
  }

  // ── Box/list row preview column (#164) ──────────────────────────────────────
  // Each row's small always-visible ~2-bar preview is rendered lazily via
  // IntersectionObserver — only when scrolled into view — rather than eagerly
  // for every row on page load, since a box/list can hold dozens of tunes and
  // each render is a real ABCJS cost. Fixed staffwidth (not responsive:resize)
  // for the same reason as TRANSPOSE_PREVIEW_OPTS above — these canvases can
  // be replaced wholesale by an HTMX swap (setting/alias/transpose change),
  // not resized in place, so there's nothing for a ResizeObserver to usefully
  // track. 240 renders reliably wider than the column box regardless of tune
  // content, so the CSS max-width:100% scale-down rule (.cairn-col-preview in
  // base.html) always shrinks it to fit rather than sometimes doing nothing —
  // scaling to fit, not overflow:hidden cropping, is what keeps the full 2
  // bars visible instead of being cut off part-way through.
  var COLUMN_PREVIEW_OPTS = { add_classes: true, staffwidth: 240 };
  var _columnPreviewObserver = null;

  function _renderColumnPreview(el) {
    var tmpl = document.getElementById("tune-abc-col-" + el.dataset.abcColumnPreviewId);
    if (!tmpl) return;
    try {
      ABCJS.renderAbc(el.id, tmpl.content.textContent, COLUMN_PREVIEW_OPTS);
      // ABCJS sets an inline height on its target element sized to the
      // *unscaled* rendered SVG (e.g. "height: 99.87px") — that inline style
      // wins over the .cairn-col-preview box's own fixed height class
      // regardless of CSS specificity, silently making every row a different
      // height depending on each tune's content. Clear it so the class's
      // fixed height governs, keeping every row's preview cell a consistent
      // size.
      el.style.removeProperty("height");
      // ABCJS's output SVG has no viewBox — only width/height attributes
      // holding its native, unscaled pixel size. Without a viewBox, CSS
      // max-width/height:auto (.cairn-col-preview svg in base.html) resizes
      // only the SVG's own layout box; the drawing inside keeps its native
      // absolute coordinates and simply gets clipped by the smaller box
      // instead of scaling down — cropping off most of the 2nd bar rather
      // than shrinking both bars to fit. Adding a viewBox derived from the
      // SVG's own width/height gives the browser a coordinate system to
      // scale against, so the CSS rule actually shrinks the whole drawing
      // proportionally instead of just resizing an empty viewport onto it.
      var svg = el.querySelector("svg");
      if (svg && !svg.hasAttribute("viewBox")) {
        var w = svg.getAttribute("width");
        var h = svg.getAttribute("height");
        if (w && h) svg.setAttribute("viewBox", "0 0 " + w + " " + h);
      }
    } catch (e) {
      // Malformed/unrenderable ABC — leave the canvas empty rather than crash.
    }
    el.dataset.abcColumnRendered = "1";
  }

  // Re-run after every HTMX swap so a freshly-added or replaced row (add
  // tune, setting/alias/transpose change — all outerHTML-swap the whole row)
  // gets observed; already-rendered rows are skipped via the rendered flag,
  // so re-scanning the whole document each time is cheap. Deliberately not
  // scoped to htmx:afterSwap's event.detail.target: that only reliably
  // covers content still inside the swap target for an innerHTML-style
  // swap (like renderMarkdownAbcBlocks() above uses it) — for an outerHTML
  // swap, which is what replaces a whole row here, the target element
  // itself is what got replaced, so scoping the re-scan to it silently
  // misses the very row that just changed. An element already on-screen at
  // swap time still renders immediately since IntersectionObserver.observe()
  // fires its callback on next check regardless of prior visibility.
  function observeColumnPreviews() {
    if (!_columnPreviewObserver) return;
    document.querySelectorAll("[data-abc-column-preview-id]:not([data-abc-column-rendered])").forEach(function (el) {
      _columnPreviewObserver.observe(el);
    });
  }

  function initColumnPreviewObserver() {
    if (!("IntersectionObserver" in window)) {
      document.querySelectorAll("[data-abc-column-preview-id]").forEach(_renderColumnPreview);
      return;
    }
    _columnPreviewObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          _renderColumnPreview(entry.target);
          _columnPreviewObserver.unobserve(entry.target);
        });
      },
      { rootMargin: "200px" }
    );
    observeColumnPreviews();
  }

  // ── init ───────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    renderScore();
    initFormPreview();
    initTuneHoverPreview();
    renderMarkdownAbcBlocks();

    document.addEventListener("htmx:afterSwap", function (e) {
      renderMarkdownAbcBlocks(e.detail.target);
    });

    renderTransposePreview();
    document.addEventListener("htmx:afterSwap", renderTransposePreview);

    initColumnPreviewObserver();
    document.addEventListener("htmx:afterSwap", observeColumnPreviews);

    // Tablature tuning <select> needs to know about a tuning just
    // added/deleted via the tunings-section partial (#233) -- re-read the
    // fresh data blob it just swapped in and repopulate the dropdown.
    document.addEventListener("htmx:afterSwap", function (e) {
      if (!e.detail.target || e.detail.target.id !== "tunings-section") return;
      var dataEl = document.getElementById("my-tunings-data");
      if (dataEl) {
        try {
          window.__cairnTunings = JSON.parse(dataEl.textContent);
        } catch (err) {
          window.__cairnTunings = [];
        }
      }
      if (window.__cairnRefreshTuningSelect) window.__cairnRefreshTuningSelect();
    });

    // Recordings' "Setting" <select>s (recordings/_manage.html, #187) are
    // rendered from tune.settings at the time that section last rendered --
    // adding a new setting only swaps #settings-section, so without this a
    // freshly added setting wouldn't show up in the recordings add/edit
    // forms until a full page reload. Registered once here (not inside the
    // swapped recordings partial itself) so repeated recordings-section
    // swaps don't stack up duplicate listeners.
    window.refreshRecordingSettingSelects = function () {
      var settingsSection = document.getElementById("settings-section");
      if (!settingsSection) return;
      var cards = settingsSection.querySelectorAll("[data-setting-id]");
      document.querySelectorAll('#recordings-section select[name="setting_id"]').forEach(function (select) {
        var current = select.value;
        select.innerHTML = "";
        cards.forEach(function (card) {
          var opt = document.createElement("option");
          opt.value = card.dataset.settingId;
          opt.textContent = card.dataset.settingLabel;
          select.appendChild(opt);
        });
        if (current && select.querySelector('option[value="' + current + '"]')) select.value = current;
      });
    };
    document.addEventListener("htmx:afterSwap", function (e) {
      if (e.detail.target && e.detail.target.id === "settings-section") window.refreshRecordingSettingSelects();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { clearCairnModal(); closeTheSessionWizard(); }
    });

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-propagate-url]");
      if (!btn) return;
      var url = btn.dataset.propagateUrl;
      // Collect data from the button and from checkboxes by class, not form
      // traversal — the response that inserts this modal is a row partial
      // plus this modal's own markup concatenated together (two root
      // elements from one HTMX swap), so this button and the checkboxes
      // it needs aren't reliably within a single common form ancestor.
      var params = new URLSearchParams();
      params.append("setting_id", btn.dataset.settingId || "");
      document.querySelectorAll(".cairn-propagate-list:checked").forEach(function (cb) {
        params.append("list_ids", cb.value);
      });
      btn.disabled = true;
      fetch(url, { method: "POST", body: params })
        .then(function (r) {
          if (r.ok) { clearCairnModal(); }
        })
        .catch(function () {})
        .finally(function () { btn.disabled = false; });
    });

    document.addEventListener("htmx:afterSwap", function () {
      if (activeSettingId !== null) {
        // Re-render the main score from the refreshed abc-setting-{id} template
        // (the swap updated those templates with the latest saved ABC).
        selectSetting(activeSettingId);
      }
    });
  });
})();
