// SPDX-License-Identifier: GPL-3.0-or-later
// Signal analysis for phone sensors. Pure functions; no DOM access.
// Results are indicators for comparing trials on the same setup, not calibrated measurements.

export function nextPow2(n) { let p = 1; while (p < n) p <<= 1; return p; }

// In-place iterative radix-2 FFT. re/im are Float64Arrays of equal power-of-two length.
export function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = -2 * Math.PI / len;
    const wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const a = i + k, b = a + len / 2;
        const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
        const ncr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = ncr;
      }
    }
  }
}

export function detrend(x) {
  const n = x.length;
  if (n < 2) return Float64Array.from(x);
  let sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (let i = 0; i < n; i++) { sx += i; sy += x[i]; sxx += i * i; sxy += i * x[i]; }
  const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx), icpt = (sy - slope * sx) / n;
  return Float64Array.from(x, (v, i) => v - (icpt + slope * i));
}

// Power spectrum with a Hann window. Returns {freqs, power} up to Nyquist.
export function powerSpectrum(signal, sampleRate) {
  const x = detrend(signal);
  const n = nextPow2(x.length);
  const re = new Float64Array(n), im = new Float64Array(n);
  for (let i = 0; i < x.length; i++) re[i] = x[i] * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / (x.length - 1)));
  fft(re, im);
  const half = n / 2;
  const freqs = new Float64Array(half), power = new Float64Array(half);
  for (let k = 0; k < half; k++) { freqs[k] = k * sampleRate / n; power[k] = re[k] ** 2 + im[k] ** 2; }
  return {freqs, power};
}

// Dominant frequency with parabolic interpolation, ignoring bins below minFreq.
export function dominantFrequency(signal, sampleRate, minFreq = 0) {
  const {freqs, power} = powerSpectrum(signal, sampleRate);
  let best = -1;
  for (let k = 1; k < power.length - 1; k++) if (freqs[k] >= minFreq && (best < 0 || power[k] > power[best])) best = k;
  if (best < 1) return null;
  const a = power[best - 1], b = power[best], c = power[best + 1];
  const shift = (a - 2 * b + c) !== 0 ? 0.5 * (a - c) / (a - 2 * b + c) : 0;
  const binHz = freqs[1] - freqs[0];
  let total = 0; for (let k = 1; k < power.length; k++) total += power[k];
  return {freq: freqs[best] + shift * binHz, prominence: total ? b / total : 0};
}

export function rms(x) { let s = 0; for (const v of x) s += v * v; return x.length ? Math.sqrt(s / x.length) : 0; }
export function median(arr) { const s = [...arr].sort((a, b) => a - b); const m = s.length >> 1; return s.length ? (s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2) : 0; }

// Accelerometer samples [{t (ms), x, y, z}] recorded from DeviceMotion events.
export function analyzeMotion(samples, {minFreq = 5} = {}) {
  if (samples.length < 64) return {ok: false, reason: 'too_few_samples', samples: samples.length};
  const dts = [];
  for (let i = 1; i < samples.length; i++) dts.push(samples[i].t - samples[i - 1].t);
  const dt = median(dts);
  const rate = 1000 / dt;
  const jitter = median(dts.map(d => Math.abs(d - dt))) / dt;
  const axes = {};
  for (const ax of ['x', 'y', 'z']) {
    const sig = samples.map(s => s[ax] || 0);
    const peak = dominantFrequency(sig, rate, minFreq);
    axes[ax] = {rms: rms(detrend(sig)), peakHz: peak ? peak.freq : null, prominence: peak ? peak.prominence : 0};
  }
  return {ok: true, sampleRateHz: rate, nyquistHz: rate / 2, jitter, axes,
    warning: rate < 150 ? 'low_sample_rate' : null};
}

// Amplitude response while the app drives the printer at known excitation frequencies.
// Works even when the phone samples below Nyquist: RMS energy survives aliasing.
export function resonanceFromSweep(segments) {
  const pts = segments.filter(s => s.samples.length >= 8).map(s => {
    const energy = ['x', 'y', 'z'].reduce((acc, ax) => acc + rms(detrend(s.samples.map(v => v[ax] || 0))) ** 2, 0);
    return {freq: s.freq, amplitude: Math.sqrt(energy)};
  });
  if (pts.length < 3) return {ok: false, points: pts};
  let best = 0;
  for (let i = 1; i < pts.length; i++) if (pts[i].amplitude > pts[best].amplitude) best = i;
  const base = median(pts.map(p => p.amplitude));
  return {ok: true, points: pts, peakHz: pts[best].freq, peakRatio: base ? pts[best].amplitude / base : 0};
}

// Audio: frames of Float32 PCM. Returns loudness, spectral centroid and transient ("click") rate.
export function analyzeAudio(frames, sampleRate) {
  if (!frames.length) return {ok: false};
  const energies = frames.map(f => rms(f));
  const med = median(energies) || 1e-9;
  let clicks = 0;
  for (let i = 1; i < energies.length; i++) if (energies[i] > 4 * med && energies[i] > 2 * energies[i - 1]) clicks++;
  let centroidSum = 0;
  const sampleFrames = frames.filter((_, i) => i % Math.max(1, Math.floor(frames.length / 32)) === 0);
  for (const f of sampleFrames) {
    const {freqs, power} = powerSpectrum(f, sampleRate);
    let num = 0, den = 0;
    for (let k = 1; k < power.length; k++) { num += freqs[k] * power[k]; den += power[k]; }
    centroidSum += den ? num / den : 0;
  }
  const seconds = frames.reduce((a, f) => a + f.length, 0) / sampleRate;
  return {ok: true, rms: rms(energies), medianRms: med, clicksPerMin: seconds ? clicks / seconds * 60 : 0,
    centroidHz: centroidSum / sampleFrames.length, seconds};
}

// Image helpers operate on {width, height, data: RGBA Uint8ClampedArray} (ImageData-like).
export function toGray(img) {
  const g = new Float64Array(img.width * img.height);
  for (let i = 0, j = 0; i < g.length; i++, j += 4) g[i] = 0.299 * img.data[j] + 0.587 * img.data[j + 1] + 0.114 * img.data[j + 2];
  return g;
}

// Variance of the Laplacian: a focus/texture indicator. Only compare photos taken the same way.
export function sharpness(img) {
  const g = toGray(img), w = img.width, h = img.height;
  let sum = 0, sum2 = 0, n = 0;
  for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
    const i = y * w + x;
    const lap = 4 * g[i] - g[i - 1] - g[i + 1] - g[i - w] - g[i + w];
    sum += lap; sum2 += lap * lap; n++;
  }
  return n ? sum2 / n - (sum / n) ** 2 : 0;
}

// Ringing along a printed wall. roi = {x, y, w, h} in pixels over a horizontal strip of the
// wall just after a corner; mmPerPx converts to millimetres (e.g. known wall length / pixels).
export function analyzeRinging(img, roi, {mmPerPx = null, speedMmS = null} = {}) {
  const g = toGray(img), W = img.width;
  const profile = new Float64Array(roi.w);
  for (let x = 0; x < roi.w; x++) {
    let s = 0;
    for (let y = 0; y < roi.h; y++) s += g[(roi.y + y) * W + roi.x + x];
    profile[x] = s / roi.h;
  }
  const flat = detrend(profile);
  const amplitude = rms(flat);
  const mean = profile.reduce((a, b) => a + b, 0) / profile.length || 1;
  const peak = dominantFrequency(flat, 1, 2 / roi.w);        // cycles per pixel
  const periodPx = peak && peak.freq > 0 ? 1 / peak.freq : null;
  const out = {amplitude, contrast: amplitude / mean, periodPx, prominence: peak ? peak.prominence : 0};
  if (periodPx && mmPerPx) {
    out.wavelengthMm = periodPx * mmPerPx;
    if (speedMmS) out.frequencyHz = speedMmS / out.wavelengthMm;
  }
  return out;
}
