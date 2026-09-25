// SPDX-License-Identifier: GPL-3.0-or-later
// USB serial drivers for WebUSB (Chrome on Android has WebUSB but no wired Web Serial).
// Each driver opens a claimed USB device as a byte stream at a given baud rate.
// Protocol details follow the Linux kernel drivers cdc-acm, ch341, cp210x and ftdi_sio.

export const KNOWN_USB_FILTERS = [
  {vendorId: 0x1a86},                    // WCH CH340/CH341 (Anycubic, Creality 8-bit, Anet...)
  {vendorId: 0x10c4},                    // Silicon Labs CP210x (older Creality/Prusa i3 clones)
  {vendorId: 0x0403},                    // FTDI FT232 (older RAMPS/Rambo, Ultimaker)
  {vendorId: 0x2341}, {vendorId: 0x2a03}, // Arduino Mega (16U2 CDC-ACM)
  {vendorId: 0x1d50},                    // OpenMoko ids used by Marlin/Klipper USB
  {vendorId: 0x0483},                    // STM32 CDC (32-bit boards)
  {vendorId: 0x2c99},                    // Prusa Research
  {vendorId: 0x1fc9},                    // NXP LPC (SKR 1.x)
  {vendorId: 0x2e8a},                    // RP2040
  {classCode: 0x02},                     // any CDC communications device
];

// ---------- CH340/CH341 baud-rate encoding (port of linux/drivers/usb/serial/ch341.c) ----------
const CH341_CLKRATE = 48000000;
const clkDiv = (ps, fact) => 1 << (12 - 3 * ps - fact);
const minRate = ps => CH341_CLKRATE / (clkDiv(ps, 1) * 512);
const CH341_MIN_RATES = [minRate(0), minRate(1), minRate(2), minRate(3)];

export function ch341Divisor(speed) {
  const minBps = minRate(0);
  const maxBps = CH341_CLKRATE / (clkDiv(3, 0) * 2);
  speed = Math.min(Math.max(speed, minBps), maxBps);
  let fact = 1;
  let ps;
  for (ps = 3; ps >= 0; ps--) if (speed > CH341_MIN_RATES[ps]) break;
  if (ps < 0) throw new Error('Unsupported baud rate');
  let div = Math.floor(CH341_CLKRATE / (clkDiv(ps, fact) * speed));
  let clk = clkDiv(ps, fact);
  if (div < 9 || div > 255) { div = Math.floor(div / 2); clk *= 2; fact = 0; }
  if (div < 2) throw new Error('Unsupported baud rate');
  if (Math.floor(16 * CH341_CLKRATE / (clk * div)) - 16 * speed >=
      16 * speed - Math.floor(16 * CH341_CLKRATE / (clk * (div + 1)))) div++;
  if (fact === 1 && div % 2 === 0) { div /= 2; fact = 0; }
  return ((0x100 - div) << 8) | (fact << 2) | ps;
}

// Actual baud produced by an encoded CH341 divisor; used to check the encoding.
export function ch341ActualBaud(encoded) {
  const ps = encoded & 3;
  const fact = (encoded >> 2) & 1;
  const div = 0x100 - ((encoded >> 8) & 0xff);
  return CH341_CLKRATE / (clkDiv(ps, fact) * div);
}

// ---------- FTDI FT232 baud divisor (3 MHz base, 1/8 fractional steps) ----------
const FTDI_FRAC_CODE = [0, 3, 2, 4, 1, 5, 6, 7];
export function ftdiDivisor(baud) {
  const d8 = Math.round((3000000 * 8) / baud);
  let integer = d8 >> 3;
  let frac = d8 & 7;
  if (integer === 1 && frac === 0) integer = 0;           // 3 Mbaud special case
  const code = FTDI_FRAC_CODE[frac];
  return {value: (integer & 0x3fff) | ((code & 3) << 14), index: code >> 2};
}

// ---------- driver implementations ----------
class UsbSerialBase {
  constructor(device) { this.device = device; this.inEp = null; this.outEp = null; this.iface = 0; this.packetSize = 64; }
  async openDevice() {
    if (!this.device.opened) await this.device.open();
    if (this.device.configuration === null) await this.device.selectConfiguration(1);
  }
  findBulk(ifaceFilter) {
    for (const iface of this.device.configuration.interfaces) {
      const alt = iface.alternates[0];
      if (ifaceFilter && !ifaceFilter(alt)) continue;
      const inEp = alt.endpoints.find(e => e.type === 'bulk' && e.direction === 'in');
      const outEp = alt.endpoints.find(e => e.type === 'bulk' && e.direction === 'out');
      if (inEp && outEp) return {iface: iface.interfaceNumber, inEp, outEp};
    }
    throw new Error('No bulk endpoints found on this USB device');
  }
  async claimBulk(ifaceFilter) {
    const found = this.findBulk(ifaceFilter);
    this.iface = found.iface; this.inEp = found.inEp.endpointNumber; this.outEp = found.outEp.endpointNumber;
    this.packetSize = found.inEp.packetSize || 64;
    await this.device.claimInterface(this.iface);
  }
  async vendorOut(request, value, index, data, recipient = 'device') {
    const setup = {requestType: 'vendor', recipient, request, value, index};
    const r = data ? await this.device.controlTransferOut(setup, data) : await this.device.controlTransferOut(setup);
    if (r.status !== 'ok') throw new Error(`USB control 0x${request.toString(16)} failed: ${r.status}`);
  }
  async write(bytes) {
    const r = await this.device.transferOut(this.outEp, bytes);
    if (r.status !== 'ok') throw new Error('USB write failed: ' + r.status);
  }
  async read() {
    const r = await this.device.transferIn(this.inEp, this.packetSize * 4);
    if (r.status === 'stall') { await this.device.clearHalt('in', this.inEp); return new Uint8Array(0); }
    return r.data ? new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength) : new Uint8Array(0);
  }
  async close() { try { await this.device.releaseInterface(this.iface); } catch (_) {} try { await this.device.close(); } catch (_) {} }
}

export class CdcAcmDriver extends UsbSerialBase {
  static matches(device) {
    return device.configuration === null || device.configuration?.interfaces.some(i => i.alternates[0].interfaceClass === 0x0a) ||
      device.deviceClass === 0x02;
  }
  async open(baud) {
    await this.openDevice();
    const ifaces = this.device.configuration.interfaces;
    const control = ifaces.find(i => i.alternates[0].interfaceClass === 0x02);
    this.controlIface = control ? control.interfaceNumber : 0;
    if (control && control.interfaceNumber !== undefined) { try { await this.device.claimInterface(control.interfaceNumber); } catch (_) {} }
    await this.claimBulk(alt => alt.interfaceClass === 0x0a);
    const coding = new Uint8Array(7);
    new DataView(coding.buffer).setUint32(0, baud, true); coding[6] = 8; // 8N1
    const setup = {requestType: 'class', recipient: 'interface', index: this.controlIface};
    await this.device.controlTransferOut({...setup, request: 0x20, value: 0}, coding);      // SET_LINE_CODING
    await this.device.controlTransferOut({...setup, request: 0x22, value: 0x03});           // DTR | RTS
  }
}

export class Ch34xDriver extends UsbSerialBase {
  static matches(device) { return device.vendorId === 0x1a86; }
  async open(baud) {
    await this.openDevice();
    await this.claimBulk();
    const v = await this.device.controlTransferIn({requestType: 'vendor', recipient: 'device', request: 0x5f, value: 0, index: 0}, 2);
    this.version = v.data ? v.data.getUint8(0) : 0;
    await this.vendorOut(0xa1, 0, 0);                                    // SERIAL_INIT
    await this.vendorOut(0x9a, 0x1312, ch341Divisor(baud) | 0x80);       // divisor/prescaler, no 32-byte buffering
    if (this.version >= 0x30) await this.vendorOut(0x9a, 0x2518, 0xc3);   // LCR: RX, TX, CS8 (8N1)
    await this.vendorOut(0xa4, (~0x60) & 0xffff, 0);                     // DTR | RTS asserted (active low)
  }
}

export class Cp210xDriver extends UsbSerialBase {
  static matches(device) { return device.vendorId === 0x10c4; }
  async open(baud) {
    await this.openDevice();
    await this.claimBulk();
    const out = (req, value, data) => this.vendorOut(req, value, this.iface, data, 'interface');
    await out(0x00, 0x0001);                                             // IFC_ENABLE
    const b = new Uint8Array(4); new DataView(b.buffer).setUint32(0, baud, true);
    await out(0x1e, 0, b);                                               // SET_BAUDRATE
    await out(0x03, 0x0800);                                             // SET_LINE_CTL 8N1
    await out(0x07, 0x0303);                                             // SET_MHS DTR+RTS
  }
}

export class FtdiDriver extends UsbSerialBase {
  static matches(device) { return device.vendorId === 0x0403; }
  async open(baud) {
    await this.openDevice();
    await this.claimBulk();
    const port = this.iface + 1;
    await this.vendorOut(0x00, 0, port);                                 // SIO_RESET
    const d = ftdiDivisor(baud);
    await this.vendorOut(0x03, d.value, (d.index << 8) | port);           // SIO_SET_BAUD_RATE
    await this.vendorOut(0x04, 0x0008, port);                            // SIO_SET_DATA 8N1
    await this.vendorOut(0x02, 0, port);                                 // no flow control
    await this.vendorOut(0x01, 0x0303, port);                            // DTR+RTS high
  }
  async read() {
    // Every max-size packet starts with two modem-status bytes that must be removed.
    const raw = await super.read();
    return stripFtdiStatus(raw, this.packetSize);
  }
}

export function stripFtdiStatus(raw, packetSize = 64) {
  const out = [];
  for (let i = 0; i < raw.length; i += packetSize) {
    const chunk = raw.subarray(i, Math.min(i + packetSize, raw.length));
    for (let j = 2; j < chunk.length; j++) out.push(chunk[j]);
  }
  return Uint8Array.from(out);
}

export function pickDriver(device) {
  for (const D of [Ch34xDriver, Cp210xDriver, FtdiDriver]) if (D.matches(device)) return new D(device);
  return new CdcAcmDriver(device);
}

export function driverName(device) {
  return pickDriver(device).constructor.name.replace('Driver', '');
}
