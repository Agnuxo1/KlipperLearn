// SPDX-License-Identifier: GPL-3.0-or-later
// Line-oriented serial connections: Web Serial (desktop Chrome/Edge), WebUSB (Chrome on
// Android via usb-drivers.js) and an in-page simulator. All expose the same interface:
//   await conn.open(); await conn.writeLine('M115'); conn.onLine = line => ...; await conn.close();
import {KNOWN_USB_FILTERS, pickDriver, driverName} from './usb-drivers.js';

const enc = new TextEncoder();

export class LineSplitter {
  constructor(onLine) { this.buf = ''; this.onLine = onLine; this.dec = new TextDecoder(); }
  push(bytes) {
    this.buf += typeof bytes === 'string' ? bytes : this.dec.decode(bytes, {stream: true});
    let i;
    while ((i = this.buf.search(/\r?\n/)) >= 0) {
      const line = this.buf.slice(0, i).replace(/\r$/, '');
      this.buf = this.buf.slice(this.buf[i] === '\r' ? i + 2 : i + 1);
      if (line.length) this.onLine(line);
    }
    if (this.buf.length > 8192) { this.onLine(this.buf); this.buf = ''; }
  }
}

class BaseConnection {
  constructor() { this.onLine = () => {}; this.onClose = () => {}; this.label = ''; this.open_ = false; }
  get isOpen() { return this.open_; }
  async writeLine(line) { await this.writeRaw(enc.encode(line + '\n')); }
}

export class WebSerialConnection extends BaseConnection {
  static supported() { return typeof navigator !== 'undefined' && 'serial' in navigator; }
  async open(baud) {
    this.port = await navigator.serial.requestPort();
    await this.port.open({baudRate: baud, bufferSize: 65536});
    const info = this.port.getInfo();
    this.label = `Web Serial ${info.usbVendorId ? info.usbVendorId.toString(16) + ':' + info.usbProductId.toString(16) : ''}`.trim();
    this.writer = this.port.writable.getWriter();
    this.open_ = true;
    this.readLoop();
  }
  async readLoop() {
    const split = new LineSplitter(l => this.onLine(l));
    try {
      while (this.open_ && this.port.readable) {
        this.reader = this.port.readable.getReader();
        try {
          for (;;) { const {value, done} = await this.reader.read(); if (done) break; if (value) split.push(value); }
        } finally { this.reader.releaseLock(); }
      }
    } catch (e) { this.onLine('!! ' + e.message); }
    if (this.open_) { this.open_ = false; this.onClose(); }
  }
  async writeRaw(bytes) { await this.writer.write(bytes); }
  async close() {
    this.open_ = false;
    try { await this.reader?.cancel(); } catch (_) {}
    try { this.writer?.releaseLock(); } catch (_) {}
    try { await this.port?.close(); } catch (_) {}
    this.onClose();
  }
}

export class WebUsbConnection extends BaseConnection {
  static supported() { return typeof navigator !== 'undefined' && 'usb' in navigator; }
  async open(baud, device) {
    this.device = device || await navigator.usb.requestDevice({filters: KNOWN_USB_FILTERS});
    this.driver = pickDriver(this.device);
    this.label = `USB ${driverName(this.device)} ${this.device.productName || ''}`.trim();
    await this.driver.open(baud);
    this.open_ = true;
    this.readLoop();
  }
  async readLoop() {
    const split = new LineSplitter(l => this.onLine(l));
    while (this.open_) {
      try { const bytes = await this.driver.read(); if (bytes.length) split.push(bytes); }
      catch (e) { if (this.open_) this.onLine('!! ' + e.message); break; }
    }
    if (this.open_) { this.open_ = false; this.onClose(); }
  }
  async writeRaw(bytes) {
    for (let i = 0; i < bytes.length; i += 64) await this.driver.write(bytes.subarray(i, i + 64));
  }
  async close() { this.open_ = false; await this.driver?.close(); this.onClose(); }
}

export class SimulatedConnection extends BaseConnection {
  constructor(sim) { super(); this.sim = sim; this.label = 'Simulator'; }
  async open() {
    this.sim.emit = line => queueMicrotask(() => this.open_ && this.onLine(line));
    this.open_ = true;
    this.sim.boot();
  }
  async writeRaw(bytes) { for (const line of new TextDecoder().decode(bytes).split('\n')) if (line) this.sim.receive(line); }
  async close() { this.open_ = false; this.sim.stop?.(); this.onClose(); }
}

export function transportSupport() {
  return {webSerial: WebSerialConnection.supported(), webUsb: WebUsbConnection.supported(),
    secure: typeof window === 'undefined' || window.isSecureContext};
}

// Preferred real transport: Web Serial where available (handles OS drivers), else WebUSB.
export function createConnection(kind, sim) {
  if (kind === 'sim') return new SimulatedConnection(sim);
  if (kind === 'serial') return new WebSerialConnection();
  if (kind === 'usb') return new WebUsbConnection();
  if (WebSerialConnection.supported()) return new WebSerialConnection();
  if (WebUsbConnection.supported()) return new WebUsbConnection();
  throw new Error('This browser has neither Web Serial nor WebUSB. Use Chrome on Android or desktop Chrome/Edge.');
}
