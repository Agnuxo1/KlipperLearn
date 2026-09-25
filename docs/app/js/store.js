// SPDX-License-Identifier: GPL-3.0-or-later
// Local-only persistence (IndexedDB) for printer profiles, trials and photos.
// Nothing leaves the device unless the user exports it.

const DB_NAME = 'klipperlearn-phone';
const STORES = ['profiles', 'trials', 'media', 'kv'];

class MemoryBackend {
  constructor() { this.data = Object.fromEntries(STORES.map(s => [s, new Map()])); }
  async put(store, value, key) { const k = key ?? value.id; this.data[store].set(k, structuredClone(value)); return k; }
  async get(store, key) { const v = this.data[store].get(key); return v === undefined ? undefined : structuredClone(v); }
  async all(store) { return [...this.data[store].values()].map(v => structuredClone(v)); }
  async delete(store, key) { this.data[store].delete(key); }
}

class IdbBackend {
  constructor(db) { this.db = db; }
  static open() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        for (const s of STORES) if (!db.objectStoreNames.contains(s)) db.createObjectStore(s, s === 'kv' || s === 'media' ? undefined : {keyPath: 'id'});
      };
      req.onsuccess = () => resolve(new IdbBackend(req.result));
      req.onerror = () => reject(req.error);
    });
  }
  tx(store, mode, fn) {
    return new Promise((resolve, reject) => {
      const t = this.db.transaction(store, mode);
      const req = fn(t.objectStore(store));
      t.oncomplete = () => resolve(req?.result);
      t.onerror = () => reject(t.error);
    });
  }
  put(store, value, key) { return this.tx(store, 'readwrite', s => (key === undefined ? s.put(value) : s.put(value, key))); }
  get(store, key) { return this.tx(store, 'readonly', s => s.get(key)); }
  all(store) { return this.tx(store, 'readonly', s => s.getAll()); }
  delete(store, key) { return this.tx(store, 'readwrite', s => s.delete(key)); }
}

export async function openStore() {
  try { if (typeof indexedDB !== 'undefined') return new Store(await IdbBackend.open()); } catch (_) {}
  return new Store(new MemoryBackend(), true);
}

export const newId = prefix => `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

export class Store {
  constructor(backend, volatile = false) { this.b = backend; this.volatile = volatile; }
  saveProfile(p) { return this.b.put('profiles', p); }
  profiles() { return this.b.all('profiles'); }
  deleteProfile(id) { return this.b.delete('profiles', id); }
  saveTrial(t) { return this.b.put('trials', t); }
  trial(id) { return this.b.get('trials', id); }
  async trials(printerId) { const all = await this.b.all('trials'); return all.filter(t => !printerId || t.printerId === printerId).sort((a, b) => a.createdAt - b.createdAt); }
  deleteTrial(id) { return this.b.delete('trials', id); }
  saveMedia(key, blob) { return this.b.put('media', blob, key); }
  media(key) { return this.b.get('media', key); }
  setKv(key, value) { return this.b.put('kv', value, key); }
  kv(key) { return this.b.get('kv', key); }

  async exportAll() {
    return {schema: 'klipperlearn.phone-export/v1', exportedAt: new Date().toISOString(),
      profiles: await this.profiles(), trials: await this.trials()};
  }
  async importAll(data) {
    if (data?.schema !== 'klipperlearn.phone-export/v1') throw new Error('Unknown export format');
    for (const p of data.profiles || []) await this.saveProfile(p);
    for (const t of data.trials || []) await this.saveTrial(t);
    return {profiles: (data.profiles || []).length, trials: (data.trials || []).length};
  }
}

// Stable short hash of a G-code program (identifies "the same test part").
export async function hashText(text) {
  if (globalThis.crypto?.subtle) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].slice(0, 8).map(b => b.toString(16).padStart(2, '0')).join('');
  }
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(16);
}
