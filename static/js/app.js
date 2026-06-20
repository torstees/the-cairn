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
    if (tempoSlider && naturalBpm) tempoSlider.value = naturalBpm;
    if (tempoLabel && naturalBpm) tempoLabel.textContent = naturalBpm + " bpm";
  }

  function render(abcString) {
    currentAbcString = abcString;
    updateDroneDisplay();
    clearCursorHighlight();
    charMap = [];
    if (rebuildMapTimer) { clearTimeout(rebuildMapTimer); rebuildMapTimer = null; }
    // Strip Q: from the visual render — tempo annotation is misleading since
    // it never updates when the slider moves. Audio uses currentAbcString.
    var displayAbc = abcString.replace(/^Q:[^\n]*\n?/m, "");
    visualObj = ABCJS.renderAbc("abc-render", displayAbc, RENDER_OPTS);
    if (visualObj && visualObj[0]) {
      charMap = buildCharMap(visualObj[0], "abc-render");
      // ABCJS responsive:"resize" fires a ResizeObserver callback after layout,
      // replacing the initial SVG and making the charMap stale. Rebuild after
      // the next paint to capture the final DOM elements.
      rebuildMapTimer = setTimeout(function () {
        charMap = buildCharMap(visualObj[0], "abc-render");
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
    if (tempoSlider && naturalBpm) tempoSlider.value = naturalBpm;
    if (tempoLabel && naturalBpm) tempoLabel.textContent = naturalBpm + " bpm";

    if (tempoSlider && tempoLabel) {
      tempoSlider.addEventListener("input", function () {
        tempoLabel.textContent = this.value + " bpm";
        if (activeSynth) {
          activeSynth.stop();
          teardownAudio();
          if (btn) btn.textContent = "▶ Play";
        }
      });
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

  var metroPattern = METRO_PATTERNS.reel;  // resolved in initMetronome
  var metroTimer = null;
  var metroNextBeat = 0;
  var metroStartTime = 0;
  var metroBeatCount = 0;
  var metroNodes = [];          // scheduled oscillators — cancelled on stop
  var metroGains = [];          // corresponding gain nodes — disconnected on stop
  var METRO_LOOKAHEAD = 25;    // ms between scheduler ticks
  var METRO_SCHEDULE = 0.25;   // seconds to schedule ahead — must exceed worst-case GC pause

  function metroSchedule(bpm) {
    var ctx = sharedAudioCtx;
    var interval = 60.0 / bpm;
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
    metroTimer = setTimeout(function () { metroSchedule(bpm); }, METRO_LOOKAHEAD);
  }

  function startMetronome(bpm) {
    stopMetronome();
    var ctx = getAudioCtx();
    metroNextBeat = ctx.currentTime;
    metroStartTime = ctx.currentTime;
    metroBeatCount = 0;
    metroSchedule(bpm);
  }

  function stopMetronome() {
    if (metroTimer) { clearTimeout(metroTimer); metroTimer = null; }
    metroNodes.forEach(function(osc) { try { osc.stop(); } catch(e) {} });
    metroGains.forEach(function(g) { try { g.disconnect(); } catch(e) {} });
    metroNodes = [];
    metroGains = [];
  }

  function initMetronome() {
    var btn = document.getElementById("metro-play");
    if (!btn) return;

    metroPattern = METRO_PATTERNS[window.__cairnTuneType] || METRO_PATTERNS.reel;

    if (window.__cairnLastTempo) {
      var slider = document.getElementById("abc-tempo");
      var label  = document.getElementById("abc-tempo-label");
      if (slider) slider.value = window.__cairnLastTempo;
      if (label)  label.textContent = window.__cairnLastTempo + " bpm";
    }

    btn.addEventListener("click", function () {
      var slider = document.getElementById("abc-tempo");
      var bpm = slider ? parseInt(slider.value, 10) : 100;

      if (metroTimer) {
        var elapsed = sharedAudioCtx ? sharedAudioCtx.currentTime - metroStartTime : 0;
        var minDuration = (4 * 60) / bpm;
        var shouldRecord = elapsed >= minDuration;
        stopMetronome();
        btn.textContent = "♩ Metro";
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

  // Expose to Alpine and templates
  window.clearCairnModal = clearCairnModal;
  window.selectSetting = selectSetting;
  window.initSettingPreview = initSettingPreview;

  // ── init ───────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    renderScore();
    initFormPreview();

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { clearCairnModal(); }
    });

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-propagate-url]");
      if (!btn) return;
      var url = btn.dataset.propagateUrl;
      // Collect data from the button and from checkboxes by class.
      // We cannot rely on form traversal because HTMX parses the combined
      // <tr>+<div> response in a table context, which can displace the modal's
      // DOM subtree via HTML foster-parenting, breaking ancestor/descendant queries.
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
