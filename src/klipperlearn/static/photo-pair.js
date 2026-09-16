/*
 * One-shot Samsung photo-pair client.
 *
 * This module owns only the phone side of the pair workflow. It does not
 * publish a live frame and it does not call printer or companion endpoints.
 * A later UI can use it as:
 *
 *   const capture = KlipperLearnPhotoPair.createPhotoPairController({
 *     token: () => sessionStorage.getItem('klipperlearn-token'),
 *     video: document.querySelector('#photoPreview'),
 *   });
 *   const result = await capture.waitAndCapture();
 *
 * The server queue is intentionally separate: a trusted runner creates a
 * job, this client claims one job, uploads `${job.id}-torch-off.jpg` and
 * `${job.id}-torch-on.jpg`, then closes the job.
 */
(() => {
  'use strict';

  const host = typeof window !== 'undefined' ? window
    : typeof globalThis !== 'undefined' ? globalThis : {};
  const LIGHT_MODES = Object.freeze(['torch-off', 'torch-on']);
  const JOB_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const TRIAL_ID = /^[0-9a-f]{32}$/;
  const DEFAULT_CONSTRAINTS = Object.freeze({
    video: Object.freeze({
      facingMode: Object.freeze({ideal: 'environment'}),
      width: Object.freeze({ideal: 1920}),
      height: Object.freeze({ideal: 1080}),
      frameRate: Object.freeze({ideal: 5}),
    }),
    audio: false,
  });
  const DEFAULTS = Object.freeze({
    apiBase: '/mobile/api',
    pollIntervalMs: 1500,
    waitTimeoutMs: 120000,
    cameraTimeoutMs: 12000,
    operationTimeoutMs: 8000,
    settleMs: 650,
    jpegQuality: 0.92,
    maxImageDimension: 1920,
  });
  const HTTP_MESSAGES = Object.freeze({
    401: "Invalid local authentication token.",
    404: "The capture or experiment does not exist.",
    409: "The capture has finished or both photographs are not available yet.",
    413: "The photograph exceeds the permitted size.",
    415: "The service requires a JPEG photograph.",
    422: "The capture data are invalid.",
    503: "The local service is unavailable.",
  });

  class PhotoPairError extends Error {
    constructor(code, message, cause) {
      super(message);
      this.name = 'PhotoPairError';
      this.code = code;
      if (cause !== undefined) this.cause = cause;
    }
  }

  function throwIfAborted(signal) {
    if (signal?.aborted) throw new PhotoPairError('cancelled', "The capture was cancelled.");
  }

  function stopStream(stream) {
    if (!stream || typeof stream.getTracks !== 'function') return;
    for (const track of stream.getTracks()) {
      try { track.stop?.(); } catch (_) {}
    }
  }

  function finiteInteger(value, fallback, minimum, maximum) {
    const number = Number(value);
    return Number.isFinite(number) && number >= minimum && number <= maximum
      ? Math.floor(number) : fallback;
  }

  function finiteQuality(value) {
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 && number <= 1 ? number : DEFAULTS.jpegQuality;
  }

  function delay(milliseconds, signal) {
    throwIfAborted(signal);
    const duration = Math.max(0, Number(milliseconds) || 0);
    if (!duration) return Promise.resolve();
    return new Promise((resolve, reject) => {
      let timer = setTimeout(done, duration);
      const abort = () => {
        clearTimeout(timer);
        timer = null;
        signal?.removeEventListener?.('abort', abort);
        reject(new PhotoPairError('cancelled', "The capture was cancelled."));
      };
      function done() {
        if (timer === null) return;
        timer = null;
        signal?.removeEventListener?.('abort', abort);
        resolve();
      }
      signal?.addEventListener?.('abort', abort, {once: true});
    });
  }

  function guardedOperation(operation, signal, timeoutMs, timeoutCode, timeoutMessage) {
    let task;
    try {
      task = Promise.resolve().then(operation);
    } catch (error) {
      task = Promise.reject(error);
    }
    return new Promise((resolve, reject) => {
      let settled = false;
      let timer = null;
      const finish = (callback, value) => {
        if (settled) return;
        settled = true;
        if (timer !== null) clearTimeout(timer);
        signal?.removeEventListener?.('abort', abort);
        callback(value);
      };
      const abort = () => finish(reject, new PhotoPairError('cancelled', "The capture was cancelled."));
      task.then(value => finish(resolve, value), error => finish(reject, error));
      if (signal) signal.addEventListener?.('abort', abort, {once: true});
      const duration = Number(timeoutMs);
      if (Number.isFinite(duration) && duration > 0) {
        timer = setTimeout(() => finish(
          reject, new PhotoPairError(timeoutCode, timeoutMessage)
        ), duration);
      }
    });
  }

  function safeId(value, pattern, label) {
    if (typeof value !== 'string' || !pattern.test(value)) {
      throw new PhotoPairError('invalid_job', label + " invalid.");
    }
    return value;
  }

  function normalizeJob(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new PhotoPairError('invalid_job', "The service returned an invalid capture.");
    }
    const id = safeId(value.id ?? value.job_id, JOB_ID, "Capture ID");
    const trialId = safeId(value.trial_id, TRIAL_ID, "Experiment ID");
    if (!['pending', 'running'].includes(value.status)) {
      throw new PhotoPairError('invalid_job', "The capture is unavailable for processing.");
    }
    const expectedNames = LIGHT_MODES.map(mode => `${id}-${mode}.jpg`);
    if (value.photo_names !== undefined) {
      if (!Array.isArray(value.photo_names)
          || value.photo_names.length !== expectedNames.length
          || value.photo_names.some((name, index) => name !== expectedNames[index])) {
        throw new PhotoPairError('invalid_job', "The capture photo list is invalid.");
      }
    }
    return {id, trialId, status: value.status, photoNames: expectedNames, raw: value};
  }

  function unwrap(payload) {
    if (payload && typeof payload === 'object'
        && Object.prototype.hasOwnProperty.call(payload, 'result')) return payload.result;
    return payload;
  }

  function serverError(status) {
    return new PhotoPairError(
      'http_' + status,
      HTTP_MESSAGES[status] || "The capture could not be completed."
    );
  }

  function isPermissionError(error) {
    return ['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(error?.name);
  }

  function failureMessage(error) {
    if (error instanceof PhotoPairError) return error.message;
    if (isPermissionError(error)) return "Camera permission was denied on the phone.";
    return "Automatic capture could not be completed.";
  }

  class PhotoPairController {
    constructor(options = {}) {
      if (!options || typeof options !== 'object' || Array.isArray(options)) {
        throw new TypeError('options must be an object');
      }
      const rawBase = options.apiBase ?? DEFAULTS.apiBase;
      if (typeof rawBase !== 'string' || !rawBase.trim()) {
        throw new TypeError('apiBase must be non-empty text');
      }
      const token = options.token;
      if (typeof token !== 'string' && typeof token !== 'function') {
        throw new TypeError('token must be text or a function');
      }
      const fetcher = options.fetch ?? host.fetch;
      if (typeof fetcher !== 'function') throw new TypeError('fetch is unavailable');
      const navigatorObject = options.navigator ?? host.navigator;
      const mediaDevices = options.mediaDevices ?? navigatorObject?.mediaDevices;
      if (!mediaDevices || typeof mediaDevices.getUserMedia !== 'function') {
        throw new TypeError('mediaDevices.getUserMedia is unavailable');
      }
      this.options = {
        ...DEFAULTS,
        ...options,
        apiBase: rawBase.replace(/\/+$/, ''),
        // Native Window.fetch requires its Window receiver in Chromium/WebKit.
        // Calling it as this.options.fetch otherwise fails before any HTTP request.
        fetch: options.fetch == null ? fetcher.bind(host) : fetcher,
        token,
        mediaDevices,
        cameraTimeoutMs: finiteInteger(options.cameraTimeoutMs, DEFAULTS.cameraTimeoutMs, 1, 300000),
        operationTimeoutMs: finiteInteger(options.operationTimeoutMs, DEFAULTS.operationTimeoutMs, 1, 300000),
        settleMs: finiteInteger(options.settleMs, DEFAULTS.settleMs, 0, 30000),
        pollIntervalMs: finiteInteger(options.pollIntervalMs, DEFAULTS.pollIntervalMs, 0, 300000),
        waitTimeoutMs: finiteInteger(options.waitTimeoutMs, DEFAULTS.waitTimeoutMs, 0, 3600000),
        maxImageDimension: finiteInteger(options.maxImageDimension, DEFAULTS.maxImageDimension, 320, 8192),
        jpegQuality: finiteQuality(options.jpegQuality),
        videoConstraints: options.videoConstraints ?? DEFAULT_CONSTRAINTS,
        document: options.document ?? host.document,
        ImageCapture: options.ImageCapture ?? host.ImageCapture,
      };
      this._video = options.video ?? null;
      this._canvas = options.canvas ?? null;
      this._busy = false;
    }

    _emit(type, values = {}) {
      const callback = this.options.onProgress;
      if (typeof callback !== 'function') return;
      try { callback({type, ...values}); } catch (_) {}
    }

    _token() {
      let value;
      try { value = typeof this.options.token === 'function' ? this.options.token() : this.options.token; }
      catch (_) { throw new PhotoPairError('missing_token', "The local authentication token could not be obtained."); }
      if (typeof value !== 'string' || !value.trim()) {
        throw new PhotoPairError('missing_token', "No local authentication token is configured.");
      }
      return value.trim();
    }

    _url(path) {
      return this.options.apiBase + '/' + String(path).replace(/^\/+/, '');
    }

    async _request(method, path, {body, headers = {}, signal} = {}) {
      throwIfAborted(signal);
      const requestHeaders = {...headers, 'X-KlipperLearn-Token': this._token()};
      const request = {
        method,
        cache: 'no-store',
        headers: requestHeaders,
      };
      if (body !== undefined) request.body = body;
      if (signal) request.signal = signal;
      let response;
      try {
        response = await this.options.fetch(this._url(path), request);
      } catch (error) {
        if (error instanceof PhotoPairError) throw error;
        if (signal?.aborted) throw new PhotoPairError('cancelled', "The capture was cancelled.");
        throw new PhotoPairError('network', "Unable to connect to the local service.", error);
      }
      if (!response || response.ok === false) throw serverError(Number(response?.status) || 0);
      if (response.status === 204 || typeof response.json !== 'function') return null;
      let payload;
      try { payload = await response.json(); }
      catch (error) { throw new PhotoPairError('invalid_response', "The service response is invalid.", error); }
      return unwrap(payload);
    }

    async queue(trialId, {signal} = {}) {
      safeId(trialId, TRIAL_ID, "Experiment ID");
      const result = await this._request('POST', 'photo-pairs', {
        signal,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({trial_id: trialId}),
      });
      return result;
    }

    async claimNext({signal} = {}) {
      const result = await this._request('GET', 'photo-pairs/next', {signal});
      if (result === null || result === undefined) return null;
      const job = normalizeJob(result);
      this._emit('claimed', {job: job.raw});
      return job.raw;
    }

    async waitAndCapture({signal, timeoutMs = this.options.waitTimeoutMs} = {}) {
      const limit = finiteInteger(timeoutMs, this.options.waitTimeoutMs, 0, 3600000);
      const started = Date.now();
      while (true) {
        const result = await this.captureNext({signal});
        if (result !== null) return result;
        const elapsed = Math.max(0, Date.now() - started);
        if (limit === 0 || elapsed >= limit) return null;
        await delay(Math.min(this.options.pollIntervalMs, limit - elapsed), signal);
      }
    }

    async captureNext({signal} = {}) {
      if (this._busy) throw new PhotoPairError('busy', "An automatic capture is already in progress.");
      this._busy = true;
      try {
        const job = await this.claimNext({signal});
        if (!job) return null;
        return await this._captureClaimed(normalizeJob(job), {signal});
      } finally {
        this._busy = false;
      }
    }

    async captureJob(value, {signal} = {}) {
      if (this._busy) throw new PhotoPairError('busy', "An automatic capture is already in progress.");
      const job = normalizeJob(value);
      this._busy = true;
      try {
        return await this._captureClaimed(job, {signal});
      } finally {
        this._busy = false;
      }
    }

    async _captureClaimed(job, {signal} = {}) {
      let stream = null;
      let video = null;
      let lighting = null;
      let failure = null;
      try {
        throwIfAborted(signal);
        video = this._getVideo();
        stream = await this._openCamera(video, signal);
        const track = this._videoTrack(stream);
        lighting = await this._prepareLighting(track, signal);
        this._emit('camera-ready', {job: job.raw, lighting: lighting.kind});
        await this._captureAndUpload(job, video, lighting, signal);
      } catch (error) {
        failure = error;
      } finally {
        try {
          await this._closeCamera(stream, video, lighting);
        } catch (error) {
          if (!failure) failure = error;
        }
      }

      if (failure) {
        const message = failureMessage(failure);
        this._emit('error', {job: job.raw, code: failure.code || 'capture', message});
        try {
          return await this._complete(job.id, message);
        } catch (error) {
          throw new PhotoPairError('completion', "The capture failure could not be recorded.", error);
        }
      }

      const result = await this._complete(job.id, null);
      this._emit('complete', {job: result});
      return result;
    }

    _getVideo() {
      if (!this._video) {
        const documentObject = this.options.document;
        if (!documentObject || typeof documentObject.createElement !== 'function') {
          throw new PhotoPairError('video_unavailable', "No video element is available for capture.");
        }
        this._video = documentObject.createElement('video');
      }
      this._video.autoplay = true;
      this._video.muted = true;
      this._video.playsInline = true;
      return this._video;
    }

    _getCanvas() {
      if (!this._canvas) {
        const documentObject = this.options.document;
        if (!documentObject || typeof documentObject.createElement !== 'function') {
          throw new PhotoPairError('canvas_unavailable', "No capture canvas is available.");
        }
        this._canvas = documentObject.createElement('canvas');
      }
      if (typeof this._canvas.getContext !== 'function' || typeof this._canvas.toBlob !== 'function') {
        throw new PhotoPairError('canvas_unavailable', "This phone cannot prepare JPEG photographs.");
      }
      return this._canvas;
    }

    async _openCamera(video, signal) {
      const acquisition = Promise.resolve().then(() => this.options.mediaDevices.getUserMedia(
        this.options.videoConstraints
      ));
      let stream;
      try {
        stream = await guardedOperation(
          () => acquisition,
          signal,
          this.options.cameraTimeoutMs,
          'camera_timeout',
          "The phone camera did not respond in time."
        );
      } catch (error) {
        acquisition.then(late => stopStream(late), () => {});
        if (error instanceof PhotoPairError) throw error;
        if (isPermissionError(error)) {
          throw new PhotoPairError('camera_permission', "Camera permission was denied on the phone.", error);
        }
        throw new PhotoPairError('camera_unavailable', "The phone camera could not be enabled.", error);
      }
      if (!stream || typeof stream.getVideoTracks !== 'function') {
        stopStream(stream);
        throw new PhotoPairError('camera_unavailable', "The camera did not return valid video.");
      }
      video.srcObject = stream;
      try {
        if (typeof video.play === 'function') await guardedOperation(
          () => video.play(), signal, this.options.cameraTimeoutMs,
          'camera_timeout', "The camera preview did not start in time."
        );
        await this._waitForVideo(video, signal);
      } catch (error) {
        stopStream(stream);
        video.srcObject = null;
        if (error instanceof PhotoPairError) throw error;
        throw new PhotoPairError('camera_unavailable', "The camera preview could not be started.", error);
      }
      if (stream.getVideoTracks().some(track => track?.readyState === 'ended')) {
        stopStream(stream);
        video.srcObject = null;
        throw new PhotoPairError('camera_unavailable', "The phone camera disconnected.");
      }
      return stream;
    }

    async _waitForVideo(video, signal) {
      const deadline = Date.now() + this.options.cameraTimeoutMs;
      while (true) {
        throwIfAborted(signal);
        const width = Number(video.videoWidth);
        const height = Number(video.videoHeight);
        if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) return;
        if (Date.now() >= deadline) {
          throw new PhotoPairError('camera_timeout', "The phone camera did not return an image.");
        }
        await delay(50, signal);
      }
    }

    _videoTrack(stream) {
      const tracks = stream?.getVideoTracks?.() || [];
      const track = tracks[0];
      if (!track || typeof track.stop !== 'function') {
        throw new PhotoPairError('camera_unavailable', "The phone video track was not found.");
      }
      return track;
    }

    async _prepareLighting(track, signal) {
      let capabilities = null;
      try { capabilities = track.getCapabilities?.() || null; } catch (_) {}
      if (capabilities?.torch === true && typeof track.applyConstraints === 'function') {
        let settings = null;
        try { settings = track.getSettings?.() || null; } catch (_) {}
        const known = settings?.torch === true || settings?.torch === false;
        const initialTorch = settings?.torch === true;
        return {
          kind: 'torch',
          track,
          initialTorch,
          initialKnown: known,
          restore: () => this._setTorch(track, initialTorch),
        };
      }

      const factory = this.options.imageCaptureFactory
        || (typeof this.options.ImageCapture === 'function'
          ? currentTrack => new this.options.ImageCapture(currentTrack) : null);
      if (factory) {
        try {
          const imageCapture = await guardedOperation(
            () => factory(track), signal, this.options.operationTimeoutMs,
            'lighting_unavailable', "The camera cannot report its lighting capabilities."
          );
          const photoCapabilities = typeof imageCapture?.getPhotoCapabilities === 'function'
            ? await guardedOperation(
              () => imageCapture.getPhotoCapabilities(), signal, this.options.operationTimeoutMs,
              'lighting_unavailable', "The camera cannot report its lighting capabilities."
            ) : null;
          const modes = Array.isArray(photoCapabilities?.fillLightMode)
            ? photoCapabilities.fillLightMode : [];
          const offMode = modes.includes('off') ? 'off' : modes.includes('none') ? 'none' : null;
          const onMode = modes.includes('flash') ? 'flash' : modes.includes('torch') ? 'torch' : null;
          if (offMode && onMode && typeof imageCapture.takePhoto === 'function') {
            return {kind: 'flash', imageCapture, offMode, onMode, restore: null};
          }
        } catch (error) {
          if (error instanceof PhotoPairError && error.code === 'cancelled') throw error;
        }
      }
      throw new PhotoPairError(
        'lighting_unavailable',
        "This phone cannot control the camera flash or torch."
      );
    }

    async _setTorch(track, desired) {
      if (typeof track?.applyConstraints !== 'function') {
        throw new PhotoPairError('lighting_control', "The camera cannot control its light.");
      }
      const advanced = {advanced: [{torch: Boolean(desired)}]};
      try {
        await guardedOperation(
          () => track.applyConstraints(advanced), null, this.options.operationTimeoutMs,
          'lighting_control', "The phone light could not be changed."
        );
      } catch (firstError) {
        try {
          await guardedOperation(
            () => track.applyConstraints({torch: Boolean(desired)}), null,
            this.options.operationTimeoutMs, 'lighting_control',
            "The phone light could not be changed."
          );
        } catch (secondError) {
          throw new PhotoPairError('lighting_control', "The phone light could not be changed.", secondError);
        }
      }
      await delay(this.options.settleMs);
    }

    async _captureAndUpload(job, video, lighting, signal) {
      for (const mode of LIGHT_MODES) {
        throwIfAborted(signal);
        if (lighting.kind === 'torch') {
          await this._setTorch(lighting.track, mode === 'torch-on');
        }
        this._emit('light-set', {mode, controlled: lighting.kind === 'torch'});
        const photo = lighting.kind === 'torch'
          ? await this._captureVideoFrame(video, signal)
          : await this._captureWithFlash(lighting, mode, signal);
        this._emit('captured', {mode});
        const filename = `${job.id}-${mode}.jpg`;
        await this._request('PUT', `experiments/${encodeURIComponent(job.trialId)}/photos`, {
          signal,
          headers: {
            'Content-Type': 'image/jpeg',
            'X-KlipperLearn-Filename': filename,
          },
          body: photo,
        });
        this._emit('uploaded', {mode, filename});
      }
    }

    async _captureWithFlash(lighting, mode, signal) {
      throwIfAborted(signal);
      let photo;
      try {
        photo = await guardedOperation(
          () => lighting.imageCapture.takePhoto({
            fillLightMode: mode === 'torch-on' ? lighting.onMode : lighting.offMode,
          }), signal, this.options.operationTimeoutMs,
          'capture_failed', "The camera did not provide the photograph."
        );
      } catch (error) {
        if (error instanceof PhotoPairError) throw error;
        throw new PhotoPairError('capture_failed', "The camera did not provide the photograph.", error);
      }
      if (!photo) throw new PhotoPairError('capture_failed', "The camera did not provide the photograph.");
      return photo;
    }

    async _captureVideoFrame(video, signal) {
      throwIfAborted(signal);
      const width = Number(video.videoWidth);
      const height = Number(video.videoHeight);
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
        throw new PhotoPairError('capture_failed', "The phone preview does not contain a valid image.");
      }
      const canvas = this._getCanvas();
      const scale = Math.min(1, this.options.maxImageDimension / width, this.options.maxImageDimension / height);
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      const context = canvas.getContext('2d');
      if (!context || typeof context.drawImage !== 'function') {
        throw new PhotoPairError('canvas_unavailable', "The JPEG photograph could not be prepared.");
      }
      try {
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
      } catch (error) {
        throw new PhotoPairError('capture_failed', "The phone image could not be read.", error);
      }
      const blob = await guardedOperation(
        () => new Promise((resolve, reject) => {
          try {
            canvas.toBlob(value => value ? resolve(value) : reject(new Error('empty jpeg')),
              'image/jpeg', this.options.jpegQuality);
          } catch (error) { reject(error); }
        }), signal, this.options.operationTimeoutMs,
        'capture_failed', "The JPEG photograph could not be prepared."
      );
      if (!blob) throw new PhotoPairError('capture_failed', "The JPEG photograph could not be prepared.");
      return blob;
    }

    async _closeCamera(stream, video, lighting) {
      let restoreError = null;
      try {
        if (lighting?.restore) await lighting.restore();
      } catch (error) {
        restoreError = error instanceof PhotoPairError
          ? error : new PhotoPairError('lighting_restore', "The phone light could not be restored.", error);
      } finally {
        stopStream(stream);
        if (video) {
          try { video.pause?.(); } catch (_) {}
          try { video.srcObject = null; } catch (_) {}
        }
      }
      if (restoreError) {
        throw new PhotoPairError(
          'lighting_restore',
          "Phone lighting could not be restored.",
          restoreError
        );
      }
    }

    async _complete(jobId, error) {
      const body = error === null ? {} : {error: String(error).slice(0, 2048)};
      const result = await this._request('POST', `photo-pairs/${encodeURIComponent(jobId)}/complete`, {
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      return result;
    }
  }

  function createPhotoPairController(options) {
    return new PhotoPairController(options);
  }

  const publicApi = Object.freeze({
    LIGHT_MODES,
    PhotoPairError,
    createPhotoPairController,
  });
  if (host && typeof host === 'object') host.KlipperLearnPhotoPair = publicApi;
  if (typeof module === 'object' && module && module.exports) module.exports = publicApi;
})();
