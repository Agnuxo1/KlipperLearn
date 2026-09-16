/* One visible KlipperLearn tab owns camera/microphone/motion at a time. */
(function(root) {
  'use strict';
  function createDeviceOwner(options = {}) {
    const storage = options.storage || root.localStorage;
    const now = options.now || Date.now;
    const interval = options.setInterval || root.setInterval.bind(root);
    const clear = options.clearInterval || root.clearInterval.bind(root);
    const id = options.id || (root.crypto?.randomUUID?.() || String(Math.random()).slice(2));
    const key = 'klipperlearn-device-owner-v1';
    const ttl = 7000;
    let timer = null, owned = false;
    const channel = Object.prototype.hasOwnProperty.call(options,'channel') ? options.channel : (typeof root.BroadcastChannel === 'function' ? new root.BroadcastChannel('klipperlearn-device-owner') : null);
    function read() {
      try { const value=JSON.parse(storage.getItem(key)||'null'); return value && typeof value.id==='string' && Number.isFinite(value.until) ? value : null; }
      catch (_) { return null; }
    }
    function write() { storage.setItem(key, JSON.stringify({id,until:now()+ttl})); }
    function lose() {
      if (!owned) return;
      owned=false;
      if (timer!==null) clear(timer);
      timer=null;
      options.onLost?.();
    }
    function heartbeat() {
      const current=read();
      if (!owned || (current && current.id!==id && current.until>now())) { lose(); return; }
      try { write(); } catch (_) { lose(); }
    }
    function claim({takeover=false}={}) {
      const current=read();
      if (!takeover && current && current.id!==id && current.until>now()) return false;
      try { write(); } catch (_) { return false; }
      owned=read()?.id===id;
      if (!owned) return false;
      if (timer===null) timer=interval(heartbeat,2000);
      channel?.postMessage({type:'claimed',id});
      return true;
    }
    function release() {
      if (timer!==null) clear(timer);
      timer=null;
      try { if (read()?.id===id) storage.removeItem(key); } catch (_) {}
      owned=false;
    }
    if (channel) channel.onmessage = event => {
      if (event?.data?.type==='claimed' && event.data.id!==id && read()?.id===event.data.id) lose();
    };
    return {claim,release,isOwner:()=>owned,id};
  }
  const api={createDeviceOwner};
  if (typeof module==='object' && module.exports) module.exports=api;
  else root.KlipperLearnDeviceOwner=api;
})(typeof globalThis!=='undefined'?globalThis:this);
