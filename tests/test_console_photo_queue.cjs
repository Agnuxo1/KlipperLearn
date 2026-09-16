'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../src/klipperlearn/mobile_app/console.js'), 'utf8');
const worker=fs.readFileSync(require.resolve('../src/klipperlearn/mobile_app/service-worker.js'),'utf8');
const html=fs.readFileSync(require.resolve('../src/klipperlearn/mobile_app/console.html'),'utf8');
const version=html.match(/console\.js\?v=(\d+)/)[1];
assert(source.includes(`postMessage('${version}')`),'Client version handshake must match the served asset');
assert(worker.includes(`event.data === '${version}'`),'Worker must recognize the current client');
assert(source.includes(`'X-KlipperLearn-Client-Version': 'console-${version}'`),'Live stream version must identify the actual asset');
const body = source.slice(source.indexOf('  async function processPhotoPairQueue()'), source.indexOf('  function setCommand('));

async function run(job, failCapture = false, overrides = {}) {
  const events = [];
  const context = {
    sensorArmed: false, sensorActiveTrialId: null, photoPairBusy: false, printerState: 'complete',
    currentToken: () => 'test-token', fresh: () => true,
    document: {hidden: false}, onboardingBusy: false, camera: {}, cameraWanted: true,
    startingCamera: false, photoPairAbort: null, AbortController,
    renderSensorControls() {}, setPhotoPairStatus() {},
    schedulePhotoPair() {events.push('schedule');},
    async stopCamera() {events.push('stop');context.camera = null;},
    async startCamera() {assert.equal(context.photoPairBusy, false);events.push('restart');},
    ensurePhotoPairController() {return {
      async claimNext() {events.push('claim');return job;},
      async captureJob(actual) {
        assert.equal(actual, job);events.push('capture');
        if (failCapture) throw Error('camera disconnected');
        return {};
      },
    };},
    ...overrides,
  };
  vm.createContext(context);
  vm.runInContext(body, context);
  await context.processPhotoPairQueue();
  assert.equal(context.photoPairBusy, false);
  assert.equal(context.photoPairAbort, null);
  return events;
}
(async () => {
  assert.deepEqual(await run(null), ['claim','schedule']);
  assert.deepEqual(await run({id:'job'}), ['claim','stop','capture','restart','schedule']);
  assert.deepEqual(await run({id:'job'}, true), ['claim','stop','capture','restart','schedule']);
  for (const overrides of [{fresh: () => false}, {currentToken: () => ''},
    {printerState: 'printing'}, {cameraWanted: false}, {document: {hidden: true}}]) {
    assert.deepEqual(await run({id:'job'}, false, overrides), ['schedule']);
  }
  console.log('console photo queue: PASS');
})().catch(error => {console.error(error);process.exitCode=1;});
