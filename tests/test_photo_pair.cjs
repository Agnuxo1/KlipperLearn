// Offline browser-contract checks for the independent Samsung pair client.
'use strict';

const assert = require('node:assert/strict');
const {
  LIGHT_MODES,
  PhotoPairError,
  createPhotoPairController,
} = require('../src/klipperlearn/static/photo-pair.js');

const JOB_ID = '11111111-2222-3333-4444-555555555555';
const TRIAL_ID = 'a'.repeat(32);
const JOB = {
  id: JOB_ID,
  job_id: JOB_ID,
  trial_id: TRIAL_ID,
  status: 'running',
  photo_names: LIGHT_MODES.map(mode => `${JOB_ID}-${mode}.jpg`),
};

function response(result, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return {result}; },
  };
}

function harness(options = {}) {
  const requests = [];
  const torchCalls = [];
  let torch = Boolean(options.initialTorch);
  let stopped = false;
  const track = {
    readyState: 'live',
    getCapabilities: () => options.torch === false ? {} : {torch: true},
    getSettings: () => ({torch}),
    applyConstraints: async constraints => {
      const advanced = constraints?.advanced?.[0];
      const desired = advanced?.torch ?? constraints?.torch;
      if (typeof desired !== 'boolean') throw Error('missing torch');
      if (options.failTorch) throw Error('torch failure');
      torch = desired;
      torchCalls.push(desired);
    },
    stop: () => { stopped = true; track.readyState = 'ended'; },
  };
  const stream = {
    getVideoTracks: () => [track],
    getTracks: () => [track],
  };
  const video = {
    videoWidth: 640,
    videoHeight: 480,
    srcObject: null,
    play: async () => {},
    pause: () => {},
  };
  let frameCount = 0;
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({drawImage: () => {}}),
    toBlob: callback => { frameCount++; callback({type: 'image/jpeg', size: 32, frame: frameCount}); },
  };
  const imageModes = [];
  const imageCapture = {
    getPhotoCapabilities: async () => ({fillLightMode: ['off', 'flash']}),
    takePhoto: async ({fillLightMode}) => {
      imageModes.push(fillLightMode);
      return {type: 'image/jpeg', size: 32, fillLightMode};
    },
  };
  let next = options.hasJob === false ? null : {...JOB};
  const completeResults = [];
  const fetch = async (url, init) => {
    requests.push({url, init});
    if (url.endsWith('/photo-pairs/next')) {
      const result = next;
      next = null;
      return response(result);
    }
    if (url.includes('/photos')) {
      const index = requests.filter(item => item.url.includes('/photos')).length;
      if (options.failUploadAt === index) return response(null, 503);
      return response({stored: true});
    }
    if (url.endsWith('/complete')) {
      const payload = JSON.parse(init.body);
      completeResults.push(payload);
      const result = {
        ...JOB,
        status: payload.error ? 'error' : 'complete',
        error: payload.error || null,
      };
      return response(result);
    }
    if (url.endsWith('/photo-pairs')) return response({...JOB, status: 'pending'}, 202);
    throw Error('unexpected URL');
  };
  const controller = createPhotoPairController({
    token: 'test-token',
    fetch,
    mediaDevices: {getUserMedia: async () => stream},
    video,
    canvas,
    settleMs: 0,
    operationTimeoutMs: 100,
    cameraTimeoutMs: 100,
    pollIntervalMs: 0,
    waitTimeoutMs: 20,
    imageCaptureFactory: options.imageCapture ? () => imageCapture : undefined,
    onProgress: options.onProgress,
  });
  return {
    controller,
    requests,
    torchCalls,
    imageModes,
    completeResults,
    video,
    track,
    get stopped() { return stopped; },
    get frameCount() { return frameCount; },
  };
}

(async () => {
  const events = [];
  const normal = harness({onProgress: event => events.push(event)});
  const completed = await normal.controller.captureNext();
  assert.equal(completed.status, 'complete');
  assert.deepEqual(normal.torchCalls, [false, true, false], 'the original torch state is restored');
  assert.equal(normal.stopped, true, 'the camera is stopped after the pair');
  assert.equal(normal.video.srcObject, null);
  assert.equal(normal.frameCount, 2);
  const requestKind = request => request.url.endsWith('/photo-pairs/next') ? 'next'
    : request.url.includes('/photos') ? 'photo'
      : request.url.endsWith('/complete') ? 'complete' : 'other';
  assert.deepEqual(normal.requests.map(request => [request.init.method, requestKind(request)]), [
    ['GET', 'next'],
    ['PUT', 'photo'],
    ['PUT', 'photo'],
    ['POST', 'complete'],
  ]);
  assert.deepEqual(normal.requests.filter(request => request.init.method === 'PUT').map(request => (
    request.init.headers['X-KlipperLearn-Filename']
  )), JOB.photo_names);
  assert.deepEqual(events.filter(event => event.type === 'uploaded').map(event => event.mode), LIGHT_MODES);
  assert.equal(normal.requests[0].init.headers['X-KlipperLearn-Token'], 'test-token');

  const initialOn = harness({initialTorch: true});
  await initialOn.controller.captureJob(JOB);
  assert.deepEqual(initialOn.torchCalls, [false, true, true], 'an initially active torch is restored');

  const failedUpload = harness({initialTorch: true, failUploadAt: 2});
  const failed = await failedUpload.controller.captureNext();
  assert.equal(failed.status, 'error');
  assert.equal(failedUpload.completeResults.length, 1);
  assert.equal(failedUpload.completeResults[0].error, "The local service is unavailable.");
  assert.deepEqual(failedUpload.torchCalls, [false, true, true], 'failure also restores the torch');

  const unsupported = harness({torch: false});
  const unsupportedResult = await unsupported.controller.captureNext();
  assert.equal(unsupportedResult.status, 'error');
  assert.match(unsupportedResult.error, /cannot control/);
  assert.equal(unsupported.requests.filter(request => request.init.method === 'PUT').length, 0);
  assert.equal(unsupported.stopped, true);

  const flash = harness({torch: false, imageCapture: true});
  const flashResult = await flash.controller.captureNext();
  assert.equal(flashResult.status, 'complete');
  assert.deepEqual(flash.imageModes, ['off', 'flash']);
  assert.equal(flash.requests.filter(request => request.init.method === 'PUT').length, 2);

  const noJob = harness({hasJob: false});
  assert.equal(await noJob.controller.captureNext(), null);
  assert.equal(await noJob.controller.waitAndCapture({timeoutMs: 0}), null);

  assert.throws(
    () => createPhotoPairController({token: 'x', fetch: async () => response(null), mediaDevices: {}}),
    error => error instanceof TypeError && /getUserMedia/.test(error.message)
  );
  assert.equal(new PhotoPairError('test', 'test').name, 'PhotoPairError');
  console.log('PASS: Samsung torch pair, restoration, failure reporting, ImageCapture fallback and idle queue.');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
