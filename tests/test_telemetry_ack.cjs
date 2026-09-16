const assert = require('node:assert/strict');
const {createTrialTelemetry} = require('../src/klipperlearn/static/trial-telemetry.js');
(async () => {
  const env = {isSecureContext:true, DeviceMotionEvent:function(){}, DeviceOrientationEvent:function(){}, addEventListener(){}, removeEventListener(){}};
  const collector = createTrialTelemetry({trialId:'test-ack', environment:env, eventTarget:env});
  await collector.requestPermissions({motion:true, orientation:false, audio:false});
  await collector.start();
  collector.recordMotion({acceleration:{x:1,y:2,z:3}});
  const sent = collector.snapshot();
  assert.equal(sent.samples.motion.length, 1);
  collector.recordMotion({acceleration:{x:4,y:5,z:6}});
  collector.acknowledge(sent);
  assert.equal(collector.snapshot().samples.motion.length, 1);
  collector.acknowledge(sent);
  assert.equal(collector.snapshot().samples.motion.length, 1, 'retry must not remove new evidence');
  await collector.stop();
  console.log('telemetry acknowledgement: PASS');
})().catch(e => { console.error(e); process.exitCode=1; });
