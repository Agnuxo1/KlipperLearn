/* Durable local queue. No credentials, raw audio or printer commands stored. */
(function(root) {
  'use strict';
  function indexedStore(indexedDB) {
    let opening;
    function database() {
      if (!indexedDB) return Promise.reject(Error("The browser cannot store sensor data offline."));
      if (!opening) opening = new Promise((resolve, reject) => {
        const request = indexedDB.open('klipperlearn-telemetry-outbox', 1);
        request.onupgradeneeded = () => {
          const store = request.result.createObjectStore('pending', {keyPath: 'id', autoIncrement: true});
          store.createIndex('scope', 'scope');
        };
        request.onerror = () => {opening = null;reject(request.error);};
        request.onblocked = () => {opening = null;reject(Error("Close the other KlipperLearn tabs to save sensor data."));};
        request.onsuccess = () => {
          const db = request.result;
          db.onversionchange = () => {db.close();opening = null;};
          resolve(db);
        };
      });
      return opening;
    }
    async function transaction(mode, operation) {
      const db = await database();
      return new Promise((resolve, reject) => {
        const tx = db.transaction('pending', mode);
        let request;
        try {request = operation(tx.objectStore('pending'));} catch(error) {tx.abort();reject(error);return;}
        // Request success is not enough: wait for durable transaction commit.
        tx.oncomplete = () => resolve(request.result);
        tx.onabort = tx.onerror = () => reject(tx.error || Error("Sensor data could not be saved on this device."));
      });
    }
    return {
      put: value => transaction('readwrite', store => store.add(value)),
      first: async scope => (await transaction('readonly', store => store.index('scope').getAll(scope, 1)))[0],
      remove: id => transaction('readwrite', store => store.delete(id)),
    };
  }
  function createOutbox({store = indexedStore(root.indexedDB), send}) {
    const active = new Map();
    async function enqueue(scope, payload, acknowledged = () => {}) {
      if (typeof scope !== 'string' || !scope || !payload?.trial_id) throw Error("Sensor upload has no identity.");
      await store.put({scope, payload});
      acknowledged();
    }
    function flush(scope) {
      if (active.has(scope)) return active.get(scope);
      const operation = (async () => {
        let delivered = 0;
        // Bound each pass so an old backlog cannot monopolise the connection.
        for (; delivered < 20; delivered++) {
          const item = await store.first(scope);
          if (!item) break;
          await send(item.payload, scope);
          await store.remove(item.id);
        }
        return delivered;
      })();
      active.set(scope, operation);
      operation.then(() => active.delete(scope), () => active.delete(scope));
      return operation;
    }
    return {enqueue, flush};
  }
  const api = {createOutbox, indexedStore};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.KlipperLearnTelemetryOutbox = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
