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
    if (!tmpl) return;
    var abc = tmpl.content.textContent.trim();
    if (!abc) return;

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

  // Expose to Alpine and templates
  window.selectSetting = selectSetting;
  window.initSettingPreview = initSettingPreview;

  // ── init ───────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    renderScore();
    initFormPreview();

    document.addEventListener("htmx:afterSwap", function () {
      if (activeSettingId !== null) {
        // Re-render the main score from the refreshed abc-setting-{id} template
        // (the swap updated those templates with the latest saved ABC).
        selectSetting(activeSettingId);
      }
    });
  });
})();
