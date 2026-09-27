// SPDX-License-Identifier: GPL-3.0-or-later
// Phone sensors through standard browser APIs. Each capability is probed; none is assumed.
// Camera and microphone require HTTPS and user permission. Data stays on the device.

export function sensorSupport() {
  const w = typeof window !== 'undefined' ? window : {};
  return {
    camera: !!navigator.mediaDevices?.getUserMedia,
    microphone: !!navigator.mediaDevices?.getUserMedia && !!(w.AudioContext || w.webkitAudioContext),
    motion: 'DeviceMotionEvent' in w,
    wakeLock: 'wakeLock' in navigator,
  };
}

export class Camera {
  constructor(video) { this.video = video; this.stream = null; }
  async start(facingMode = 'environment') {
    this.stream = await navigator.mediaDevices.getUserMedia({video: {facingMode, width: {ideal: 1280}, height: {ideal: 720}}, audio: false});
    this.video.srcObject = this.stream;
    await this.video.play();
    // Torch helps with repeatable lighting where the phone supports it.
    const track = this.stream.getVideoTracks()[0];
    this.torchSupported = !!track.getCapabilities?.().torch;
  }
  async torch(on) {
    const track = this.stream?.getVideoTracks()[0];
    if (track && this.torchSupported) await track.applyConstraints({advanced: [{torch: !!on}]});
  }
  frame(maxWidth = 960) {
    const v = this.video;
    if (!v.videoWidth) return null;
    const scale = Math.min(1, maxWidth / v.videoWidth);
    const c = document.createElement('canvas');
    c.width = Math.round(v.videoWidth * scale); c.height = Math.round(v.videoHeight * scale);
    const ctx = c.getContext('2d', {willReadFrequently: true});
    ctx.drawImage(v, 0, 0, c.width, c.height);
    return c;
  }
  async snapshot(maxWidth = 960, quality = 0.8) {
    const c = this.frame(maxWidth);
    if (!c) return null;
    return new Promise(r => c.toBlob(b => r(b), 'image/jpeg', quality));
  }
  stop() { this.stream?.getTracks().forEach(t => t.stop()); this.stream = null; }
}

export class Microphone {
  constructor() { this.frames = []; this.running = false; }
  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false}});
    const AC = window.AudioContext || window.webkitAudioContext;
    this.ctx = new AC();
    this.sampleRate = this.ctx.sampleRate;
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    src.connect(this.analyser);
    this.buf = new Float32Array(this.analyser.fftSize);
    this.running = true;
    this.frames = [];
    // Keep ~10 frames/s: enough for loudness and click statistics without storing audio.
    this.timer = setInterval(() => {
      this.analyser.getFloatTimeDomainData(this.buf);
      this.frames.push(Float32Array.from(this.buf));
      if (this.frames.length > 36000) this.frames.shift();
    }, 100);
  }
  level() { if (!this.running) return 0; this.analyser.getFloatTimeDomainData(this.buf); let s = 0; for (const v of this.buf) s += v * v; return Math.sqrt(s / this.buf.length); }
  take() { const f = this.frames; this.frames = []; return f; }
  // Continuous raw samples for the dataset recorder: onBlock(Float32Array, sampleRate, time).
  // AudioWorklet where available, ScriptProcessor as the fallback for older WebViews.
  async tap(onBlock) {
    const src = this.ctx.createMediaStreamSource(this.stream);
    try {
      await this.ctx.audioWorklet.addModule(new URL('./audio-tap.js', import.meta.url));
      this.tapNode = new AudioWorkletNode(this.ctx, 'kl-tap');
      this.tapNode.port.onmessage = e => onBlock(e.data, this.sampleRate, performance.now());
    } catch (_) {
      this.tapNode = this.ctx.createScriptProcessor(4096, 1, 1);
      this.tapNode.onaudioprocess = e => onBlock(Float32Array.from(e.inputBuffer.getChannelData(0)), this.sampleRate, performance.now());
    }
    const sink = this.ctx.createGain(); sink.gain.value = 0;   // keep the graph pulling without playing sound
    src.connect(this.tapNode); this.tapNode.connect(sink); sink.connect(this.ctx.destination);
    if (this.ctx.state === 'suspended') await this.ctx.resume();
  }
  stop() { clearInterval(this.timer); this.running = false; try { this.tapNode?.disconnect(); } catch (_) {} this.stream?.getTracks().forEach(t => t.stop()); this.ctx?.close(); }
}

export class MotionRecorder {
  constructor() { this.samples = []; this.handler = e => this.onMotion(e); this.running = false; }
  async start() {
    // iOS requires an explicit permission request from a user gesture; Android does not.
    if (typeof DeviceMotionEvent !== 'undefined' && typeof DeviceMotionEvent.requestPermission === 'function') {
      const r = await DeviceMotionEvent.requestPermission();
      if (r !== 'granted') throw new Error('Motion permission denied');
    }
    this.samples = [];
    window.addEventListener('devicemotion', this.handler);
    this.running = true;
  }
  onMotion(e) {
    const a = e.acceleration?.x != null ? e.acceleration : e.accelerationIncludingGravity;
    if (!a || a.x == null) return;
    const t = performance.now();
    this.samples.push({t, x: a.x, y: a.y, z: a.z});
    this.onSample?.(t, a.x, a.y, a.z);
    if (this.samples.length > 200000) this.samples.shift();
  }
  mark() { return this.samples.length; }
  since(index) { return this.samples.slice(index); }
  stop() { window.removeEventListener('devicemotion', this.handler); this.running = false; return this.samples; }
}

// Keep the screen on while printing: a suspended tab would stop sending G-code.
export class WakeLock {
  async acquire() { try { this.lock = await navigator.wakeLock?.request('screen'); } catch (_) { this.lock = null; } return !!this.lock; }
  async release() { try { await this.lock?.release(); } catch (_) {} this.lock = null; }
}
