'use strict';
const assert = require('node:assert/strict');
const {createOutbox} = require('../src/klipperlearn/mobile_app/telemetry-outbox.js');
(async () => {
  const rows = new Map();let sequence = 0, online = false, acknowledgements = 0;
  const sent = [];
  const store = {
    async put(value) {const id = ++sequence;rows.set(id, structuredClone({...value,id}));},
    async first(scope) {return [...rows.values()].find(row => row.scope === scope);},
    async remove(id) {rows.delete(id);},
  };
  const send = async payload => {if (!online) throw Error('offline');sent.push(payload.trial_id);};
  let queue = createOutbox({store,send});
  await queue.enqueue('printer-a',{trial_id:'a'},() => acknowledgements++);
  await queue.enqueue('printer-b',{trial_id:'b'});
  assert.equal(acknowledgements,1);
  await assert.rejects(queue.flush('printer-a'),/offline/);
  assert.equal(rows.size,2);
  queue = createOutbox({store,send}); // Reload: persisted requests remain.
  online = true;
  await Promise.all([queue.flush('printer-a'),queue.flush('printer-a')]);
  assert.deepEqual(sent,['a']);
  assert.equal(rows.size,1, 'a different pairing must never receive old data');
  const failedStore = {...store, async put() {throw Error('quota');}};
  const full = createOutbox({store:failedStore,send});
  await assert.rejects(full.enqueue('printer-a',{trial_id:'c'},() => acknowledgements++),/quota/);
  assert.equal(acknowledgements,1,'never release capture buffers before commit');
  await queue.flush('printer-b');
  assert.deepEqual(sent,['a','b']);
  console.log('durable telemetry queue: PASS');
})().catch(error => {console.error(error);process.exitCode=1;});
