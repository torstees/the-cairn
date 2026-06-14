(function () {
  var RENDER_OPTS = {
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

  // ── ABC helpers ────────────────────────────────────────────────────────────

  // Extract the BPM number from a Q: header.
  // Handles Q:1/4=100, Q:3/8=100 (note-spec form) and Q:100 (legacy form).
  function extractBpm(abcString) {
    var m = abcString.match(/^Q:[^=\n]*=(\d+)/m) || abcString.match(/^Q:(\d+)/m);
    return m ? parseInt(m[1], 10) : null;
  }

  // Return a copy of abcString with the Q: BPM replaced by bpm.
  // Preserves the note-length specifier (e.g. Q:3/8= stays, only the number changes).
  // Uses .test() to detect which form is present — avoids a fall-through bug when
  // the replacement value equals the existing value (strings would compare equal).
  function setQBpm(abcString, bpm) {
    if (/^Q:[^=\n]+=\d+/m.test(abcString)) {
      return abcString.replace(/^(Q:[^=\n]+=)\d+/m, "$1" + bpm);
    }
    if (/^Q:\d+/m.test(abcString)) {
      return abcString.replace(/^Q:\d+/m, "Q:" + bpm);
    }
    return abcString.replace(/^K:/m, "Q:1/4=" + bpm + "\nK:");
  }

  // ── detail page ────────────────────────────────────────────────────────────

  function render(abcString) {
    currentAbcString = abcString;
    visualObj = ABCJS.renderAbc("abc-render", abcString, RENDER_OPTS);
  }

  function renderScore() {
    var abcSource = document.getElementById("abc-source");
    if (!abcSource) return;
    var abcString = abcSource.content.textContent.trim();
    if (!abcString) return;

    render(abcString);

    var btn = document.getElementById("abc-play");
    var tempoSlider = document.getElementById("abc-tempo");
    var tempoLabel = document.getElementById("abc-tempo-label");

    // Initialise slider at the natural BPM from the Q: header
    naturalBpm = extractBpm(abcString);
    if (tempoSlider && naturalBpm) {
      tempoSlider.value = naturalBpm;
    }
    if (tempoLabel && naturalBpm) {
      tempoLabel.textContent = naturalBpm + " bpm";
    }
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

    // Render BPM-adjusted ABC to the hidden element so the visible score is untouched.
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

  // ── edit form preview ──────────────────────────────────────────────────────

  function parseUserHeaders(raw) {
    var lines = raw.split("\n");
    var userHeaders = [];
    var musicLines = [];
    var inMusic = false;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (!inMusic && line.length >= 2 && line[1] === ":" && /[A-Za-z]/.test(line[0])) {
        if (!MAPPED_HEADERS.has(line[0].toUpperCase())) {
          userHeaders.push(line);
        }
      } else {
        inMusic = true;
        musicLines.push(line);
      }
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
      ABCJS.renderAbc("form-abc-render", buildFormAbc(), RENDER_OPTS);
    }

    updatePreview();

    var form = document.querySelector("form");
    if (form) {
      form.addEventListener("input", updatePreview);
      form.addEventListener("change", updatePreview);
    }
  }

  // ── init ───────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    renderScore();
    initFormPreview();
  });
})();
