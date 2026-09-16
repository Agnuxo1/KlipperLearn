(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const manualStates = new Set(['standby', 'complete', 'cancelled', 'error']);
  const activePrintStates = new Set(['printing', 'paused']);
  const stateLabels = {standby: "Standby", printing: "Printing", paused: "Paused", complete: "Completed", cancelled: 'Cancelada', error: 'Error', unknown: "Unknown"};
  const modelPattern = /\.(?:gcode|gco|g|g3d)$/i;
  const errors = {401: "Invalid pairing.", 403: "Unauthorized action.", 404: "Action unavailable.", 409: "The current state does not permit this action.", 422: "Review command values.", 503: "Unable to connect to the printer."};
  const STALE_MS = 8000;
  const fallbackLimits = {extruder: 275, bed: 110};
  let limits = {...fallbackLimits};
  let pending = false, modelsPending = false, modelsLoaded = false;
  let connectionReady = false, printerState = 'unknown', tokenRevision = 0;
  let lastStatus = 0, statusSequence = 0, modelFiles = [];
  let capabilities = null, capabilitiesAt = 0, capabilitySequence = 0;
  let targets = {extruder: 0, bed: 0};
  const draftDirty = {hotendTarget: false, bedTarget: false};
  const sensorTrialPattern = /^[0-9a-f]{32}$/;
  const requestedSensorSources = Object.freeze({motion: true, orientation: true, audio: true});
  let sensorSources = {...requestedSensorSources};
  const SENSOR_ACTIVE_POLL_MS = 5000;
  const SENSOR_UPLOAD_MS = 5000;
  const PHOTO_QUEUE_POLL_MS = 5000;
  let sensorPaired = false, sensorArmed = false, sensorBusy = false;
  let sensorActiveTrialId = null, sensorCollector = null, sensorCollectorTrialId = null;
  let sensorPermissionReport = null, sensorPollTimer = null, sensorUploadTimer = null;
  let sensorPollBusy = false, sensorStartBusy = false, sensorUploadBusy = false;
  let sensorRevision = 0;
  let photoPairController = null, photoPairTimer = null, photoPairAbort = null;
  let photoPairBusy = false;
  const ONBOARDING_PERMISSION_KEY = 'klipperlearn-console-permissions-v1';
  let onboardingBusy = false, onboardingRevision = 0;
  let activationRequested = false, activationCompleted = false, peripheralPromise = null, connectPromise = null;

  const fragment = new URLSearchParams(location.hash.slice(1));
  const pair = fragment.get('pair');
  let storedToken = '';
  try { storedToken = localStorage.getItem('klipperlearn-token') || sessionStorage.getItem('klipperlearn-token') || ''; } catch (_) {}
  const validPair = Boolean(pair && /^[A-Za-z0-9_-]{24,128}$/.test(pair));
  if (validPair) {
    storedToken = pair;
    try { localStorage.setItem('klipperlearn-token', pair); sessionStorage.setItem('klipperlearn-token', pair); } catch (_) {}
  }
  if (fragment.has('pair')) history.replaceState(null, '', location.pathname + location.search);
  sensorPaired = Boolean(validPair || storedToken);

  function currentToken() {
    return storedToken.trim();
  }

  async function connectLocal() {
    if (connectPromise) return connectPromise;
    connectPromise = (async () => {
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch('/mobile/api/connect', {method: 'POST', cache: 'no-store',
          signal: controller.signal, headers: {'X-KlipperLearn-Connect': '1'}});
        if (!response.ok) throw localError("Local connection failed. Check the printer Wi-Fi network.");
        const value = (await response.json())?.result?.token;
        if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{24,128}$/.test(value)) throw localError("Invalid connection response.");
        if (storedToken !== value) tokenRevision++;
        storedToken = value; sensorPaired = true;
        try { localStorage.setItem('klipperlearn-token', value); sessionStorage.setItem('klipperlearn-token', value); } catch (_) {}
        renderPairingStatus();
      } finally { clearTimeout(timer); }
    })();
    try { await connectPromise; } finally { connectPromise = null; }
  }

  function renderPairingStatus() {
    const paired = Boolean(currentToken());
    const label = paired ? "Local connection" : "Ready to connect";
    const status = $('pairingStatus');
    const info = $('pairingInfo');
    if (status) { status.textContent = label; status.className = 'pairing-status' + (paired ? ' ok' : ''); }
    if (info) info.textContent = paired
      ? "This device remembers the printer connection."
      : "Tap Connect printer. The connection is prepared automatically.";
  }

  function numberValue(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  }
  function publicText(value, fallback = '') {
    if (value === null || value === undefined) return fallback;
    let text = String(value);
    const token = currentToken();
    if (token) text = text.split(token).join('[oculto]');
    return text.slice(0, 512);
  }
  function localError(message) {
    const error = Error(message);
    error.safe = true;
    return error;
  }
  function spanishError(error, fallback) {
    return error && error.safe ? error.message : fallback;
  }
  function setOnboardingStatus(message, error = false) {
    const element = $('onboardingStatus');
    if (!element) return;
    element.textContent = publicText(message);
    element.className = 'network-status' + (error ? ' error' : '');
  }
  function setOnboardingStep(name, state) {
    const id = {permissions: 'onboardingStepPermissions', stream: 'onboardingStepStream', printer: 'onboardingStepPrinter'}[name];
    const element = id && $(id);
    if (!element) return;
    element.dataset.state = state;
    if (state === 'active') element.setAttribute('aria-current', 'step');
    else element.removeAttribute('aria-current');
  }
  function resetOnboardingProgress() {
    ['permissions', 'stream', 'printer'].forEach(name => setOnboardingStep(name, 'pending'));
  }
  function renderOnboarding() {
    const card = $('onboardingCard'), button = $('activatePrinter');
    if (!card || !button) return;
    const ready = Boolean(activationRequested && currentToken() && fresh());
    if (ready) activationCompleted = true;
    // A network interruption must not cover navigation or the emergency stop.
    card.hidden = photoPairBusy || activationCompleted;
    button.disabled = onboardingBusy || photoPairBusy;
    button.setAttribute('aria-busy', String(onboardingBusy));
  }
  function rememberOnboardingPermissions(report, cameraReady) {
    const permissions = report?.permissions || {};
    try {
      localStorage.setItem(ONBOARDING_PERMISSION_KEY, JSON.stringify({
        activated: true, camera: Boolean(cameraReady),
        motion: permissions.motion?.granted === true,
        orientation: permissions.orientation?.granted === true,
        microphone: permissions.audio?.granted === true
      }));
    } catch (_) {}
  }
  function readOnboardingPermissions() {
    try {
      const value = JSON.parse(localStorage.getItem(ONBOARDING_PERMISSION_KEY) || 'null');
      return value && typeof value === 'object' ? value : null;
    } catch (_) { return null; }
  }
  async function permissionsReadyForReconnect() {
    const remembered = readOnboardingPermissions();
    return Boolean(remembered?.activated || remembered?.camera);
  }
  async function api(path, options = {}) {
    const token = currentToken();
    if (!token) throw localError("Tap Connect printer to connect.");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), path === 'printer/start' ? 60000 : 8000);
    try {
      const response = await fetch('/mobile/api/' + path, {
        ...options, cache: 'no-store', signal: controller.signal,
        headers: {...(options.headers || {}), 'X-KlipperLearn-Token': token}
      });
      if (!response.ok) {
        const error = localError(errors[response.status] || "The request could not be completed.");
        error.status = response.status;
        throw error;
      }
      return response.status === 204 ? null : await response.json();
    } catch (error) {
      if (error.safe) throw error;
      throw localError(controller.signal.aborted ? "Request timed out. Check the connection." : "Unable to connect to the service.");
    } finally { clearTimeout(timeout); }
  }
  function apiResult(payload) {
    return payload && Object.prototype.hasOwnProperty.call(payload, 'result') ? payload.result : payload;
  }
  function normalizeSensorTrialId(value) {
    return typeof value === 'string' && sensorTrialPattern.test(value) ? value : null;
  }
  function activeSensorTrialId(payload) {
    const result = apiResult(payload);
    const values = [result];
    if (result && typeof result === 'object' && !Array.isArray(result)) {
      ['active', 'trial', 'current', 'trial_info'].forEach(key => { if (result[key] !== undefined) values.push(result[key]); });
      ['trial_id', 'trialId', 'active_trial_id', 'activeTrialId', 'id'].forEach(key => {
        if (result[key] !== undefined) values.push(result[key]);
      });
    }
    for (const value of values) {
      const candidate = typeof value === 'string' ? value : value && typeof value === 'object'
        ? value.trial_id ?? value.trialId ?? value.active_trial_id ?? value.activeTrialId ?? value.id
        : null;
      const trialId = normalizeSensorTrialId(candidate);
      if (trialId) return trialId;
    }
    return null;
  }
  function setSensorStatus(message, error = false) {
    const element = $('sensorStatus');
    element.textContent = publicText(message);
    element.className = 'network-status' + (error ? ' error' : '');
  }
  function setPhotoPairStatus(message, error = false) {
    const element = $('photoPairStatus');
    element.textContent = publicText(message);
    element.className = 'network-status' + (error ? ' error' : '');
  }
  function renderSensorControls() {
    const button = $('sensorPermissions'), stop = $('sensorStop');
    const hasToken = Boolean(currentToken());
    button.disabled = onboardingBusy || sensorBusy;
    button.textContent = "Connect printer";
    stop.disabled = !sensorArmed && !sensorCollector && !photoPairBusy;
    renderOnboarding();
  }
  function createSensorCollector(trialId) {
    const factory = window.KlipperLearnTrialTelemetry?.createTrialTelemetry;
    if (typeof factory !== 'function') throw localError("The sensor collector did not load.");
    return factory({
      trialId,
      environment: window,
      navigator,
      eventTarget: window,
      sources: sensorSources,
      audioIntervalMs: 250,
    });
  }
  function telemetryUploadPayload(trialId, snapshot) {
    return {...snapshot, trial_id: trialId};
  }
  let telemetryOutbox = null;
  async function telemetryScope(token) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(token));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  }
  function ensureTelemetryOutbox() {
    if (!telemetryOutbox) {
      const create = window.KlipperLearnTelemetryOutbox?.createOutbox;
      if (!create) throw localError("Local sensor storage did not load.");
      telemetryOutbox = create({send: async (payload, scope) => {
        const token = currentToken();
        if (!token || await telemetryScope(token) !== scope || currentToken() !== token) {
          throw localError("Pairing changed. Previous sensor data remain stored locally.");
        }
        await api('trial-telemetry/' + encodeURIComponent(payload.trial_id) + '/snapshot', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
        });
      }});
    }
    return telemetryOutbox;
  }
  async function retryTelemetryOutbox() {
    const token = currentToken();
    if (!token || navigator.onLine === false) return;
    try {
      const delivered = await ensureTelemetryOutbox().flush(await telemetryScope(token));
      if (delivered) setSensorStatus("Pending data were resent to the local server.");
    } catch (_) { /* Pending records remain durable; normal uploads report failures. */ }
  }
  async function uploadTelemetrySnapshotFor(trialId, snapshot, collector = null) {
    if (!normalizeSensorTrialId(trialId) || !snapshot) return false;
    const payload = telemetryUploadPayload(trialId, snapshot);
    const scope = await telemetryScope(currentToken());
    const outbox = ensureTelemetryOutbox();
    await outbox.enqueue(scope, payload, () => collector?.acknowledge?.(snapshot));
    try { await outbox.flush(scope); }
    catch (_) { throw localError("Sensors are saved on this device and will be uploaded when the connection recovers."); }
    return true;
  }
  async function uploadTelemetrySnapshot() {
    const collector = sensorCollector, trialId = sensorCollectorTrialId;
    if (!collector || !trialId || sensorUploadBusy) return;
    sensorUploadBusy = true;
    try {
      await uploadTelemetrySnapshotFor(trialId, collector.snapshot(), collector);
      if (collector === sensorCollector) setSensorStatus('Ensayo ' + publicText(trialId) + " · sending sensors and metrics.");
    } catch (error) {
      if (collector === sensorCollector) setSensorStatus(spanishError(error, "Trial metrics could not be uploaded."), true);
    } finally {
      sensorUploadBusy = false;
    }
  }
  function clearSensorUploadTimer() {
    if (sensorUploadTimer !== null) clearInterval(sensorUploadTimer);
    sensorUploadTimer = null;
  }
  async function stopSensorCollector(uploadFinal = false) {
    clearSensorUploadTimer();
    const collector = sensorCollector, trialId = sensorCollectorTrialId;
    sensorCollector = null;
    sensorCollectorTrialId = null;
    renderSensorControls();
    if (!collector) return;
    try {
      const snapshot = await collector.stop();
      if (uploadFinal && trialId && currentToken()) await uploadTelemetrySnapshotFor(trialId, snapshot);
    } catch (error) {
      setSensorStatus(spanishError(error, "Sensor capture could not be closed."), true);
    }
  }
  async function startSensorCollectorFor(trialId) {
    if (!sensorArmed || !normalizeSensorTrialId(trialId) || sensorStartBusy) return;
    if (sensorCollector && sensorCollectorTrialId === trialId) return;
    sensorStartBusy = true;
    const revision = sensorRevision;
    let collector = null;
    try {
      await stopSensorCollector(true);
      collector = createSensorCollector(trialId);
      const report = await collector.requestPermissions(sensorSources);
      if (revision !== sensorRevision || !sensorArmed || sensorActiveTrialId !== trialId) {
        await collector.stop();
        return;
      }
      sensorPermissionReport = report.permissions;
      await collector.start();
      if (revision !== sensorRevision || !sensorArmed || sensorActiveTrialId !== trialId) {
        await collector.stop();
        return;
      }
      sensorCollector = collector;
      sensorCollectorTrialId = trialId;
      sensorUploadTimer = setInterval(() => { void uploadTelemetrySnapshot(); }, SENSOR_UPLOAD_MS);
      setSensorStatus('Ensayo activo ' + publicText(trialId) + ' · sensores iniciados.');
      void uploadTelemetrySnapshot();
      schedulePhotoPair(0);
    } catch (error) {
      if (collector) await collector.stop().catch(() => {});
      if (revision === sensorRevision) setSensorStatus(spanishError(error, "The sensor collector could not be started."), true);
    } finally {
      sensorStartBusy = false;
      renderSensorControls();
    }
  }
  function scheduleSensorPoll(delay = SENSOR_ACTIVE_POLL_MS) {
    if (sensorPollTimer !== null) clearTimeout(sensorPollTimer);
    if (!sensorPaired || !currentToken()) { sensorPollTimer = null; return; }
    sensorPollTimer = setTimeout(() => { sensorPollTimer = null; void pollActiveSensorTrial(); }, Math.max(0, delay));
  }
  async function pollActiveSensorTrial() {
    if (!sensorPaired || !currentToken()) return;
    if (sensorPollBusy) { scheduleSensorPoll(); return; }
    sensorPollBusy = true;
    const revision = tokenRevision;
    try {
      const nextTrialId = activeSensorTrialId(await api('trial-telemetry/active'));
      if (revision !== tokenRevision) return;
      const changed = nextTrialId !== sensorActiveTrialId;
      sensorActiveTrialId = nextTrialId;
      if (changed && sensorCollector) await stopSensorCollector(true);
      if (nextTrialId && sensorArmed) await startSensorCollectorFor(nextTrialId);
      if (!nextTrialId) {
        // Final photographs belong to a completed job, not to the lifetime of
        // its sensor collector. Do not cancel an in-flight final capture.
        if (!photoPairBusy && photoPairTimer === null) schedulePhotoPair(0);
        if (sensorArmed && !sensorCollector) setSensorStatus("Permissions ready · waiting for an active trial.");
      }
      renderSensorControls();
    } catch (error) {
      if (revision === tokenRevision && ![404, 405].includes(error.status)) {
        setSensorStatus(spanishError(error, "The active trial could not be queried."), true);
      }
    } finally {
      sensorPollBusy = false;
      if (revision === tokenRevision) scheduleSensorPoll();
    }
  }
  function requiredSensorPermissionError(report) {
    const permissions = report?.permissions || {};
    const unavailable = Object.entries(permissions).filter(([, value]) => value?.granted !== true).map(([name]) => ({motion:'movimiento',orientation:"orientation",audio:"microphone"}[name]));
    return unavailable.length ? "No " + unavailable.join(', ') + "; the printer and available sensors will continue working." : '';
  }
  async function armSensorsFromGesture({onboarding = false, automatic = false} = {}) {
    if (sensorArmed && !onboarding) return {ok: true, report: {permissions: sensorPermissionReport}, active: Boolean(sensorCollector)};
    if (!onboarding && !automatic && $('sensorPermissions').disabled) return {ok: false};
    sensorBusy = true;
    const revision = ++sensorRevision;
    renderSensorControls();
    let probe = null;
    let report = null;
    try {
      // This call is deliberately reached from the visible button click: iOS motion/orientation permission
      // requests otherwise fail before the collector can be attached to the active trial.
      probe = createSensorCollector(sensorActiveTrialId || 'pending-sensor-pairing');
      report = await probe.requestPermissions(requestedSensorSources);
      sensorPermissionReport = report.permissions;
      sensorSources = Object.fromEntries(Object.entries(requestedSensorSources).map(([name]) => [name, report.permissions?.[name]?.granted === true]));
      const permissionWarning = requiredSensorPermissionError(report);
      await probe.stop();
      if (revision !== sensorRevision) return;
      sensorArmed = true;
      sensorPaired = true;
      setSensorStatus(permissionWarning || "Permissions checked · looking for the active trial…", Boolean(permissionWarning));
      if (currentToken()) await pollActiveSensorTrial();
      if (revision === sensorRevision && !sensorActiveTrialId) setSensorStatus(permissionWarning || "Permissions ready · waiting for an active trial.", Boolean(permissionWarning));
      if (sensorActiveTrialId && !sensorCollector) throw localError("Telemetry could not be started. Tap Connect printer to retry.");
      return {ok: true, report, active: Boolean(sensorCollector), warning: permissionWarning};
    } catch (error) {
      if (probe) await probe.stop().catch(() => {});
      if (revision === sensorRevision) {
        sensorArmed = false;
        setSensorStatus(spanishError(error, "Sensor permissions could not be requested."), true);
      }
      if (onboarding) throw error;
      return {ok: false, report, error};
    } finally {
      if (revision === sensorRevision) { sensorBusy = false; renderSensorControls(); }
    }
  }
  async function stopSensorCapture() {
    sensorArmed = false;
    ++sensorRevision;
    await stopSensorCollector(true);
    setSensorStatus("Sensors stopped. Tap once to authorize them again.");
    sensorBusy = false;
    renderSensorControls();
  }
  function ensurePhotoPairController() {
    if (photoPairController) return photoPairController;
    const factory = window.KlipperLearnPhotoPair?.createPhotoPairController;
    if (typeof factory !== 'function') throw localError("The paired-photo processor did not load.");
    photoPairController = factory({
      apiBase: '/mobile/api',
      token: currentToken,
      onProgress: event => {
        if (event.type === 'claimed') setPhotoPairStatus("Capturing paired photographs…");
        if (event.type === 'light-set') setPhotoPairStatus('Capturando ' + event.mode + '…');
        if (event.type === 'uploaded') setPhotoPairStatus('Subida ' + event.mode + '.');
        if (event.type === 'complete') setPhotoPairStatus('Pareja torch-off/on completada.');
        if (event.type === 'error') setPhotoPairStatus(event.message || "Paired photographs failed.", true);
      },
    });
    return photoPairController;
  }
  function cancelPhotoPair() {
    if (photoPairTimer !== null) clearTimeout(photoPairTimer);
    photoPairTimer = null;
    if (photoPairAbort) photoPairAbort.abort();
    photoPairAbort = null;
  }
  function schedulePhotoPair(delay = PHOTO_QUEUE_POLL_MS) {
    if (photoPairTimer !== null) clearTimeout(photoPairTimer);
    // Camera permission is independent of microphone/motion permission.
    if (!cameraWanted) { photoPairTimer = null; return; }
    photoPairTimer = setTimeout(() => { photoPairTimer = null; void processPhotoPairQueue(); }, Math.max(0, delay));
  }
  async function processPhotoPairQueue() {
    if (!cameraWanted || !currentToken() || !fresh() || photoPairBusy || document.hidden || onboardingBusy
        || !['standby', 'complete', 'cancelled'].includes(printerState)) {
      schedulePhotoPair();
      return;
    }
    photoPairBusy = true;
    renderSensorControls();
    photoPairAbort = new AbortController();
    const signal = photoPairAbort.signal;
    const resumeLive = Boolean(camera || cameraWanted);
    let pausedLive = false;
    try {
      const controller = ensurePhotoPairController();
      const job = await controller.claimNext({signal});
      if (!job) return;
      if (camera || startingCamera) {
        pausedLive = true;
        await stopCamera(true, "Live camera paused for paired photographs…");
      }
      const result = await controller.captureJob(job, {signal});
      if (result) setPhotoPairStatus(result.error ? "Paired photographs ended with an error." : 'Pareja torch-off/on completada.');
      else setPhotoPairStatus("Paired-photo queue ready · no pending jobs.");
    } catch (error) {
      const message = error?.name === 'PhotoPairError' ? error.message : "The paired-photo queue could not be processed.";
      if (cameraWanted) setPhotoPairStatus(message, true);
    } finally {
      photoPairBusy = false;
      photoPairAbort = null;
      if (pausedLive && resumeLive && cameraWanted && !document.hidden) await startCamera();
      renderSensorControls();
      schedulePhotoPair();
    }
  }
  function setCommand(message, error = false) {
    ['command', 'temperatureStatus'].forEach(id => {
      $(id).textContent = publicText(message);
      $(id).className = 'network-status' + (error ? ' error' : ' ok');
    });
  }
  function setModelsStatus(message, error = false) {
    $('modelsStatus').textContent = message;
    $('modelsStatus').className = 'network-status' + (error ? ' error' : '');
  }
  function setConnection(ready, message) {
    $('connectionBadge').textContent = ready ? "Connected" : "Disconnected";
    $('connectionBadge').className = 'badge ' + (ready ? 'ok' : 'warn');
    $('connection').textContent = message;
  }
  function fresh() {
    return connectionReady && navigator.onLine !== false && lastStatus > 0 && Date.now() - lastStatus < STALE_MS;
  }
  function canTransport() { return fresh() && !pending && !modelsPending; }
  function canManualCommand() { return canTransport() && manualStates.has(printerState); }
  function canPrint() { return canManualCommand() && ['standby', 'complete', 'cancelled'].includes(printerState); }
  function renderControls() {
    const manual = canManualCommand(), transport = canTransport();
    ['home', 'heatOpen', 'coolAll', 'applyHotend', 'applyBed', 'hotendTarget', 'bedTarget'].forEach(id => { $(id).disabled = !manual; });
    $('pause').disabled = !transport || printerState !== 'printing';
    $('resume').disabled = !transport || printerState !== 'paused';
    $('cancel').disabled = !transport || !activePrintStates.has(printerState);
    $('pause').hidden = printerState !== 'printing';
    $('resume').hidden = printerState !== 'paused';
    $('cancel').hidden = !activePrintStates.has(printerState);
    const fileDisabled = !fresh() || pending || modelsPending;
    $('refreshModels').disabled = fileDisabled;
    $('modelSelect').disabled = fileDisabled || !modelsLoaded || !modelFiles.length;
    $('printModel').disabled = !canPrint() || !modelFiles.includes($('modelSelect').value);
    $('modelCard').setAttribute('aria-busy', String(modelsPending));
    document.querySelectorAll('.model-tile').forEach(button => {
      button.disabled = fileDisabled;
      button.setAttribute('aria-pressed', String(button.dataset.filename === $('modelSelect').value));
    });
    renderSensorControls();
  }
  function invalidateStatus(message) {
    lastStatus = 0;
    connectionReady = false;
    printerState = 'unknown';
    $('file').textContent = "No print data";
    ['hotend', 'bed', 'progress'].forEach(id => { $(id).textContent = '—'; });
    $('printState').textContent = "Unknown";
    $('progressBar').value = 0;
    $('hotendTargetReading').textContent = $('bedTargetReading').textContent = "Target: —";
    setConnection(false, message);
    renderControls();
    renderCalibration();
  }
  function setTargetInput(id, value) {
    if (!draftDirty[id] && numberValue(value) !== null) $(id).value = String(value);
  }
  async function status() {
    const revision = tokenRevision, sequence = ++statusSequence;
    try {
      const payload = await api('printer/status');
      if (revision !== tokenRevision || sequence !== statusSequence) return;
      const printer = payload?.result?.status;
      if (!printer?.webhooks || !printer?.print_stats) throw localError("Printer state is unknown.");
      const wasReady = connectionReady;
      connectionReady = printer.webhooks.state === 'ready';
      printerState = typeof printer.print_stats.state === 'string' ? printer.print_stats.state.toLowerCase() : 'unknown';
      lastStatus = Date.now();
      $('file').textContent = publicText(printer.print_stats.filename, '') || "No print";
      $('printState').textContent = stateLabels[printerState] || "Unknown";
      [['hotend', 'hotendTarget', 'extruder', printer.extruder], ['bed', 'bedTarget', 'bed', printer.heater_bed]].forEach(([reading, input, key, sensor]) => {
        const current = numberValue(sensor?.temperature), target = numberValue(sensor?.target);
        $(reading).textContent = current === null ? '—' : current.toFixed(1) + '°';
        $(reading + 'TargetReading').textContent = target === null ? "Target: —" : 'Objetivo: ' + target + ' °C';
        if (target !== null) { targets[key] = target; setTargetInput(input, target); }
      });
      const progress = numberValue(printer.virtual_sdcard?.progress);
      $('progress').textContent = progress === null ? '—' : (Math.max(0, Math.min(1, progress)) * 100).toFixed(0) + '%';
      $('progressBar').value = progress === null ? 0 : Math.max(0, Math.min(100, progress * 100));
      setConnection(connectionReady, connectionReady ? 'Conectada · ' + (stateLabels[printerState] || "Unknown state") : "Printer unavailable.");
      renderControls();
      renderCalibration();
      if (connectionReady && !wasReady && !modelsLoaded && !modelsPending && !pending) void refreshModels();
      return connectionReady;
    } catch (error) {
      if (revision === tokenRevision && sequence === statusSequence) invalidateStatus(spanishError(error, "The printer could not be queried."));
      return false;
    }
  }
  async function poll() {
    await status();
    setTimeout(poll, 3000);
  }

  function applyLimits() {
    const real = capabilities?.connected === true ? capabilities.limits : null;
    const positive = (value, fallback) => numberValue(value) !== null && value > 0 ? value : fallback;
    limits = {extruder: positive(real?.extruder_max, fallbackLimits.extruder), bed: positive(real?.bed_max, fallbackLimits.bed)};
    [['hotendTarget', limits.extruder], ['bedTarget', limits.bed]].forEach(([id, maximum]) => {
      $(id).max = String(maximum);
      $(id + 'Hint').textContent = "Between 0 and " + maximum + ' °C';
    });
  }
  function renderCalibration() {
    const known = capabilities?.connected === true && fresh() && Date.now() - capabilitiesAt < 45000;
    $('capabilityStatus').textContent = known ? "Preparing · capabilities retrieved" : "Preparing · unknown state";
    const details = $('capabilityDetails');
    details.replaceChildren();
    const add = (label, value) => {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label; dd.textContent = publicText(value);
      details.append(dt, dd);
    };
    add("Machine", known ? capabilities.machine?.name || "Unknown" : "Unknown");
    add("Status", fresh() ? stateLabels[printerState] || "Unknown" : "Unknown");
    const feature = key => !known || typeof capabilities.features?.[key] !== 'boolean' ? "Unknown" : capabilities.features[key] ? "Available" : 'No disponible';
    add('Input shaper', feature('input_shaper'));
    add('Resonancias', feature('resonance_tester'));
    add("Accelerometer", feature('accelerometer'));
    add('Pressure advance', feature('pressure_advance'));
    const measured = value => known && numberValue(value) !== null ? value : '—';
    add("Maximum speed", measured(capabilities?.limits?.max_velocity) + (known && numberValue(capabilities?.limits?.max_velocity) !== null ? ' mm/s' : ''));
    add("Maximum acceleration", measured(capabilities?.limits?.max_accel) + (known && numberValue(capabilities?.limits?.max_accel) !== null ? ' mm/s²' : ''));
    if (known && capabilities.input_shaper && typeof capabilities.input_shaper === 'object') {
      ['x', 'y'].forEach(axis => {
        const frequency = numberValue(capabilities.input_shaper['shaper_freq_' + axis]);
        add('Shaper ' + axis.toUpperCase(), frequency === null ? "No data" : frequency + ' Hz');
      });
    }
    const calibration = known ? capabilities.calibration : null;
    const automatic = calibration?.automatic_available === false ? "Automatic trials unavailable." : "Automatic trials: unverified.";
    const model = calibration?.model_trained === false ? "Model not trained." : "Model: unverified.";
    $('calibrationTruth').textContent = known ? automatic + ' ' + model : "Calibration and model status: unknown.";
  }
  async function loadCapabilities() {
    const revision = tokenRevision, sequence = ++capabilitySequence;
    $('refreshCapabilities').disabled = true;
    try {
      const payload = await api('printer/capabilities');
      if (revision !== tokenRevision || sequence !== capabilitySequence) return;
      capabilities = payload?.result || null;
      capabilitiesAt = Date.now();
    } catch (_) {
      if (revision === tokenRevision && sequence === capabilitySequence) { capabilities = null; capabilitiesAt = 0; }
    } finally {
      if (sequence === capabilitySequence) {
        applyLimits(); renderCalibration();
        $('refreshCapabilities').disabled = false;
      }
      return capabilities;
    }
  }

  function isModelFilename(filename) {
    return typeof filename === 'string' && filename.length > 0 && filename.length <= 512 && !/[\u0000-\u001f\u007f]/.test(filename) && modelPattern.test(filename);
  }
  function modelNames(payload) {
    const entries = Array.isArray(payload) ? payload : Array.isArray(payload?.files) ? payload.files : Array.isArray(payload?.result) ? payload.result : payload?.result?.files;
    if (!Array.isArray(entries)) throw localError("The model list is invalid.");
    return [...new Set(entries.map(entry => typeof entry === 'string' ? entry : entry?.path || entry?.filename || entry?.name).filter(isModelFilename))].sort((a, b) => a.localeCompare(b, "en-GB", {numeric: true}));
  }
  function renderModels(names) {
    const select = $('modelSelect'), previous = select.value;
    modelFiles = names;
    select.replaceChildren(new Option(names.length ? "Select a model" : "No G-code models", ''));
    const list = $('modelList');
    list.replaceChildren();
    names.forEach(filename => {
      select.add(new Option(publicText(filename), filename));
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'model-tile'; button.dataset.filename = filename;
      button.setAttribute('aria-pressed', 'false');
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      icon.setAttribute('aria-hidden', 'true');
      const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
      use.setAttribute('href', '#i-files'); icon.append(use);
      const label = document.createElement('span'); label.textContent = publicText(filename);
      button.append(icon, label);
      button.addEventListener('click', () => {
        if (button.disabled) return;
        select.value = filename; renderControls();
      });
      list.append(button);
    });
    if (names.includes(previous)) select.value = previous;
    if (!names.length) {
      const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = "No G-code models are available."; list.append(empty);
    }
    modelsLoaded = true;
  }
  async function refreshModels() {
    if (!fresh() || pending || modelsPending) return;
    const revision = tokenRevision;
    modelsPending = true; renderControls(); setModelsStatus('Consultando modelos…');
    try {
      const names = modelNames(await api('printer/files'));
      if (revision !== tokenRevision) return;
      renderModels(names); setModelsStatus(names.length + " models · selecting a file does not start a print");
    } catch (error) {
      if (revision === tokenRevision) {
        renderModels([]); modelsLoaded = false;
        setModelsStatus(spanishError(error, "The list could not be loaded."), true);
      }
    } finally { modelsPending = false; renderControls(); }
  }

  async function command(action, allowed, message, body, confirmation, onSuccess) {
    if (!allowed()) return;
    const revision = tokenRevision;
    if (confirmation && !await window.ConsoleShell.confirm(confirmation)) return;
    if (revision !== tokenRevision || !allowed()) return;
    pending = true; statusSequence++; renderControls(); setCommand('Enviando orden…');
    try {
      await api('printer/' + action, {method: 'POST', ...(body === undefined ? {} : {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})});
      if (revision !== tokenRevision) return;
      if (onSuccess) onSuccess();
      setCommand(message);
    } catch (error) {
      if (revision === tokenRevision) setCommand(spanishError(error, "The command could not be sent."), true);
    } finally {
      // A fresh status is required before unlocking another physical action.
      if (revision === tokenRevision) { lastStatus = 0; await status(); }
      pending = false; renderControls();
    }
  }
  function targetNumber(id, label, maximum) {
    const raw = $(id).value.trim().replace(',', '.');
    const value = Number(raw);
    if (!raw || !Number.isFinite(value) || value < 0 || value > maximum) {
      $(id).focus();
      throw localError("Enter a target for " + label + " between 0 and " + maximum + ' °C.');
    }
    return value;
  }
  function applyTemperature() {
    if (!canManualCommand()) return;
    try {
      const extruder = targetNumber('hotendTarget', 'hotend', limits.extruder);
      const bed = targetNumber('bedTarget', "bed", limits.bed);
      void command('temperature', canManualCommand, "Temperature targets accepted.", {extruder, bed}, null, () => {
        targets = {extruder, bed};
        draftDirty.hotendTarget = draftDirty.bedTarget = false;
        setTargetInput('hotendTarget', extruder); setTargetInput('bedTarget', bed);
      });
    } catch (error) { setCommand(spanishError(error, "Check the temperature targets."), true); }
  }
  ['hotendTarget', 'bedTarget'].forEach(id => $(id).addEventListener('input', () => { draftDirty[id] = true; }));
  $('home').addEventListener('click', () => command('home', canManualCommand, 'Home solicitado.', undefined, "Home the axes? Check that the travel path is clear."));
  $('coolAll').addEventListener('click', () => command('cool', canManualCommand, 'Enfriamiento solicitado.', undefined, null, () => {
    draftDirty.hotendTarget = draftDirty.bedTarget = false;
    setTargetInput('hotendTarget', 0); setTargetInput('bedTarget', 0);
  }));
  $('applyHotend').addEventListener('click', applyTemperature);
  $('applyBed').addEventListener('click', applyTemperature);
  $('refreshModels').addEventListener('click', refreshModels);
  $('modelSelect').addEventListener('change', renderControls);
  $('printModel').addEventListener('click', () => {
    const filename = $('modelSelect').value;
    if (!modelFiles.includes(filename) || !isModelFilename(filename)) return;
    void command('start', () => canPrint() && modelFiles.includes(filename), "Print requested.", {filename}, "Print «" + publicText(filename) + '»?');
  });
  ['pause', 'resume', 'cancel'].forEach(action => $(action).addEventListener('click', () => {
    const allowed = () => canTransport() && (action === 'pause' ? printerState === 'printing' : action === 'resume' ? printerState === 'paused' : activePrintStates.has(printerState));
    void command(action, allowed, {pause: 'Pausa solicitada.', resume: "Resume requested.", cancel: "Cancellation requested."}[action], undefined, action === 'cancel' ? "Cancel the current print?" : null);
  }));
  $('refreshCapabilities').addEventListener('click', loadCapabilities);
  $('activatePrinter').addEventListener('click', () => { void activatePrinter(); });
  document.addEventListener('console:activate', () => { void activatePrinter(); });
  $('sensorPermissions').addEventListener('click', () => { void activatePrinter(); });
  $('connectionBadge').addEventListener('click', () => { void activatePrinter(); });
  $('sensorStop').addEventListener('click', () => { void stopSensorCapture(); });
  document.addEventListener('console:view', event => {
    if (event.detail === 'calibration') void loadCapabilities();
    if (event.detail === 'files' && !modelsLoaded) void refreshModels();
  });
  window.addEventListener('offline', () => { statusSequence++; invalidateStatus("No network connection."); });
  window.addEventListener('online', () => { void status(); void loadCapabilities(); void reconnectOnboardingIfReady(); });
  setInterval(() => {
    if (lastStatus && Date.now() - lastStatus >= STALE_MS) invalidateStatus("Data expired. Waiting for a connection.");
    if (capabilitiesAt && Date.now() - capabilitiesAt >= 45000) {
      capabilities = null; capabilitiesAt = 0; applyLimits(); renderCalibration();
    }
    renderControls();
  }, 1000);
  setInterval(loadCapabilities, 30000);

  let camera = null, cameraWanted = false, startingCamera = false;
  let deviceOwner = null;
  const cameraSession = crypto.randomUUID ? crypto.randomUUID() : 'camera_' + Date.now() + '_' + Math.random().toString(36).slice(2);
  let torchTrack = null, torchSupported = false, torchOn = false;
  let torchWarning = '', wakeWarning = '', cameraLastError = null;
  let timer = null, reconnectTimer = null, wakeTimer = null;
  let wake = null, wakePendingTicket = null, generation = 0;
  let reconnectAttempts = 0, wakeAttempts = 0, lastFrameAt = 0;
  let cameraIO = Promise.resolve(), cameraCleanup = Promise.resolve();
  const canvas = document.createElement('canvas');
  const cameraDiagnostic = document.createElement('p');
  cameraDiagnostic.id = 'cameraDiagnostic';
  cameraDiagnostic.className = 'network-status';
  cameraDiagnostic.setAttribute('role', 'status');
  cameraDiagnostic.setAttribute('aria-live', 'polite');
  $('cameraStatus').insertAdjacentElement('afterend', cameraDiagnostic);

  function renderCameraDiagnostic() {
    cameraDiagnostic.textContent = [
      "Keep this page visible; Android may suspend the camera or screen",
      wakeWarning, torchWarning
    ].filter(Boolean).join(' · ');
  }
  function cameraActive(ticket) {
    return cameraWanted && !document.hidden && ticket === generation && Boolean(camera);
  }
  function updateCameraButtons() {
    $('cameraStart').disabled = cameraWanted || startingCamera;
    $('cameraStop').disabled = !cameraWanted && !camera && !startingCamera;
    renderOnboarding();
  }
  function updateTorchButton() {
    const label = torchOn ? "Turn light off" : "Turn light on";
    $('torchLabel').textContent = label;
    $('cameraTorch').setAttribute('aria-label', label);
    $('cameraTorch').setAttribute('aria-pressed', String(torchOn));
    $('cameraTorch').disabled = !camera || !torchSupported;
  }
  function resetTorch() {
    torchTrack = null; torchSupported = false; torchOn = false; torchWarning = '';
    updateTorchButton();
  }
  function detectTorch() {
    torchTrack = camera?.getVideoTracks()[0] || null;
    torchSupported = false; torchOn = false; torchWarning = '';
    try {
      torchSupported = torchTrack?.getCapabilities?.().torch === true && typeof torchTrack.applyConstraints === 'function';
      torchOn = torchTrack?.getSettings?.().torch === true;
    } catch (_) {}
    if (!torchSupported) torchWarning = "This camera has no controllable light.";
    updateTorchButton(); renderCameraDiagnostic();
  }
  async function toggleTorch() {
    const track = torchTrack, ticket = generation;
    if (!cameraActive(ticket) || !torchSupported || !track || $('cameraTorch').disabled) return;
    const next = !torchOn;
    $('cameraTorch').disabled = true;
    try {
      await track.applyConstraints({advanced: [{torch: next}]});
      if (!cameraActive(ticket) || torchTrack !== track) return;
      torchOn = next; torchWarning = '';
    } catch (_) {
      if (!cameraActive(ticket) || torchTrack !== track) return;
      // A transient constraint failure does not remove a supported control.
      torchWarning = "The light could not be changed. You can retry.";
    } finally {
      if (cameraActive(ticket) && torchTrack === track) { updateTorchButton(); renderCameraDiagnostic(); }
    }
  }

  function scheduleWakeRetry(ticket) {
    if (!cameraActive(ticket) || wakeTimer !== null || wakeAttempts >= 3) return;
    const delay = 2000 * (2 ** wakeAttempts++);
    wakeTimer = setTimeout(() => { wakeTimer = null; void acquireWake(ticket); }, delay);
  }
  async function acquireWake(ticket) {
    if (!cameraActive(ticket) || wake || wakePendingTicket === ticket) return;
    if (!navigator.wakeLock?.request) {
      wakeWarning = "Screen wake lock is unavailable.";
      renderCameraDiagnostic(); return;
    }
    wakePendingTicket = ticket;
    try {
      const lock = await navigator.wakeLock.request('screen');
      if (!cameraActive(ticket)) { await lock.release().catch(() => {}); return; }
      wake = lock;
      wakeWarning = '';
      lock.addEventListener('release', () => {
        if (wake !== lock) return;
        wake = null;
        if (!cameraActive(ticket)) return;
        wakeWarning = "Android released the screen wake lock.";
        renderCameraDiagnostic(); scheduleWakeRetry(ticket);
      });
      if (lock.released) {
        wake = null;
        wakeWarning = "Android released the screen wake lock.";
        scheduleWakeRetry(ticket);
      }
    } catch (_) {
      if (cameraActive(ticket)) {
        wakeWarning = "The screen could not be kept awake.";
        scheduleWakeRetry(ticket);
      }
    } finally {
      if (wakePendingTicket === ticket) wakePendingTicket = null;
      if (ticket === generation) renderCameraDiagnostic();
    }
  }

  // Serial PUT/DELETE ordering: a previous cleanup cannot erase a new stream.
  function queueCameraRequest(run) {
    const operation = cameraIO.then(run);
    cameraIO = operation.catch(() => {});
    return operation;
  }
  async function sendFrame(ticket) {
    if (!cameraActive(ticket)) return;
    try {
      const video = $('preview');
      if (video.videoWidth) {
        canvas.width = 640;
        canvas.height = Math.round(640 * video.videoHeight / video.videoWidth);
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        const jpeg = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.7));
        if (!cameraActive(ticket) || !jpeg) return;
        await queueCameraRequest(() => {
          if (!cameraActive(ticket)) return;
          return api('live/frame', {method: 'PUT', headers: {'Content-Type': 'image/jpeg', 'X-KlipperLearn-Client-Version': 'console-25', 'X-KlipperLearn-Camera-Session': cameraSession}, body: jpeg});
        });
        if (!cameraActive(ticket)) return;
        lastFrameAt = Date.now();
        $('cameraStatus').textContent = "Streaming · last image 0 s ago";
      }
    } catch (_) {
      if (cameraActive(ticket)) {
        const age = lastFrameAt ? Math.max(0, Math.floor((Date.now() - lastFrameAt) / 1000)) + ' s' : "no successful upload";
        $('cameraStatus').textContent = "Reconnecting Wi-Fi · last image: " + age;
      }
    } finally {
      if (cameraActive(ticket)) timer = setTimeout(() => { void sendFrame(ticket); }, 1000);
    }
  }

  function stopCamera(preserveWanted = false, message = "Camera off") {
    if (!preserveWanted) { cameraWanted = false; cancelPhotoPair(); }
    generation++;
    startingCamera = false;
    clearTimeout(timer); clearTimeout(reconnectTimer); clearTimeout(wakeTimer);
    timer = reconnectTimer = wakeTimer = null;
    const stream = camera, lock = wake;
    camera = null; wake = null;
    resetTorch();
    if (stream) stream.getTracks().forEach(track => track.stop());
    $('preview').srcObject = null;
    wakeWarning = '';
    $('cameraStatus').textContent = message;
    updateCameraButtons(); renderCameraDiagnostic(); renderOnboarding();
    const release = lock ? lock.release().catch(() => {}) : Promise.resolve();
    const previousCleanup = cameraCleanup;
    const deletion = stream && !preserveWanted ? queueCameraRequest(() => api('live/frame', {method: 'DELETE', headers: {'X-KlipperLearn-Camera-Session': cameraSession}})) : Promise.resolve();
    cameraCleanup = Promise.all([previousCleanup, release, deletion.catch(() => {})]).then(() => {});
    return cameraCleanup;
  }

  function reconnectCamera() {
    void stopCamera(true, "Reconnecting camera…");
    if (!cameraWanted || document.hidden) return;
    if (reconnectAttempts >= 3) {
      void stopCamera(false, "The camera could not recover. Tap Start camera.");
      return;
    }
    const delay = 2000 * (2 ** reconnectAttempts++);
    const ticket = generation;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (cameraWanted && !document.hidden && ticket === generation) void startCamera();
    }, delay);
  }

  async function startCamera({throwOnError = false} = {}) {
    if (!cameraWanted || document.hidden) {
      if (throwOnError) throw localError("Keep this screen visible and tap Connect printer.");
      return false;
    }
    if (camera) return true;
    if (startingCamera) return false;
    startingCamera = true;
    const ticket = ++generation;
    cameraLastError = null;
    updateCameraButtons();
    $('cameraStatus').textContent = "Starting camera…";
    try {
      await cameraCleanup;
      if (!cameraWanted || document.hidden || ticket !== generation) return;
      // getUserMedia has no AbortSignal: discard and stop any late result.
      const stream = await window.KlipperLearnTrialTelemetry.withPermissionTimeout(
        navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: 'environment'}, width: {ideal: 1920}, height: {ideal: 1080}, frameRate: {ideal: 5}}, audio: false}),
        late => late.getTracks().forEach(track => track.stop())
      );
      if (!cameraWanted || document.hidden || ticket !== generation) {
        stream.getTracks().forEach(track => track.stop()); return;
      }
      camera = stream;
      $('preview').srcObject = stream;
      stream.getVideoTracks().forEach(track => track.addEventListener('ended', () => {
        if (cameraActive(ticket)) reconnectCamera();
      }, {once: true}));
      await $('preview').play();
      if (!cameraActive(ticket)) return;
      if (stream.getVideoTracks().some(track => track.readyState === 'ended')) { reconnectCamera(); return; }
      startingCamera = false;
      detectTorch(); updateCameraButtons();
      // A denied or slow wake lock must never hold up image transmission.
      void acquireWake(ticket);
      void sendFrame(ticket);
      schedulePhotoPair(0);
      return true;
    } catch (error) {
      if (ticket !== generation) return;
      const retryLabel = "Connect printer";
      const message = ['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(error?.name)
        ? "Allow camera access in this browser and tap «" + retryLabel + '».'
        : "The camera is unavailable. Use a secure browser and tap «" + retryLabel + '».';
      cameraLastError = localError(message);
      if (throwOnError) {
        await stopCamera(false, message);
        throw cameraLastError;
      }
      if (['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(error?.name)) {
        void stopCamera(false, message);
      } else if (cameraWanted && !document.hidden) reconnectCamera();
      return false;
    } finally {
      if (ticket === generation) { startingCamera = false; updateCameraButtons(); }
    }
  }

  async function verifyOnboardingPrinter() {
    await Promise.all([status(), loadCapabilities()]);
    // Polls may supersede one another; use the latest state, not a discarded return value.
    if (!fresh()) throw localError($('connection').textContent || "The printer is not responding. Check that it is powered on.");
  }
  async function rollbackOnboardingResources(snapshot) {
    if (!snapshot.camera) await stopCamera(false, "Camera stopped.");
    if (!snapshot.sensorArmed) {
      sensorArmed = false;
      ++sensorRevision;
      cancelPhotoPair();
      await stopSensorCollector(false);
      sensorBusy = false;
    }
    renderSensorControls();
  }
  function onboardingErrorMessage(error) {
    if (error?.safe) return error.message;
    if (error?.name === 'NotAllowedError' || error?.name === 'PermissionDeniedError') {
      return "Allow camera, motion and microphone access in this browser, then tap Connect printer.";
    }
    return "Connect KlipperLearn to the printer and tap Connect printer.";
  }
  async function activatePrinter({automatic = false} = {}) {
    if (onboardingBusy || photoPairBusy) return false;
    onboardingBusy = true;
    activationRequested = true;
    const revision = ++onboardingRevision;
    resetOnboardingProgress();
    setOnboardingStatus("Connecting your printer…");
    renderOnboarding();
    try {
      // Permission requests start from this click, independently of printer connectivity.
      // An unanswered native prompt must not block connection to Klipper.
      try {
        if (!peripheralPromise && ensureDeviceOwner().claim({takeover: !automatic})) {
          cameraWanted = true; reconnectAttempts = 0; wakeAttempts = 0;
          setOnboardingStep('permissions', 'active');
          const cameraPromise = startCamera({throwOnError: true}).then(ready => ({ready})).catch(error => ({ready: false, error}));
          const sensorPromise = armSensorsFromGesture({onboarding: true, automatic}).catch(error => ({ok: false, error}));
          peripheralPromise = Promise.all([cameraPromise, sensorPromise]).then(([cameraResult, sensorResult]) => {
            if (revision !== onboardingRevision) return;
            rememberOnboardingPermissions(sensorResult?.report, Boolean(cameraResult.ready && camera));
            const missing = [camera ? '' : "camera", sensorResult?.ok ? sensorResult.warning : 'sensores'].filter(Boolean);
            setOnboardingStep('permissions', missing.length ? 'blocked' : 'done');
            setOnboardingStep('stream', camera ? 'done' : 'blocked');
            if (fresh()) setCommand(missing.length
              ? 'Impresora conectada. ' + missing.join(' · ') + ": permission pending. Tap Connected to retry."
              : "Printer, camera and sensors connected.");
          }).catch(() => { setSensorStatus("Sensor permissions are pending; the printer connection remains available.", true); })
            .finally(() => { peripheralPromise = null; renderOnboarding(); });
        }
      } catch (_) {
        // Optional device ownership/storage failures must not skip connectLocal.
        setOnboardingStep('permissions', 'blocked');
        setSensorStatus("Camera and sensor permissions are pending; the printer connection remains available.", true);
      }
      // The owner explicitly enables one-click access only on their configured LAN.
      await connectLocal();
      await verifyOnboardingPrinter();
      if (revision !== onboardingRevision) return false;
      rememberOnboardingPermissions({permissions: sensorPermissionReport}, Boolean(camera));
      setOnboardingStep('printer', 'done');
      setOnboardingStatus('Impresora conectada.');
      setCommand('Impresora activa.');
      void pollActiveSensorTrial();
      return true;
    } catch (error) {
      if (revision === onboardingRevision) {
        const message = onboardingErrorMessage(error);
        setOnboardingStep('printer', 'blocked');
        setOnboardingStatus(message, true);
        setCommand(message, true);
      }
      return false;
    } finally {
      if (revision === onboardingRevision) {
        onboardingBusy = false;
        renderControls();
      }
    }
  }
  async function reconnectOnboardingIfReady() {
    if (document.hidden || onboardingBusy || photoPairBusy) return;
    if (await permissionsReadyForReconnect()) void activatePrinter({automatic: true});
  }

  function ensureDeviceOwner() {
    if (deviceOwner) return deviceOwner;
    const create = window.KlipperLearnDeviceOwner?.createDeviceOwner;
    if (typeof create !== 'function') throw localError("The device coordinator did not load.");
    deviceOwner = create({onLost: () => {
      ++onboardingRevision;
      onboardingBusy = false;
      void stopCamera(false, "Camera ownership moved to another tab.");
      sensorArmed = false;
      ++sensorRevision;
      cancelPhotoPair();
      void stopSensorCollector(true);
      setOnboardingStatus("Control moved to another KlipperLearn tab.", true);
      renderSensorControls();
    }});
    return deviceOwner;
  }

  $('cameraStart').addEventListener('click', () => {
    void activatePrinter();
  });
  $('cameraStop').addEventListener('click', () => { void stopCamera(); });
  $('cameraTorch').addEventListener('click', toggleTorch);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      if (cameraWanted || camera || startingCamera) void stopCamera(true, "Paused: return to this screen");
      deviceOwner?.release();
    } else if (cameraWanted && !photoPairBusy && !onboardingBusy && ensureDeviceOwner().claim({takeover: false})) {
      wakeAttempts = 0;
      if (camera) void acquireWake(generation);
      else void startCamera();
    }
    if (!document.hidden) void reconnectOnboardingIfReady();
  });
  window.addEventListener('pagehide', () => { deviceOwner?.release(); void stopCamera(); });
  renderCameraDiagnostic();

  renderPairingStatus();
  renderControls();
  setSensorStatus("The Connect printer button enables the camera and sensors.");
  setOnboardingStatus("Tap Connect printer. Choose Allow when the browser asks.");
  renderSensorControls();
  scheduleSensorPoll(0);
  void poll();
  void loadCapabilities();
  void reconnectOnboardingIfReady();
  void retryTelemetryOutbox();
  setInterval(() => { void retryTelemetryOutbox(); }, 10000);
  window.addEventListener('online', () => { void retryTelemetryOutbox(); void reconnectOnboardingIfReady(); });
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.addEventListener('message', event => {
      if (event.data?.type === 'klipperlearn:version') event.ports[0]?.postMessage('25');
    });
    navigator.serviceWorker.register('service-worker.js', {updateViaCache: 'none'})
      .then(registration => registration.update()).catch(() => {});
  }
})();
