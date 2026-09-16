'use strict';
// Real IndexedDB in an isolated headless browser; never visits the printer.
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
(async () => {
  const channel=process.env.KL_TEST_BROWSER_CHANNEL;
  const browser = await chromium.launch({...(channel?{channel}:{}),headless:true});
  try {
    const context = await browser.newContext();
    await context.route('http://localhost:8766/**', route => route.fulfill({contentType:'text/html',body:'<!doctype html><title>Outbox regression</title>'}));
    const page = await context.newPage();
    const load = async () => {
      await page.goto('http://localhost:8766/');
      await page.addScriptTag({path:require.resolve('../src/klipperlearn/mobile_app/telemetry-outbox.js')});
    };
    await load();
    const first = await page.evaluate(async () => {
      let ack = 0;
      const queue = KlipperLearnTelemetryOutbox.createOutbox({send:async () => {throw Error('offline');}});
      await queue.enqueue('pair-a',{trial_id:'persisted-trial',samples:{motion:[{t_ms:12}]}},() => ack++);
      await queue.enqueue('pair-b',{trial_id:'other-printer'});
      try {await queue.flush('pair-a');} catch (_) {}
      return ack;
    });
    assert.equal(first,1);
    await load(); // Destroy page state, keep only committed browser storage.
    const result = await page.evaluate(async () => {
      const delivered=[];
      const queue=KlipperLearnTelemetryOutbox.createOutbox({send:async payload => delivered.push(payload)});
      await Promise.all([queue.flush('pair-a'),queue.flush('pair-a')]);
      await queue.flush('pair-a');
      const pending = await KlipperLearnTelemetryOutbox.indexedStore(indexedDB).first('pair-b');
      return {delivered,pending};
    });
    assert.equal(result.delivered.length,1);
    assert.equal(result.delivered[0].samples.motion[0].t_ms,12);
    assert.equal(result.pending.payload.trial_id,'other-printer');
    console.log('real IndexedDB reload/retry/isolation: PASS');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
