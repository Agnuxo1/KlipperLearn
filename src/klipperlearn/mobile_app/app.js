(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const elements = {
    secureBadge: $("secureBadge"),
    sessionId: $("sessionId"),
    sessionName: $("sessionName"),
    placement: $("placement"),
    testNote: $("testNote"),
    useCamera: $("useCamera"),
    useAudio: $("useAudio"),
    prepareButton: $("prepareButton"),
    sourceStatus: $("sourceStatus"),
    startButton: $("startButton"),
    stopButton: $("stopButton"),
    photoButton: $("photoButton"),
    recordingState: $("recordingState"),
    durationMetric: $("durationMetric"),
    motionMetric: $("motionMetric"),
    audioMetric: $("audioMetric"),
    accelMetric: $("accelMetric"),
    motionPlot: $("motionPlot"),
    cameraPreview: $("cameraPreview"),
    photoList: $("photoList"),
    analysis: $("analysis"),
    exportButton: $("exportButton"),
    lanToken: $("lanToken"),
    lanEndpoint: $("lanEndpoint"),
    lanStatus: $("lanStatus"),
    uploadButton: $("uploadButton"),
  };

  const state = {
    sessionId: makeSessionId(),
    collecting: false,
    captureStartPerformance: null,
    captureStartedUtc: null,
    captureEndedUtc: null,
    motion: [],
    orientation: [],
    audioFeatures: [],
    cameraFrames: [],
    permissions: { motion: "not_requested", orientation: "not_requested", camera: "not_requested", microphone: "not_requested" },
    listenersAttached: false,
    videoStream: null,
    audioStream: null,
    audioContext: null,
    analyser: null,
    audioTimer: null,
    uiTimer: null,
    lastMotionMagnitude: null,
    latestAnalysis: null,
    lanPayload: null,
    lanReceipt: null,
  };

  try {
    const rememberedToken = localStorage.getItem('klipperlearn-token') || sessionStorage.getItem('klipperlearn-token') || '';
    if (rememberedToken && elements.lanToken) elements.lanToken.value = rememberedToken;
  } catch (_) {}

  const audioBands = [
    ["20_80_hz", 20, 80],
    ["80_250_hz", 80, 250],
    ["250_800_hz", 250, 800],
    ["800_2000_hz", 800, 2000],
    ["2000_8000_hz", 2000, 8000],
  ];

  function makeSessionId() {
    const now = new Date().toISOString().replace(/[-:.]/g, "").replace("Z", "Z");
    const random = Math.random().toString(36).slice(2, 7);
    return "mobile-" + now + "-" + random;
  }

  function nowUtc() {
    return new Date().toISOString();
  }

  function elapsedMs() {
    return state.captureStartPerformance === null ? null : Math.max(0, Math.round(performance.now() - state.captureStartPerformance));
  }

  function number(value, digits) {
    if (!Number.isFinite(value)) return "—";
    return Number(value).toLocaleString("en-GB", { maximumFractionDigits: digits === undefined ? 1 : digits });
  }

  function setSecureBadge() {
    if (window.isSecureContext) {
      elements.secureBadge.textContent = "Contexto seguro";
      elements.secureBadge.className = "badge ok";
    } else {
      elements.secureBadge.textContent = "HTTPS is required";
      elements.secureBadge.className = "badge warn";
    }
  }

  function setSessionLabel() {
    elements.sessionId.textContent = state.sessionId;
  }

  function statusValue(value) {
    const translations = {
      granted: "autorizado",
      denied: "denegado",
      prompt: "pending",
      not_requested: "not requested",
      not_supported: "no compatible",
      ready: "ready",
      released: "liberado",
      unavailable: "unavailable",
      error: "error",
    };
    return translations[value] || value;
  }

  function renderSourceStatus() {
    const statuses = [
      ["Accelerometer", state.permissions.motion],
      ["Orientation", state.permissions.orientation],
      ["Camera", state.permissions.camera],
      ["Microphone", state.permissions.microphone],
    ];
    elements.sourceStatus.replaceChildren();
    statuses.forEach(([label, value]) => {
      const wrapper = document.createElement("div");
      const key = document.createElement("dt");
      const val = document.createElement("dd");
      key.textContent = label;
      val.textContent = statusValue(value);
      wrapper.append(key, val);
      elements.sourceStatus.append(wrapper);
    });
  }

  async function askSensorPermission(eventType, stateKey) {
    const api = window[eventType];
    if (!api) {
      state.permissions[stateKey] = "not_supported";
      return;
    }
    if (typeof api.requestPermission === "function") {
      try {
        state.permissions[stateKey] = await api.requestPermission();
      } catch (error) {
        state.permissions[stateKey] = "denied";
      }
    } else {
      state.permissions[stateKey] = "granted";
    }
  }

  function attachSensorListeners() {
    if (state.listenersAttached) return;
    window.addEventListener("devicemotion", onMotion, { passive: true });
    window.addEventListener("deviceorientation", onOrientation, { passive: true });
    state.listenersAttached = true;
  }

  async function prepareSensors() {
    await askSensorPermission("DeviceMotionEvent", "motion");
    await askSensorPermission("DeviceOrientationEvent", "orientation");
    attachSensorListeners();
  }

  function stopTracks(stream) {
    if (stream) stream.getTracks().forEach((track) => track.stop());
  }

  async function releaseMedia() {
    if (state.audioTimer) {
      window.clearInterval(state.audioTimer);
      state.audioTimer = null;
    }
    if (state.audioContext) {
      try {
        await state.audioContext.close();
      } catch (error) {
        // Closing an already closed AudioContext is harmless.
      }
    }
    state.audioContext = null;
    state.analyser = null;
    stopTracks(state.videoStream);
    stopTracks(state.audioStream);
    state.videoStream = null;
    state.audioStream = null;
    elements.cameraPreview.srcObject = null;
    if (state.permissions.camera === "ready") state.permissions.camera = "released";
    if (state.permissions.microphone === "ready") state.permissions.microphone = "released";
  }

  async function prepareCamera() {
    if (!elements.useCamera.checked) {
      state.permissions.camera = "not_requested";
      return;
    }
    try {
      state.videoStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      elements.cameraPreview.srcObject = state.videoStream;
      state.permissions.camera = "ready";
    } catch (error) {
      state.permissions.camera = error && error.name === "NotAllowedError" ? "denied" : "unavailable";
    }
  }

  function setupAudioAnalyser() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass || !state.audioStream) {
      state.permissions.microphone = "not_supported";
      return;
    }
    state.audioContext = new AudioContextClass();
    state.analyser = state.audioContext.createAnalyser();
    state.analyser.fftSize = 2048;
    state.analyser.smoothingTimeConstant = 0;
    const source = state.audioContext.createMediaStreamSource(state.audioStream);
    source.connect(state.analyser);
    state.audioContext.resume();
    state.audioTimer = window.setInterval(captureAudioFeature, 250);
  }

  async function prepareAudio() {
    if (!elements.useAudio.checked) {
      state.permissions.microphone = "not_requested";
      return;
    }
    try {
      state.audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
          channelCount: 1,
        },
        video: false,
      });
      setupAudioAnalyser();
      state.permissions.microphone = state.analyser ? "ready" : state.permissions.microphone;
    } catch (error) {
      state.permissions.microphone = error && error.name === "NotAllowedError" ? "denied" : "unavailable";
    }
  }

  async function prepareSources() {
    if (!window.isSecureContext) {
      elements.analysis.textContent = "The browser grants camera, microphone and motion access only over HTTPS or localhost.";
      return;
    }
    elements.prepareButton.disabled = true;
    elements.prepareButton.textContent = "Solicitando…";
    await releaseMedia();
    await prepareSensors();
    await prepareCamera();
    await prepareAudio();
    renderSourceStatus();
    elements.prepareButton.disabled = false;
    elements.prepareButton.textContent = "Actualizar fuentes";
    const usable = state.permissions.motion === "granted" || state.permissions.microphone === "ready";
    elements.startButton.disabled = !usable;
    elements.photoButton.disabled = !state.videoStream;
    if (!usable) {
      elements.analysis.textContent = "Enable at least the accelerometer or microphone to collect vibration evidence.";
    }
  }

  function vector(source, axes) {
    if (!source) return null;
    const result = {};
    (axes || ["x", "y", "z"]).forEach((axis) => {
      if (Number.isFinite(source[axis])) result[axis] = Number(source[axis]);
    });
    return Object.keys(result).length ? result : null;
  }

  function magnitude(source) {
    if (!source || !Number.isFinite(source.x) || !Number.isFinite(source.y) || !Number.isFinite(source.z)) return null;
    return Math.hypot(source.x, source.y, source.z);
  }

  function onMotion(event) {
    if (!state.collecting) return;
    const linear = vector(event.acceleration);
    const withGravity = vector(event.accelerationIncludingGravity);
    const rotation = vector(event.rotationRate, ["alpha", "beta", "gamma"]);
    const sample = {
      t_ms: elapsedMs(),
      linear_acceleration_mps2: linear,
      acceleration_including_gravity_mps2: withGravity,
      rotation_rate_deg_s: rotation,
      interval_ms: Number.isFinite(event.interval) ? Number(event.interval) : null,
    };
    state.motion.push(sample);
    state.lastMotionMagnitude = magnitude(linear) ?? magnitude(withGravity);
  }

  function onOrientation(event) {
    if (!state.collecting) return;
    state.orientation.push({
      t_ms: elapsedMs(),
      alpha_deg: Number.isFinite(event.alpha) ? Number(event.alpha) : null,
      beta_deg: Number.isFinite(event.beta) ? Number(event.beta) : null,
      gamma_deg: Number.isFinite(event.gamma) ? Number(event.gamma) : null,
      absolute: Boolean(event.absolute),
    });
  }

  function dbAverage(values, startBin, endBin) {
    let total = 0;
    let count = 0;
    for (let index = startBin; index <= endBin && index < values.length; index += 1) {
      const value = values[index];
      if (Number.isFinite(value)) {
        total += Math.pow(10, value / 10);
        count += 1;
      }
    }
    return count ? 10 * Math.log10(total / count) : null;
  }

  function captureAudioFeature() {
    if (!state.collecting || !state.analyser || !state.audioContext) return;
    const spectrum = new Float32Array(state.analyser.frequencyBinCount);
    const waveform = new Float32Array(state.analyser.fftSize);
    state.analyser.getFloatFrequencyData(spectrum);
    state.analyser.getFloatTimeDomainData(waveform);
    const rate = state.audioContext.sampleRate;
    const binWidth = rate / state.analyser.fftSize;
    let peakIndex = null;
    let peakValue = -Infinity;
    for (let index = 1; index < spectrum.length; index += 1) {
      const frequency = index * binWidth;
      if (frequency < 20 || frequency > Math.min(8000, rate / 2)) continue;
      if (spectrum[index] > peakValue) {
        peakValue = spectrum[index];
        peakIndex = index;
      }
    }
    const rms = Math.sqrt(waveform.reduce((sum, value) => sum + value * value, 0) / waveform.length);
    const bands = {};
    audioBands.forEach(([label, low, high]) => {
      bands[label] = dbAverage(spectrum, Math.ceil(low / binWidth), Math.floor(high / binWidth));
    });
    state.audioFeatures.push({
      t_ms: elapsedMs(),
      sample_rate_hz: rate,
      rms_dbfs: rms > 0 ? Number((20 * Math.log10(rms)).toFixed(2)) : null,
      dominant_frequency_hz: peakIndex === null ? null : Number((peakIndex * binWidth).toFixed(2)),
      dominant_magnitude_db: Number.isFinite(peakValue) ? Number(peakValue.toFixed(2)) : null,
      band_magnitude_db: bands,
    });
  }

  function resetCapture() {
    state.sessionId = makeSessionId();
    state.captureStartPerformance = null;
    state.captureStartedUtc = null;
    state.captureEndedUtc = null;
    state.motion = [];
    state.orientation = [];
    state.audioFeatures = [];
    state.cameraFrames.forEach((frame) => URL.revokeObjectURL(frame.objectUrl));
    state.cameraFrames = [];
    state.latestAnalysis = null;
    state.lastMotionMagnitude = null;
    state.lanPayload = null;
    state.lanReceipt = null;
    elements.photoList.replaceChildren();
    elements.analysis.className = "analysis empty";
    elements.analysis.textContent = "No completed capture is available yet.";
    elements.exportButton.disabled = true;
    elements.uploadButton.disabled = true;
    setLanStatus("Finish a capture and enter the token to enable upload.");
    setSessionLabel();
  }

  function startCapture() {
    if (state.collecting) return;
    if (state.motion.length || state.audioFeatures.length || state.cameraFrames.length) {
      if (!window.confirm("The unexported session will be replaced. Start a new capture?")) return;
      resetCapture();
    }
    state.collecting = true;
    state.captureStartPerformance = performance.now();
    state.captureStartedUtc = nowUtc();
    state.captureEndedUtc = null;
    elements.recordingState.textContent = "Recording evidence";
    elements.recordingState.className = "state recording";
    elements.startButton.disabled = true;
    elements.stopButton.disabled = false;
    elements.prepareButton.disabled = true;
    elements.photoButton.disabled = !state.videoStream;
    state.uiTimer = window.setInterval(updateLiveView, 160);
    updateLiveView();
  }

  function interpolate(points, timestamp) {
    let right = 1;
    while (right < points.length && points[right].t < timestamp) right += 1;
    if (right >= points.length) return points[points.length - 1].value;
    const left = points[right - 1];
    const next = points[right];
    const ratio = next.t === left.t ? 0 : (timestamp - left.t) / (next.t - left.t);
    return left.value + (next.value - left.value) * ratio;
  }

  function analyzeMotion(samples) {
    const linear = samples.map((sample) => ({ t: sample.t_ms, value: magnitude(sample.linear_acceleration_mps2) }))
      .filter((sample) => Number.isFinite(sample.t) && Number.isFinite(sample.value));
    const gravity = samples.map((sample) => ({ t: sample.t_ms, value: magnitude(sample.acceleration_including_gravity_mps2) }))
      .filter((sample) => Number.isFinite(sample.t) && Number.isFinite(sample.value));
    const points = linear.length >= 64 ? linear : gravity;
    const source = linear.length >= 64 ? "linear_acceleration_mps2" : "acceleration_including_gravity_mps2";
    if (points.length < 64) {
      return { available: false, reason: "At least 64 valid acceleration samples are required.", source };
    }
    const end = points[points.length - 1].t;
    const start = Math.max(points[0].t, end - 10000);
    const windowPoints = points.filter((point) => point.t >= start);
    const durationSeconds = (windowPoints[windowPoints.length - 1].t - windowPoints[0].t) / 1000;
    if (durationSeconds <= 0.4) return { available: false, reason: "The motion window is too short.", source };
    const usableCount = Math.min(512, windowPoints.length);
    const n = Math.pow(2, Math.floor(Math.log2(usableCount)));
    if (n < 64) return { available: false, reason: "Not enough uniformly sampled data.", source };
    const sampleRate = n / durationSeconds;
    const sampled = Array.from({ length: n }, (_, index) => {
      const timestamp = windowPoints[0].t + (index * durationSeconds * 1000) / n;
      return interpolate(windowPoints, timestamp);
    });
    const mean = sampled.reduce((sum, value) => sum + value, 0) / sampled.length;
    const windowed = sampled.map((value, index) => (value - mean) * (0.5 - 0.5 * Math.cos((2 * Math.PI * index) / (n - 1))));
    let peak = { frequency_hz: null, power: -Infinity };
    const candidates = [];
    for (let bin = 1; bin < n / 2; bin += 1) {
      const frequency = (bin * sampleRate) / n;
      if (frequency < 1 || frequency > Math.min(80, sampleRate / 2)) continue;
      let real = 0;
      let imaginary = 0;
      for (let index = 0; index < n; index += 1) {
        const phase = (2 * Math.PI * bin * index) / n;
        real += windowed[index] * Math.cos(phase);
        imaginary -= windowed[index] * Math.sin(phase);
      }
      const power = real * real + imaginary * imaginary;
      candidates.push({ frequency_hz: Number(frequency.toFixed(2)), power: Number(power.toFixed(4)) });
      if (power > peak.power) peak = { frequency_hz: Number(frequency.toFixed(2)), power: Number(power.toFixed(4)) };
    }
    return {
      available: Number.isFinite(peak.frequency_hz),
      source,
      method: "magnitude_detrended_hann_windowed_dft",
      window_ms: Math.round(durationSeconds * 1000),
      effective_sample_hz: Number(sampleRate.toFixed(2)),
      dominant_frequency_hz: peak.frequency_hz,
      candidate_peaks: candidates.sort((left, right) => right.power - left.power).slice(0, 3),
    };
  }

  function analyzeAudio(features) {
    const valid = features.filter((item) => Number.isFinite(item.dominant_frequency_hz) && Number.isFinite(item.dominant_magnitude_db));
    if (!valid.length) return { available: false, reason: "No acoustic features were captured." };
    const strongest = valid.reduce((best, item) => item.dominant_magnitude_db > best.dominant_magnitude_db ? item : best);
    const rmsValues = valid.map((item) => item.rms_dbfs).filter(Number.isFinite);
    const meanRms = rmsValues.length ? rmsValues.reduce((sum, item) => sum + item, 0) / rmsValues.length : null;
    return {
      available: true,
      feature_count: valid.length,
      strongest_frequency_hz: strongest.dominant_frequency_hz,
      strongest_magnitude_db: strongest.dominant_magnitude_db,
      mean_rms_dbfs: meanRms === null ? null : Number(meanRms.toFixed(2)),
      method: "local_analysernode_spectrum_no_raw_audio",
    };
  }

  function finishCapture() {
    if (!state.collecting) return;
    captureAudioFeature();
    state.collecting = false;
    state.captureEndedUtc = nowUtc();
    if (state.uiTimer) {
      window.clearInterval(state.uiTimer);
      state.uiTimer = null;
    }
    state.latestAnalysis = { motion: analyzeMotion(state.motion), audio: analyzeAudio(state.audioFeatures) };
    elements.recordingState.textContent = "Finished";
    elements.recordingState.className = "state idle";
    elements.stopButton.disabled = true;
    elements.prepareButton.disabled = false;
    elements.startButton.disabled = false;
    elements.exportButton.disabled = !(state.motion.length || state.audioFeatures.length);
    updateUploadButton();
    updateLiveView();
    renderAnalysis();
    releaseMedia().then(renderSourceStatus);
  }

  function drawPlot() {
    const canvas = elements.motionPlot;
    const context = canvas.getContext("2d");
    const scale = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(canvas.clientWidth * scale));
    const height = Math.max(1, Math.floor(canvas.clientHeight * scale));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    context.clearRect(0, 0, width, height);
    context.strokeStyle = "#25364e";
    context.lineWidth = scale;
    for (let row = 1; row < 4; row += 1) {
      const y = (height * row) / 4;
      context.beginPath();
      context.moveTo(0, y);
      context.lineTo(width, y);
      context.stroke();
    }
    const values = state.motion.slice(-220).map((sample) => magnitude(sample.linear_acceleration_mps2) ?? magnitude(sample.acceleration_including_gravity_mps2)).filter(Number.isFinite);
    if (values.length < 2) return;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = Math.max(max - min, 0.05);
    context.strokeStyle = "#74e0bf";
    context.lineWidth = 2 * scale;
    context.beginPath();
    values.forEach((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / span) * (height - 8 * scale) - 4 * scale;
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();
  }

  function updateLiveView() {
    const duration = state.collecting ? (elapsedMs() || 0) : state.captureStartPerformance === null ? 0 : Date.parse(state.captureEndedUtc) - Date.parse(state.captureStartedUtc);
    elements.durationMetric.textContent = number(duration / 1000, 1) + " s";
    elements.motionMetric.textContent = number(state.motion.length, 0);
    elements.audioMetric.textContent = number(state.audioFeatures.length, 0);
    elements.accelMetric.textContent = state.lastMotionMagnitude === null ? "—" : number(state.lastMotionMagnitude, 2) + " m/s²";
    drawPlot();
  }

  function renderAnalysis() {
    const motion = state.latestAnalysis.motion;
    const audio = state.latestAnalysis.audio;
    elements.analysis.className = "analysis";
    elements.analysis.replaceChildren();
    const grid = document.createElement("div");
    grid.className = "analysis-grid";
    const rows = [
      ["Motion peak", motion.available ? number(motion.dominant_frequency_hz, 2) + " Hz" : motion.reason],
      ["Ventana / muestreo", motion.available ? number(motion.window_ms / 1000, 1) + " s / " + number(motion.effective_sample_hz, 1) + " Hz" : "—"],
      ["Acoustic peak", audio.available ? number(audio.strongest_frequency_hz, 2) + " Hz" : audio.reason],
      ["Mean acoustic level", audio.available ? number(audio.mean_rms_dbfs, 1) + " dBFS" : "—"],
    ];
    rows.forEach(([label, value]) => {
      const box = document.createElement("div");
      const name = document.createElement("span");
      const result = document.createElement("strong");
      name.textContent = label;
      result.textContent = value;
      box.append(name, result);
      grid.append(box);
    });
    elements.analysis.append(grid);
  }

  async function sha256(blob) {
    if (!window.crypto || !window.crypto.subtle) return null;
    const hash = await window.crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
    return Array.from(new Uint8Array(hash)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function takePhoto() {
    const video = elements.cameraPreview;
    if (!state.videoStream || !video.videoWidth) return;
    const maximum = 1280;
    const ratio = Math.min(1, maximum / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * ratio);
    canvas.height = Math.round(video.videoHeight * ratio);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.88));
    if (!blob) return;
    const index = state.cameraFrames.length + 1;
    const filename = "frame-" + String(index).padStart(3, "0") + ".jpg";
    const frame = {
      filename,
      captured_at_utc: nowUtc(),
      t_ms: state.collecting ? elapsedMs() : null,
      mime_type: "image/jpeg",
      byte_count: blob.size,
      sha256: await sha256(blob),
      blob,
      objectUrl: URL.createObjectURL(blob),
    };
    state.cameraFrames.push(frame);
    const listItem = document.createElement("li");
    const link = document.createElement("a");
    link.href = frame.objectUrl;
    link.download = filename;
    link.textContent = "Download " + filename + " (" + Math.round(blob.size / 1024) + " KB)";
    listItem.append(link);
    elements.photoList.append(listItem);
  }

  function buildPayload(networkTransmission) {
    return {
      schema: "klipperlearn.mobile-sensor/v1",
      exported_at_utc: nowUtc(),
      session: {
        id: state.sessionId,
        name: elements.sessionName.value.trim() || null,
        placement: elements.placement.value,
        note: elements.testNote.value.trim() || null,
        started_at_utc: state.captureStartedUtc,
        ended_at_utc: state.captureEndedUtc,
        recording_duration_ms: state.captureStartedUtc && state.captureEndedUtc ? Date.parse(state.captureEndedUtc) - Date.parse(state.captureStartedUtc) : null,
        mode: "passive_phone_sensor_capture",
      },
      privacy: {
        network_transmission: networkTransmission || false,
        raw_audio_saved: false,
        raw_video_saved: false,
        camera_images_saved_only_on_manual_capture: true,
        storage: "browser_memory_until_export",
      },
      device: {
        user_agent: navigator.userAgent,
        platform: navigator.platform || null,
        secure_context: window.isSecureContext,
        screen: { width_px: screen.width, height_px: screen.height, pixel_ratio: window.devicePixelRatio || 1 },
      },
      permissions: state.permissions,
      acquisition: {
        motion_units: "m/s2 (DeviceMotion API, device-reported)",
        orientation_units: "degrees (DeviceOrientation API)",
        audio_feature_method: "AnalyserNode spectrum; no waveform or recording is saved",
        microphone_constraints_requested: elements.useAudio.checked ? { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 } : null,
      },
      samples: {
        motion: state.motion,
        orientation: state.orientation,
        audio_features: state.audioFeatures,
      },
      camera_frames: state.cameraFrames.map(({ objectUrl, blob, ...frame }) => frame),
      analysis: state.latestAnalysis,
      limitations: [
        "Phone placement on a fixed frame measures frame response and ambient coupling, not toolhead acceleration.",
        "Acoustic features are relative to this phone, room, placement, and automatic device processing.",
        "This export is evidence for human review and never configures or controls a printer.",
      ],
    };
  }

  function exportSession() {
    if (!state.latestAnalysis) return;
    const payload = buildPayload(false);
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = state.sessionId + ".json";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  function localApiUrl(path) {
    return new URL("api/" + path, window.location.href);
  }

  function setLanStatus(message, kind) {
    elements.lanStatus.textContent = message;
    elements.lanStatus.className = "network-status" + (kind ? " " + kind : "");
  }

  function updateUploadButton() {
    const validToken = elements.lanToken.value.trim().length >= 16;
    const enabled = Boolean(state.latestAnalysis) && !state.collecting && window.isSecureContext && validToken;
    elements.uploadButton.disabled = !enabled;
    if (!window.isSecureContext) {
      setLanStatus("Secure LAN uploads require opening this application over HTTPS.", "error");
    } else if (state.latestAnalysis && !validToken) {
      setLanStatus("Enter the local receiver token to authorize one manual upload.");
    }
  }

  async function responseDetail(response) {
    try {
      const body = await response.json();
      return body.detail || JSON.stringify(body);
    } catch (error) {
      return response.statusText || "Network error.";
    }
  }

  async function uploadToLan() {
    if (!state.latestAnalysis || state.collecting) return;
    const token = elements.lanToken.value.trim();
    if (token.length < 16) {
      setLanStatus("The local token must contain at least 16 characters.", "error");
      return;
    }
    state.lanPayload = state.lanPayload || buildPayload({
      enabled: true,
      scope: "local_lan",
      method: "manual_authenticated_upload",
    });
    elements.uploadButton.disabled = true;
    setLanStatus("Sending the session to the local receiver…");
    try {
      const sessionResponse = await fetch(localApiUrl("sessions"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-KlipperLearn-Token": token,
        },
        body: JSON.stringify(state.lanPayload),
      });
      if (!sessionResponse.ok) throw new Error(await responseDetail(sessionResponse));
      const receipt = await sessionResponse.json();
      for (const frame of state.cameraFrames) {
        const frameResponse = await fetch(
          localApiUrl("sessions/" + encodeURIComponent(state.sessionId) + "/frames/" + encodeURIComponent(frame.filename)),
          {
            method: "PUT",
            headers: {
              "Content-Type": "image/jpeg",
              "X-KlipperLearn-Token": token,
            },
            body: frame.blob,
          },
        );
        if (!frameResponse.ok) throw new Error(await responseDetail(frameResponse));
      }
      state.lanReceipt = receipt;
      setLanStatus(
        "Received on the host: " + receipt.session_id + ". " + state.cameraFrames.length + " verified photograph(s).",
        "ok",
      );
    } catch (error) {
      setLanStatus("Upload has not completed: " + (error.message || "network error") + ". Puedes reintentarlo.", "error");
    } finally {
      updateUploadButton();
    }
  }

  function installHandlers() {
    elements.prepareButton.addEventListener("click", prepareSources);
    elements.startButton.addEventListener("click", startCapture);
    elements.stopButton.addEventListener("click", finishCapture);
    elements.photoButton.addEventListener("click", takePhoto);
    elements.exportButton.addEventListener("click", exportSession);
    elements.uploadButton.addEventListener("click", uploadToLan);
    elements.lanToken.addEventListener("input", () => {
      try { localStorage.setItem('klipperlearn-token', elements.lanToken.value.trim()); } catch (_) {}
      sessionStorage.setItem("klipperlearn-token", elements.lanToken.value.trim());
      updateUploadButton();
    });
    window.addEventListener("beforeunload", () => {
      if (state.collecting) finishCapture();
      releaseMedia();
    });
  }

  function boot() {
    const pairing = new URLSearchParams(window.location.hash.slice(1));
    const pairingToken = pairing.get("pair");
    if (pairingToken && /^[A-Za-z0-9_-]{24,128}$/.test(pairingToken)) {
      sessionStorage.setItem("klipperlearn-token", pairingToken);
      history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    elements.lanToken.value = sessionStorage.getItem("klipperlearn-token") || "";
    setSecureBadge();
    setSessionLabel();
    renderSourceStatus();
    drawPlot();
    elements.lanEndpoint.textContent = "Receptor esperado: " + localApiUrl("sessions").toString();
    installHandlers();
    updateUploadButton();
    if ("serviceWorker" in navigator && window.isSecureContext) {
      navigator.serviceWorker.register("service-worker.js").catch(() => {});
    }
  }

  boot();
})();
