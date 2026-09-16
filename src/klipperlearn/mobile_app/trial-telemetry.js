/*
 * Passive, opt-in browser telemetry for one KlipperLearn trial.
 *
 * This file has no network, printer, companion, camera, or persistence code.
 * It can be loaded as a browser global or required by a small test harness.
 * Microphone samples are used only inside captureAudioFeature and are never
 * placed in the returned object.  The exported audio channel contains feature
 * windows (levels, bands, and dominant frequency) only.
 */
(function attachTrialTelemetry(root, factory) {
  const api = factory(root);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root && typeof root === "object") root.KlipperLearnTrialTelemetry = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createApi(root) {
  "use strict";

  const SCHEMA = "klipperlearn.trial-telemetry/v1";
  const SOURCES = ["motion", "orientation", "audio"];
  const MAX_MOTION_SAMPLES = 16384;
  const MAX_ORIENTATION_SAMPLES = 16384;
  const MAX_AUDIO_FEATURES = 4096;

  function isFiniteNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  // Native permission prompts cannot be cancelled. Bound waiting and release
  // a media stream if the user answers an expired prompt later.
  function withPermissionTimeout(promise, onLate = () => {}, timeoutMs = 20000) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => {
        settled = true;
        reject(Object.assign(new Error("Permission pending"), {name: 'TimeoutError'}));
      }, timeoutMs);
      Promise.resolve(promise).then(value => {
        if (settled) { onLate(value); return; }
        settled = true; clearTimeout(timer); resolve(value);
      }, error => {
        if (settled) return;
        settled = true; clearTimeout(timer); reject(error);
      });
    });
  }

  function safeTrialId(value) {
    return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(value);
  }

  function utcNow() {
    return new Date().toISOString();
  }

  function makeClock(environment, suppliedClock) {
    if (suppliedClock && typeof suppliedClock.now === "function") {
      return { now: suppliedClock.now, utc: suppliedClock.utc || utcNow };
    }
    const performanceObject = environment && environment.performance;
    return {
      now: () => performanceObject && typeof performanceObject.now === "function" ? performanceObject.now() : Date.now(),
      utc: utcNow,
    };
  }

  function secureContext(environment) {
    return !environment || environment.isSecureContext !== false;
  }

  function vectorFrom(source) {
    if (!source || typeof source !== "object") return null;
    const vector = {};
    ["x", "y", "z"].forEach((axis) => {
      if (isFiniteNumber(source[axis])) vector[axis] = source[axis];
    });
    return Object.keys(vector).length ? vector : null;
  }

  function magnitude(vector) {
    if (!vector) return null;
    const values = [vector.x, vector.y, vector.z].filter(isFiniteNumber);
    return values.length ? Math.sqrt(values.reduce((sum, value) => sum + value * value, 0)) : null;
  }

  function scalarStats(values) {
    if (!values.length) return null;
    const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
    return {
      mean,
      min: Math.min(...values),
      max: Math.max(...values),
      rms: Math.sqrt(values.reduce((sum, value) => sum + value * value, 0) / values.length),
    };
  }

  function timeline(samples) {
    if (!samples.length) return { sample_count: 0, first_t_ms: null, last_t_ms: null, duration_ms: 0 };
    const first = samples[0].t_ms;
    const last = samples[samples.length - 1].t_ms;
    return {
      sample_count: samples.length,
      first_t_ms: first,
      last_t_ms: last,
      duration_ms: Math.max(0, last - first),
    };
  }

  function aggregateMotion(samples) {
    const result = timeline(samples);
    result.linear_acceleration_magnitude_mps2 = scalarStats(
      samples.map((sample) => magnitude(sample.linear_acceleration_mps2)).filter(isFiniteNumber),
    );
    result.acceleration_including_gravity_magnitude_mps2 = scalarStats(
      samples.map((sample) => magnitude(sample.acceleration_including_gravity_mps2)).filter(isFiniteNumber),
    );
    result.rotation_rate_magnitude_dps = scalarStats(
      samples.map((sample) => magnitude(sample.rotation_rate_dps)).filter(isFiniteNumber),
    );
    return result;
  }

  function aggregateOrientation(samples) {
    const result = timeline(samples);
    result.absolute_sample_count = samples.filter((sample) => sample.absolute === true).length;
    ["alpha_deg", "beta_deg", "gamma_deg"].forEach((angle) => {
      result[angle] = scalarStats(samples.map((sample) => sample[angle]).filter(isFiniteNumber));
    });
    return result;
  }

  function aggregateAudioFeatures(samples) {
    const result = timeline(samples);
    const rms = samples.map((sample) => sample.rms_dbfs).filter(isFiniteNumber);
    const peaks = samples.map((sample) => sample.peak_dbfs).filter(isFiniteNumber);
    const withFrequency = samples.filter((sample) => isFiniteNumber(sample.dominant_frequency_hz));
    result.mean_rms_dbfs = rms.length ? rms.reduce((sum, value) => sum + value, 0) / rms.length : null;
    result.peak_rms_dbfs = rms.length ? Math.max(...rms) : null;
    result.peak_dbfs = peaks.length ? Math.max(...peaks) : null;
    const strongest = withFrequency.reduce(
      (best, sample) => !best || (sample.dominant_magnitude_db || -Infinity) > (best.dominant_magnitude_db || -Infinity) ? sample : best,
      null,
    );
    result.dominant_frequency_hz = strongest ? strongest.dominant_frequency_hz : null;
    const magnitudes = withFrequency.map((sample) => sample.dominant_magnitude_db).filter(isFiniteNumber);
    result.dominant_magnitude_db = magnitudes.length ? Math.max(...magnitudes) : null;
    const bands = {};
    samples.forEach((sample) => {
      if (!sample.bands_dbfs || typeof sample.bands_dbfs !== "object") return;
      Object.entries(sample.bands_dbfs).forEach(([name, value]) => {
        if (!isFiniteNumber(value)) return;
        if (!bands[name]) bands[name] = [];
        bands[name].push(value);
      });
    });
    result.mean_bands_dbfs = Object.fromEntries(
      Object.entries(bands).map(([name, values]) => [name, values.reduce((sum, value) => sum + value, 0) / values.length]),
    );
    return result;
  }

  function apiAvailable(environment, name) {
    return Boolean(environment && secureContext(environment) && typeof environment[name] !== "undefined");
  }

  function createTrialTelemetry(options) {
    const settings = options || {};
    const environment = settings.environment || settings.window || root || {};
    const navigatorObject = settings.navigator || environment.navigator || {};
    const mediaDevices = settings.mediaDevices || navigatorObject.mediaDevices;
    const eventTarget = settings.eventTarget || environment;
    const clock = makeClock(environment, settings.clock);
    const interval = settings.setInterval || environment.setInterval || setInterval;
    const clearIntervalFunction = settings.clearInterval || environment.clearInterval || clearInterval;
    const trialId = settings.trialId || settings.trial_id;
    if (!safeTrialId(trialId)) throw new TypeError("trialId must use a safe identifier format");

    const state = {
      trialId,
      started: false,
      stopped: false,
      permissionsRequested: false,
      startMonotonic: null,
      lastSampleTime: 0,
      startedAtUtc: null,
      endedAtUtc: null,
      motion: [],
      orientation: [],
      audioFeatures: [],
      dropped: { motion: 0, orientation: 0, audio: 0 },
      permissions: {
        motion: { requested: false, granted: false, state: "not_requested", api: "DeviceMotionEvent" },
        orientation: { requested: false, granted: false, state: "not_requested", api: "DeviceOrientationEvent" },
        audio: { requested: false, granted: false, state: "not_requested", api: "getUserMedia" },
      },
      stream: null,
      audioContext: null,
      analyser: null,
      audioTimer: null,
      motionHandler: null,
      orientationHandler: null,
    };

    function nowMs() {
      const value = Number(clock.now());
      return Number.isFinite(value) ? value : Date.now();
    }

    function sampleTime() {
      const current = nowMs();
      const start = state.startMonotonic === null ? current : state.startMonotonic;
      state.lastSampleTime = Math.max(state.lastSampleTime, Math.max(0, current - start));
      return state.lastSampleTime;
    }

    function sampleHeader() {
      return { trial_id: trialId, t_ms: Number(sampleTime().toFixed(3)), timestamp_utc: clock.utc() };
    }

    function capabilityReport() {
      const hasEventTarget = Boolean(eventTarget && typeof eventTarget.addEventListener === "function");
      const motion = apiAvailable(environment, "DeviceMotionEvent") && hasEventTarget;
      const orientation = apiAvailable(environment, "DeviceOrientationEvent") && hasEventTarget;
      const AudioContextConstructor = environment.AudioContext || environment.webkitAudioContext;
      const audio = secureContext(environment)
        && Boolean(mediaDevices && typeof mediaDevices.getUserMedia === "function")
        && typeof AudioContextConstructor === "function";
      return {
        secure_context: secureContext(environment),
        motion: { available: motion, reason: motion ? null : "DeviceMotionEvent is unavailable" },
        orientation: { available: orientation, reason: orientation ? null : "DeviceOrientationEvent is unavailable" },
        audio: {
          available: audio,
          reason: audio ? null : "getUserMedia or AudioContext is unavailable",
        },
      };
    }

    function setPermission(source, requested, granted, status, reason) {
      state.permissions[source] = {
        ...state.permissions[source],
        requested,
        granted,
        state: status,
        ...(reason ? { reason } : {}),
      };
    }

    async function requestSensorPermission(source, constructorName, eventName) {
      if (!apiAvailable(environment, constructorName) || !eventTarget || typeof eventTarget.addEventListener !== "function") {
        setPermission(source, true, false, "unavailable", `${eventName} unavailable`);
        return state.permissions[source];
      }
      const constructor = environment[constructorName];
      if (constructor && typeof constructor.requestPermission === "function") {
        try {
          const result = await withPermissionTimeout(constructor.requestPermission());
          if (result === "granted") setPermission(source, true, true, "granted");
          else setPermission(source, true, false, "denied", "The browser denied permission");
        } catch (error) {
          setPermission(source, true, false, "denied", "Permission could not be requested");
        }
      } else {
        setPermission(source, true, true, "granted");
      }
      return state.permissions[source];
    }

    async function requestAudioPermission() {
      const AudioContextConstructor = environment.AudioContext || environment.webkitAudioContext;
      if (!secureContext(environment) || !mediaDevices || typeof mediaDevices.getUserMedia !== "function") {
        setPermission("audio", true, false, "unavailable", "getUserMedia is unavailable in this context");
        return state.permissions.audio;
      }
      if (typeof AudioContextConstructor !== "function") {
        setPermission("audio", true, false, "unavailable", "AudioContext is unavailable");
        return state.permissions.audio;
      }
      try {
        const stream = await withPermissionTimeout(mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
          },
          video: false,
        }), late => late.getTracks().forEach(track => track.stop()));
        if (state.stopped) { stream.getTracks().forEach(track => track.stop()); return state.permissions.audio; }
        state.stream = stream;
        setPermission("audio", true, true, "granted");
      } catch (error) {
        setPermission("audio", true, false, "denied", "The browser denied microphone access");
      }
      return state.permissions.audio;
    }

    async function requestPermissions(requested = settings.sources || {}) {
      if (state.started || state.endedAtUtc !== null) throw new Error("The capture is already running or finished");
      const wanted = {
        motion: Boolean(requested && requested.motion),
        orientation: Boolean(requested && requested.orientation),
        audio: Boolean(requested && requested.audio),
      };
      state.permissionsRequested = true;
      if (!wanted.motion) setPermission("motion", false, false, "not_requested");
      if (!wanted.orientation) setPermission("orientation", false, false, "not_requested");
      if (!wanted.audio) setPermission("audio", false, false, "not_requested");
      await Promise.all([
        wanted.motion && requestSensorPermission("motion", "DeviceMotionEvent", "Movimiento"),
        wanted.orientation && requestSensorPermission("orientation", "DeviceOrientationEvent", "Orientation"),
        wanted.audio && requestAudioPermission(),
      ]);
      return {
        permissions: JSON.parse(JSON.stringify(state.permissions)),
        capabilities: capabilityReport(),
      };
    }

    function appendSample(kind, sample) {
      const collection = kind === "motion" ? state.motion : kind === "orientation" ? state.orientation : state.audioFeatures;
      const limit = kind === "motion" ? MAX_MOTION_SAMPLES : kind === "orientation" ? MAX_ORIENTATION_SAMPLES : MAX_AUDIO_FEATURES;
      if (collection.length >= limit) {
        state.dropped[kind] += 1;
        return false;
      }
      collection.push(sample);
      return true;
    }

    function recordMotion(event) {
      if (!state.started || !state.permissions.motion.granted || !event) return false;
      const sample = sampleHeader();
      const linear = vectorFrom(event.acceleration);
      const gravity = vectorFrom(event.accelerationIncludingGravity);
      const rotation = vectorFrom(event.rotationRate);
      if (linear) sample.linear_acceleration_mps2 = linear;
      if (gravity) sample.acceleration_including_gravity_mps2 = gravity;
      if (rotation) sample.rotation_rate_dps = rotation;
      if (isFiniteNumber(event.interval) && event.interval >= 0) sample.interval_ms = event.interval;
      if (!linear && !gravity && !rotation) return false;
      return appendSample("motion", sample);
    }

    function recordOrientation(event) {
      if (!state.started || !state.permissions.orientation.granted || !event) return false;
      const sample = sampleHeader();
      let hasAngle = false;
      ["alpha", "beta", "gamma"].forEach((name) => {
        if (isFiniteNumber(event[name])) {
          sample[`${name}_deg`] = event[name];
          hasAngle = true;
        }
      });
      if (typeof event.absolute === "boolean") sample.absolute = event.absolute;
      if (!hasAngle) return false;
      return appendSample("orientation", sample);
    }

    function dbFromAmplitude(amplitude) {
      return 20 * Math.log10(Math.max(amplitude, 1e-12));
    }

    function captureAudioFeature() {
      const analyser = state.analyser;
      if (!state.started || !state.permissions.audio.granted || !analyser) return false;
      const timeData = new Float32Array(analyser.fftSize);
      const frequencyData = new Float32Array(analyser.frequencyBinCount);
      try {
        analyser.getFloatTimeDomainData(timeData);
        analyser.getFloatFrequencyData(frequencyData);
      } catch (error) {
        return false;
      }
      let sumSquares = 0;
      let peak = 0;
      timeData.forEach((value) => {
        sumSquares += value * value;
        peak = Math.max(peak, Math.abs(value));
      });
      let dominantIndex = -1;
      let dominantDb = -Infinity;
      frequencyData.forEach((value, index) => {
        if (Number.isFinite(value) && value > dominantDb) {
          dominantDb = value;
          dominantIndex = index;
        }
      });
      const sampleRate = state.audioContext && state.audioContext.sampleRate;
      const feature = sampleHeader();
      feature.rms_dbfs = dbFromAmplitude(Math.sqrt(sumSquares / Math.max(1, timeData.length)));
      feature.peak_dbfs = dbFromAmplitude(peak);
      if (dominantIndex >= 0 && isFiniteNumber(sampleRate) && sampleRate > 0) {
        feature.dominant_frequency_hz = dominantIndex * sampleRate / analyser.fftSize;
        feature.dominant_magnitude_db = dominantDb;
      }
      const bands = { low: [], mid: [], high: [] };
      frequencyData.forEach((value, index) => {
        if (!Number.isFinite(value) || !isFiniteNumber(sampleRate) || sampleRate <= 0) return;
        const frequency = index * sampleRate / analyser.fftSize;
        if (frequency < 250) bands.low.push(value);
        else if (frequency < 2000) bands.mid.push(value);
        else bands.high.push(value);
      });
      feature.bands_dbfs = Object.fromEntries(
        Object.entries(bands)
          .filter(([, values]) => values.length)
          .map(([name, values]) => [name, values.reduce((sum, value) => sum + value, 0) / values.length]),
      );
      feature.sample_rate_hz = sampleRate;
      feature.fft_size = analyser.fftSize;
      feature.method = "analysernode_feature_window_no_raw_audio";
      return appendSample("audio", feature);
    }

    async function setupAudio() {
      if (!state.stream || !state.permissions.audio.granted) return false;
      const AudioContextConstructor = environment.AudioContext || environment.webkitAudioContext;
      if (typeof AudioContextConstructor !== "function") {
        setPermission("audio", true, false, "unavailable", "AudioContext is unavailable");
        await releaseAudio();
        return false;
      }
      try {
        state.audioContext = new AudioContextConstructor();
        const source = state.audioContext.createMediaStreamSource(state.stream);
        state.analyser = state.audioContext.createAnalyser();
        state.analyser.fftSize = 2048;
        state.analyser.smoothingTimeConstant = 0.15;
        source.connect(state.analyser);
        if (typeof state.audioContext.resume === "function") await state.audioContext.resume();
        const requestedInterval = Number(settings.audioIntervalMs);
        const audioIntervalMs = Number.isFinite(requestedInterval)
          ? Math.min(2000, Math.max(100, requestedInterval))
          : 250;
        state.audioTimer = interval(captureAudioFeature, audioIntervalMs);
        return true;
      } catch (error) {
        setPermission("audio", true, false, "unavailable", "Acoustic analysis could not be prepared");
        await releaseAudio();
        return false;
      }
    }

    function degradation() {
      const samples = { motion: state.motion, orientation: state.orientation, audio: state.audioFeatures };
      return SOURCES.reduce((reasons, source) => {
        if (state.permissions[source].state !== "granted") reasons.push(`${source}:${state.permissions[source].state}`);
        if (!samples[source].length) reasons.push(`${source}:no_samples`);
        return reasons;
      }, []);
    }

    function telemetry() {
      return {
        schema: SCHEMA,
        source: "web",
        trial_id: trialId,
        started_at_utc: state.startedAtUtc,
        ended_at_utc: state.endedAtUtc,
        permissions: JSON.parse(JSON.stringify(state.permissions)),
        capabilities: capabilityReport(),
        privacy: {
          raw_audio_saved: false,
          audio_storage: "aggregated_metrics_only",
        },
        samples: {
          motion: state.motion.slice(),
          orientation: state.orientation.slice(),
          audio_features: state.audioFeatures.slice(),
        },
        metrics: {
          motion: aggregateMotion(state.motion),
          orientation: aggregateOrientation(state.orientation),
          audio: aggregateAudioFeatures(state.audioFeatures),
        },
        degradation: degradation(),
        dropped_samples: { ...state.dropped },
      };
    }

    async function start() {
      if (!state.permissionsRequested) throw new Error("Request permissions explicitly before starting");
      if (state.endedAtUtc !== null) throw new Error("This capture has already finished");
      if (state.started) return telemetry();
      state.started = true;
      state.startMonotonic = nowMs();
      state.lastSampleTime = 0;
      state.startedAtUtc = clock.utc();
      state.endedAtUtc = null;
      if (state.permissions.motion.granted) {
        state.motionHandler = recordMotion;
        eventTarget.addEventListener("devicemotion", state.motionHandler, { passive: true });
      }
      if (state.permissions.orientation.granted) {
        state.orientationHandler = recordOrientation;
        eventTarget.addEventListener("deviceorientation", state.orientationHandler, { passive: true });
      }
      await setupAudio();
      return telemetry();
    }

    async function releaseAudio() {
      if (state.audioTimer !== null) {
        clearIntervalFunction(state.audioTimer);
        state.audioTimer = null;
      }
      if (state.audioContext && typeof state.audioContext.close === "function") {
        try { await state.audioContext.close(); } catch (error) { /* best effort */ }
      }
      state.audioContext = null;
      state.analyser = null;
      if (state.stream && typeof state.stream.getTracks === "function") {
        state.stream.getTracks().forEach((track) => {
          if (track && typeof track.stop === "function") track.stop();
        });
      }
      state.stream = null;
    }

    async function stop() {
      state.stopped = true;
      if (!state.started) {
        await releaseAudio();
        return telemetry();
      }
      captureAudioFeature();
      state.started = false;
      if (state.motionHandler && eventTarget && typeof eventTarget.removeEventListener === "function") {
        eventTarget.removeEventListener("devicemotion", state.motionHandler);
      }
      if (state.orientationHandler && eventTarget && typeof eventTarget.removeEventListener === "function") {
        eventTarget.removeEventListener("deviceorientation", state.orientationHandler);
      }
      state.motionHandler = null;
      state.orientationHandler = null;
      state.endedAtUtc = clock.utc();
      const result = telemetry();
      await releaseAudio();
      return result;
    }

    function acknowledge(snapshot) {
      if (!snapshot || snapshot.trial_id !== state.trialId) return;
      for (const [name, collection] of [['motion', state.motion], ['orientation', state.orientation], ['audio_features', state.audioFeatures]]) {
        const sent = snapshot.samples?.[name] || [];
        let count = 0;
        while (count < sent.length && count < collection.length && collection[count] === sent[count]) count++;
        collection.splice(0, count);
      }
    }

    return {
      acknowledge,
      capabilities: capabilityReport,
      requestPermissions,
      start,
      stop,
      snapshot: telemetry,
      recordMotion,
      recordOrientation,
      captureAudioFeature,
      aggregateMotion,
      aggregateOrientation,
      aggregateAudioFeatures,
    };
  }

  return {
    SCHEMA,
    withPermissionTimeout,
    createTrialTelemetry,
    aggregateMotion,
    aggregateOrientation,
    aggregateAudioFeatures,
  };
});
