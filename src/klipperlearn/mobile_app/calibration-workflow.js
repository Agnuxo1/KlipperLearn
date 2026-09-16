(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const pairPattern = /^[A-Za-z0-9_-]{24,128}$/;
  function currentToken() {
    const pair = new URLSearchParams(location.hash.slice(1)).get('pair');
    let token = '';
    try { token = pairPattern.test(pair || '') ? pair : localStorage.getItem('klipperlearn-token') || sessionStorage.getItem('klipperlearn-token') || ''; } catch (_) {}
    if (pairPattern.test(pair || '')) {
      try { localStorage.setItem('klipperlearn-token', pair); sessionStorage.setItem('klipperlearn-token', pair); } catch (_) {}
      history.replaceState(null, '', location.pathname + location.search);
    }
    return token;
  }

  const MAX_JPEG_BYTES = 5 * 1024 * 1024;
  const MAX_INPUT_PIXELS = 20 * 1000 * 1000;
  const chartFiles = new Set(['chart.json', 'chart.svg', 'chart.gcode']);
  const cornerIds = [
    ['calibrationTLX', 'calibrationTLY'],
    ['calibrationTRX', 'calibrationTRY'],
    ['calibrationBRX', 'calibrationBRY'],
    ['calibrationBLX', 'calibrationBLY']
  ];
  const inputFields = [
    ['calibrationHotendTemp', 'hotend_temp_c'],
    ['calibrationBedTemp', 'bed_temp_c'],
    ['calibrationLayerHeight', 'layer_height_mm'],
    ['calibrationNozzle', 'nozzle_mm'],
    ['calibrationFilament', 'filament_diameter_mm'],
    ['calibrationLineWidth', 'line_width_mm'],
    ['calibrationPrintSpeed', 'print_speed_mm_s'],
    ['calibrationTravelSpeed', 'travel_speed_mm_s'],
    ['calibrationVolumetric', 'max_volumetric_mm3_s'],
    ['calibrationSize', 'size_mm'],
    ['calibrationOriginX', 'origin_x_mm'],
    ['calibrationOriginY', 'origin_y_mm']
  ];
  const machineLabels = [
    ['bed_width_mm', "Bed X"],
    ['bed_depth_mm', "Bed Y"],
    ['origin_x_mm', 'Origen X'],
    ['origin_y_mm', 'Origen Y'],
    ['max_hotend_temp_c', "Maximum hotend temperature"],
    ['max_bed_temp_c', "Maximum bed temperature"],
    ['max_velocity_mm_s', "Maximum speed"],
    ['nozzle_mm', 'Boquilla'],
    ['filament_diameter_mm', 'Filamento']
  ];

  let machineInfo = null;
  let machinePromise = null;
  let chartId = null;
  let chartBusy = false;
  let downloadBusy = false;
  let photoBase64 = '';
  let photoImage = null;
  let photoGeneration = 0;
  let analyzeBusy = false;
  let adjustmentBusy = false;
  let adjustmentConfirming = false;
  let proposalId = null;

  function localError(message) {
    const error = Error(message);
    error.safe = true;
    return error;
  }

  function safeText(value, fallback = '') {
    let text = value === null || value === undefined ? fallback : String(value);
    const token = currentToken();
    if (token) text = text.split(token).join('[oculto]');
    return text.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').slice(0, 300);
  }

  function statusMessage(error, fallback) {
    if (error && error.safe) return error.message;
    return fallback;
  }

  function setStatus(id, message, error = false) {
    const node = $(id);
    if (!node) return;
    node.textContent = safeText(message);
    node.className = 'network-status' + (error ? ' error' : '');
  }

  async function api(path, options = {}) {
    const token = currentToken();
    if (!token) throw localError("Tap Connect printer in the console to pair this session.");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const headers = {...(options.headers || {}), 'X-KlipperLearn-Token': token};
      const response = await fetch('/mobile/api/' + path, {
        ...options,
        cache: 'no-store',
        signal: controller.signal,
        headers
      });
      if (!response.ok) {
        let detail = '';
        try { detail = (await response.json())?.detail || ''; } catch (_) {}
        const known = {401: "Tap Connect printer to renew the connection.", 404: "Chart or action unavailable.", 409: "The printer is not ready for this action.", 413: "The request is too large.", 422: "Review the specified values.", 503: "The experimental feature is unavailable."};
        const message = response.status === 409 && detail ? safeText(detail) : known[response.status] || "The request could not be completed.";
        throw localError(message);
      }
      return response.status === 204 ? null : await response.json();
    } catch (error) {
      if (error.safe) throw error;
      throw localError(controller.signal.aborted ? "Request timed out. Check the connection." : "Unable to connect to the service.");
    } finally {
      clearTimeout(timeout);
    }
  }

  function numberValue(id, label, {positive = false, nonNegative = false} = {}) {
    const input = $(id);
    const raw = input.value.trim().replace(',', '.');
    const value = Number(raw);
    if (!raw || !Number.isFinite(value) || (positive && value <= 0) || (nonNegative && value < 0)) {
      input.focus();
      throw localError("Enter a valid value for " + label + '.');
    }
    return value;
  }

  function setIfBlank(id, value) {
    const input = $(id);
    if (input && !input.value && Number.isFinite(Number(value))) input.value = String(value);
  }

  function renderMachine(info) {
    machineInfo = info && typeof info === 'object' ? info : null;
    const machine = machineInfo?.machine || machineInfo?.capabilities || {};
    const status = machineInfo?.ready
      ? "Ready · actual configuration retrieved · between prints."
      : machineInfo?.status_message
        ? "Not ready · state error: " + machineInfo.status_message
        : 'No lista · ' + (Array.isArray(machineInfo?.reasons) ? machineInfo.reasons[0] : 'estado desconocido');
    setStatus('calibrationWorkflowStatus', status, !machineInfo?.ready);
    setStatus('adjustmentMachineStatus', status, !machineInfo?.ready);

    const details = $('calibrationWorkflowMachine');
    details.replaceChildren();
    const add = (label, value, suffix = '') => {
      const dt = document.createElement('dt');
      const dd = document.createElement('dd');
      dt.textContent = label;
      dd.textContent = typeof value === 'string'
        ? safeText(value, "Unknown")
        : value === null || value === undefined || !Number.isFinite(Number(value))
          ? "Unknown"
          : Number(value).toFixed(3).replace(/\.000$/, '') + suffix;
      details.append(dt, dd);
    };
    add('Webhooks', machineInfo?.webhooks_state || "Unknown");
    if (machineInfo?.status_message) add("Status message", machineInfo.status_message);
    add("Print status", machineInfo?.printer_state || "Unknown");
    machineLabels.forEach(([key, label]) => add(label, machine[key], key.includes('temp') ? ' °C' : key.includes('velocity') ? ' mm/s' : ' mm'));
    if (machine.nozzle_mm !== undefined) setIfBlank('calibrationNozzle', machine.nozzle_mm);
    if (machine.filament_diameter_mm !== undefined) setIfBlank('calibrationFilament', machine.filament_diameter_mm);

    const width = Number(machine.bed_width_mm);
    const depth = Number(machine.bed_depth_mm);
    const velocity = Number(machine.max_velocity_mm_s);
    const hotendMax = Number(machine.max_hotend_temp_c);
    const bedMax = Number(machine.max_bed_temp_c);
    if (Number.isFinite(width)) $('calibrationSize').max = String(Math.min(width, Number.isFinite(depth) ? depth : width, 1000));
    if (Number.isFinite(width)) $('calibrationOriginX').max = String(Math.max(0, width - Number($('calibrationSize').value || 100)));
    if (Number.isFinite(depth)) $('calibrationOriginY').max = String(Math.max(0, depth - Number($('calibrationSize').value || 100)));
    if (Number.isFinite(velocity)) {
      $('calibrationPrintSpeed').max = String(velocity);
      $('calibrationTravelSpeed').max = String(velocity);
    }
    if (Number.isFinite(hotendMax)) $('calibrationHotendTemp').max = String(hotendMax);
    if (Number.isFinite(bedMax)) $('calibrationBedTemp').max = String(bedMax);
    updateActionStates();
  }

  async function loadMachine(force = false) {
    if (machinePromise && !force) return machinePromise;
    machinePromise = (async () => {
      setStatus('calibrationWorkflowStatus', "Checking actual capabilities…");
      setStatus('adjustmentMachineStatus', "Querying actual state…");
      try {
        const payload = await api('calibration/info');
        renderMachine(payload?.result || null);
        return machineInfo;
      } catch (error) {
        machineInfo = null;
        setStatus('calibrationWorkflowStatus', statusMessage(error, "The machine could not be queried."), true);
        setStatus('adjustmentMachineStatus', statusMessage(error, "The machine could not be queried."), true);
        updateActionStates();
        return null;
      } finally {
        machinePromise = null;
      }
    })();
    return machinePromise;
  }

  function updateActionStates() {
    const ready = machineInfo?.ready === true;
    $('calibrationGenerate').disabled = !ready || chartBusy;
    $('calibrationAnalyze').disabled = analyzeBusy || !chartId || !photoBase64 || !validCorners();
    $('adjustmentPreview').disabled = !ready || adjustmentBusy || adjustmentConfirming;
    $('adjustmentApply').disabled = !ready || adjustmentBusy || adjustmentConfirming || !proposalId;
    $('adjustmentRestore').disabled = !ready || adjustmentBusy || adjustmentConfirming || !proposalId;
  }

  function setTab(name) {
    document.querySelectorAll('[data-workflow-tab]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.workflowTab === name)));
    document.querySelectorAll('[data-workflow-panel]').forEach(panel => { panel.hidden = panel.dataset.workflowPanel !== name; });
  }

  function chartSpecFromForm() {
    const spec = {};
    inputFields.forEach(([id, key]) => {
      spec[key] = numberValue(id, $(id).closest('label').firstChild.textContent, {nonNegative: !['layer_height_mm', 'line_width_mm', 'nozzle_mm', 'filament_diameter_mm', 'print_speed_mm_s', 'travel_speed_mm_s', 'max_volumetric_mm3_s', 'size_mm'].includes(key)});
    });
    ['layer_height_mm', 'line_width_mm', 'nozzle_mm', 'filament_diameter_mm', 'print_speed_mm_s', 'travel_speed_mm_s', 'max_volumetric_mm3_s', 'size_mm'].forEach(key => {
      if (spec[key] <= 0) throw localError("The value of " + key + " must be positive.");
    });
    return spec;
  }

  async function generateChart(event) {
    event.preventDefault();
    if (chartBusy || machineInfo?.ready !== true) return;
    try {
      const spec = chartSpecFromForm();
      chartBusy = true;
      updateActionStates();
      setStatus('calibrationGenerateStatus', "Generating local files…");
      const payload = await api('calibration/charts', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(spec)});
      chartId = typeof payload?.chart_id === 'string' ? payload.chart_id : null;
      if (!chartId) throw localError("The server did not return a valid chart.");
      $('calibrationChartDownloads').hidden = false;
      setStatus('calibrationGenerateStatus', "Chart generated. Download the files; this workflow does not start a print.");
      setTab('analyze');
    } catch (error) {
      setStatus('calibrationGenerateStatus', statusMessage(error, "The chart could not be generated."), true);
    } finally {
      chartBusy = false;
      updateActionStates();
    }
  }

  async function downloadChart(event) {
    const filename = event.currentTarget.dataset.downloadChart;
    if (downloadBusy || !chartId || !chartFiles.has(filename)) return;
    downloadBusy = true;
    event.currentTarget.disabled = true;
    try {
      const token = currentToken();
      if (!token) throw localError("Tap Connect printer in the console to pair this session.");
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      let response;
      try {
        response = await fetch('/mobile/api/calibration/charts/' + encodeURIComponent(chartId) + '/' + filename, {cache: 'no-store', signal: controller.signal, headers: {'X-KlipperLearn-Token': token}});
      } finally {
        clearTimeout(timeout);
      }
      if (!response.ok) throw localError(response.status === 401 ? "Invalid pairing. Reopen the pairing link." : "The file could not be downloaded.");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setStatus('calibrationGenerateStatus', statusMessage(error, "The file could not be downloaded."), true);
    } finally {
      downloadBusy = false;
      event.currentTarget.disabled = false;
    }
  }

  function drawPhoto() {
    const canvas = $('calibrationCanvas');
    if (!photoImage || !canvas.width || !canvas.height) return;
    const context = canvas.getContext('2d');
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(photoImage, 0, 0, canvas.width, canvas.height);
    const points = cornerPointsFromInputs();
    points.forEach((point, index) => {
      if (!point) return;
      context.fillStyle = '#b6f886';
      context.strokeStyle = '#141715';
      context.lineWidth = Math.max(2, canvas.width / 500);
      context.beginPath();
      context.arc(point[0], point[1], Math.max(5, canvas.width / 100), 0, Math.PI * 2);
      context.fill();
      context.stroke();
      context.fillStyle = '#141715';
      context.font = 'bold ' + Math.max(12, canvas.width / 45) + 'px system-ui';
      context.fillText(['TL', 'TR', 'BR', 'BL'][index], point[0] + 7, point[1] - 7);
    });
  }

  function cornerPointsFromInputs() {
    return cornerIds.map(([xId, yId]) => {
      const xRaw = $(xId).value.trim();
      const yRaw = $(yId).value.trim();
      if (!xRaw || !yRaw) return null;
      const point = [Number(xRaw), Number(yRaw)];
      return Number.isFinite(point[0]) && Number.isFinite(point[1]) && point[0] >= 0 && point[1] >= 0 ? point : null;
    });
  }

  function validCorners() {
    const points = cornerPointsFromInputs();
    return points.every(Boolean) && new Set(points.map(point => point.join(':'))).size === 4;
  }

  function writeCorner(index, x, y) {
    if (index < 0 || index >= cornerIds.length) return;
    $(cornerIds[index][0]).value = String(Math.round(x * 100) / 100);
    $(cornerIds[index][1]).value = String(Math.round(y * 100) / 100);
    drawPhoto();
    updateActionStates();
  }

  function resetCorners() {
    cornerIds.forEach(([xId, yId]) => { $(xId).value = ''; $(yId).value = ''; });
  }

  function loadPhoto(event) {
    const generation = ++photoGeneration;
    const file = event.target.files?.[0];
    photoBase64 = '';
    photoImage = null;
    resetCorners();
    $('calibrationCanvas').hidden = true;
    if (!file) { updateActionStates(); return; }
    if (file.type !== 'image/jpeg' && !/\.jpe?g$/i.test(file.name)) {
      setStatus('calibrationAnalyzeStatus', "Select a JPEG photograph.", true);
      updateActionStates();
      return;
    }
    if (file.size > MAX_JPEG_BYTES) {
      setStatus('calibrationAnalyzeStatus', "The JPEG photograph exceeds 5 MiB.", true);
      updateActionStates();
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (generation !== photoGeneration) return;
      if (typeof reader.result !== 'string') return;
      photoBase64 = reader.result;
      const image = new Image();
      image.onload = () => {
        if (generation !== photoGeneration) return;
        if (!image.naturalWidth || !image.naturalHeight || image.naturalWidth * image.naturalHeight > MAX_INPUT_PIXELS) {
          photoBase64 = '';
          photoImage = null;
          $('calibrationCanvas').hidden = true;
          setStatus('calibrationAnalyzeStatus', "The photograph exceeds the permitted resolution.", true);
          updateActionStates();
          return;
        }
        photoImage = image;
        const canvas = $('calibrationCanvas');
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        canvas.hidden = false;
        setStatus('calibrationAnalyzeStatus', "Select TL, TR, BR and BL in that order; coordinates can also be entered manually.");
        drawPhoto();
        updateActionStates();
      };
      image.onerror = () => { if (generation !== photoGeneration) return; photoBase64 = ''; setStatus('calibrationAnalyzeStatus', "The JPEG photograph could not be read.", true); updateActionStates(); };
      image.src = reader.result;
    };
    reader.onerror = () => { if (generation !== photoGeneration) return; photoBase64 = ''; setStatus('calibrationAnalyzeStatus', "The photograph could not be read.", true); updateActionStates(); };
    reader.readAsDataURL(file);
  }

  function canvasPoint(event) {
    const canvas = $('calibrationCanvas');
    const rect = canvas.getBoundingClientRect();
    return [(event.clientX - rect.left) * canvas.width / rect.width, (event.clientY - rect.top) * canvas.height / rect.height];
  }

  async function analyzePhoto() {
    if (analyzeBusy || !chartId || !photoBase64 || !validCorners()) return;
    analyzeBusy = true;
    updateActionStates();
    setStatus('calibrationAnalyzeStatus', "Analyzing the photograph locally…");
    $('calibrationReport').hidden = true;
    $('calibrationHumanReview').hidden = true;
    try {
      const payload = await api('calibration/charts/' + encodeURIComponent(chartId) + '/analyze', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({image_base64: photoBase64, corners_px: cornerPointsFromInputs(), polarity: $('calibrationPolarity').value})});
      const report = payload?.report;
      const reasons = report && (report.unusable_reasons || report.reasons || report.issues);
      const unusable = report && (report.usable_for_review === false || report.usable === false || report.analysis_usable === false || report.status === 'unusable');
      setStatus('calibrationAnalyzeStatus', unusable ? "Analysis is unusable: " + (Array.isArray(reasons) ? reasons.join('; ') : "review the photograph and fiducials.") : "Report received; human review is required.");
      $('calibrationHumanReview').hidden = false;
      $('calibrationReport').textContent = JSON.stringify(report ?? payload, null, 2).slice(0, 12000);
      $('calibrationReport').hidden = false;
    } catch (error) {
      setStatus('calibrationAnalyzeStatus', statusMessage(error, "The photograph could not be analyzed."), true);
    } finally {
      analyzeBusy = false;
      updateActionStates();
    }
  }

  function adjustmentValues() {
    const parameter = $('adjustmentParameter').value;
    const value = numberValue('adjustmentValue', 'valor');
    const minimum = numberValue('adjustmentMin', "minimum bound");
    const maximum = numberValue('adjustmentMax', "maximum bound");
    const maximumStep = numberValue('adjustmentStep', "maximum step", {positive: true});
    if (minimum > maximum || value < minimum || value > maximum) throw localError("The value must be within the specified range.");
    return {parameter, value, bounds: [minimum, maximum], maximum_step: maximumStep};
  }

  function proposalFrom(payload) {
    const result = payload?.result && typeof payload.result === 'object' ? payload.result : payload;
    return {result, id: payload?.proposal_id || result?.proposal_id || result?.id || null};
  }

  async function previewAdjustment(event) {
    event.preventDefault();
    if (adjustmentBusy || machineInfo?.ready !== true) return;
    try {
      const body = adjustmentValues();
      adjustmentBusy = true;
      proposalId = null;
      updateActionStates();
      setStatus('adjustmentStatus', "Preparing a manual preview…");
      const response = await api('calibration/adjustments/preview', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      const proposal = proposalFrom(response);
      if (typeof proposal.id !== 'string' || !proposal.id) throw localError("The server did not return a valid proposal.");
      proposalId = proposal.id;
      $('adjustmentProposalDetails').textContent = JSON.stringify(proposal.result, null, 2).slice(0, 8000);
      $('adjustmentProposalDetails').hidden = false;
      setStatus('adjustmentStatus', "Preview ready. Review the proposal before applying.");
    } catch (error) {
      setStatus('adjustmentStatus', statusMessage(error, "The preview could not be prepared."), true);
    } finally {
      adjustmentBusy = false;
      updateActionStates();
    }
  }

  async function confirmedAdjustment(action) {
    if (adjustmentBusy || adjustmentConfirming || !proposalId || machineInfo?.ready !== true) return;
    if (!window.ConsoleShell || typeof window.ConsoleShell.confirm !== 'function') {
      setStatus('adjustmentStatus', "This interface cannot confirm the manual action.", true);
      return;
    }
    adjustmentConfirming = true;
    updateActionStates();
    let accepted = false;
    try {
      accepted = await window.ConsoleShell.confirm(action === 'apply' ? "Apply this proposal? Only between prints and after human review." : "Restore this proposal? This is a manual action requiring review.");
    } catch (_) {
      accepted = false;
    }
    adjustmentConfirming = false;
    if (!accepted) { updateActionStates(); return; }
    adjustmentBusy = true;
    updateActionStates();
    setStatus('adjustmentStatus', action === 'apply' ? 'Aplicando propuesta confirmada…' : 'Restaurando propuesta confirmada…');
    try {
      const response = await api('calibration/adjustments/' + action, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({proposal_id: proposalId, confirmed: true})});
      const proposal = proposalFrom(response);
      $('adjustmentProposalDetails').textContent = JSON.stringify(proposal.result, null, 2).slice(0, 8000);
      $('adjustmentProposalDetails').hidden = false;
      const expectedStatus = action === 'apply' ? 'applied' : 'restored';
      if (proposal.result?.status !== expectedStatus) {
        setStatus('adjustmentStatus', "The action was not confirmed; returned state: " + safeText(proposal.result?.status || 'desconocido') + '.', true);
      } else {
        setStatus('adjustmentStatus', action === 'apply' ? 'Propuesta aplicada manualmente.' : 'Propuesta restaurada manualmente.');
      }
    } catch (error) {
      setStatus('adjustmentStatus', statusMessage(error, "The manual action could not be completed."), true);
    } finally {
      adjustmentBusy = false;
      updateActionStates();
    }
  }

  document.querySelectorAll('[data-workflow-tab]').forEach(button => button.addEventListener('click', () => setTab(button.dataset.workflowTab)));
  $('calibrationChartForm').addEventListener('submit', generateChart);
  document.querySelectorAll('[data-download-chart]').forEach(button => button.addEventListener('click', downloadChart));
  $('calibrationPhoto').addEventListener('change', loadPhoto);
  $('calibrationCanvas').addEventListener('click', event => {
    if (!photoImage) return;
    const points = cornerPointsFromInputs();
    let index = points.findIndex(point => !point);
    if (index < 0) { resetCorners(); index = 0; }
    const point = canvasPoint(event);
    writeCorner(index, point[0], point[1]);
    setStatus('calibrationAnalyzeStatus', index === 3 ? "Four corners selected; check their order before analysis." : "Select the next corner: " + ['TL', 'TR', 'BR', 'BL'][index + 1] + '.');
  });
  cornerIds.flat().forEach(id => $(id).addEventListener('input', () => { drawPhoto(); updateActionStates(); }));
  $('calibrationSize').addEventListener('input', () => renderMachine(machineInfo || {}));
  $('calibrationAnalyze').addEventListener('click', analyzePhoto);
  $('adjustmentForm').addEventListener('submit', previewAdjustment);
  $('adjustmentApply').addEventListener('click', () => void confirmedAdjustment('apply'));
  $('adjustmentRestore').addEventListener('click', () => void confirmedAdjustment('restore'));
  document.addEventListener('click', event => {
    const opener = event.target.closest('[data-dialog]');
    if (opener?.dataset.dialog === 'calibrationWorkflowDialog' || opener?.dataset.dialog === 'calibrationAdjustmentDialog') void loadMachine(true);
  });
  document.addEventListener('console:view', event => { if (event.detail === 'calibration') void loadMachine(); });
  setTab('generate');
  updateActionStates();
})();
