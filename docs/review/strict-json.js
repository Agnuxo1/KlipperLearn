/* SPDX-License-Identifier: MIT
 * Strict bounded JSON parser for local, untrusted evidence. No evaluation.
 * Rejects duplicate object keys before JSON.parse could discard them.
 */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KlipperLearnJSON = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function parse(text, maximum = 2 * 1024 * 1024) {
    if (typeof text !== 'string' || text.length > maximum) throw new Error('JSON exceeds the input limit.');
    let offset = 0;
    const fail = message => { throw new Error(message + ' At character ' + offset + '.'); };
    const whitespace = () => { while (/^[\x20\t\r\n]$/.test(text[offset] || '')) offset++; };
    function string() {
      const start = offset++;
      while (offset < text.length) {
        const c = text[offset++];
        if (c === '"') {
          const result = JSON.parse(text.slice(start, offset));
          // Require scalar Unicode; reject isolated surrogates in decoded data.
          for (const symbol of result) {
            const n = symbol.codePointAt(0);
            if (n >= 0xd800 && n <= 0xdfff) fail('Invalid Unicode');
          }
          return result;
        }
        if (c === '\\') offset++;
      }
      return fail('Unterminated JSON string');
    }
    function value(depth) {
      if (depth > 32) fail('JSON nesting exceeds the limit');
      whitespace();
      if (text[offset] === '"') return string();
      if (text[offset] === '{') {
        offset++; whitespace();
        const result = Object.create(null), names = new Set();
        if (text[offset] === '}') { offset++; return result; }
        for (;;) {
          whitespace();
          if (text[offset] !== '"') fail('Expected an object key');
          const name = string();
          if (names.has(name)) fail('Duplicate JSON key');
          if (['__proto__', 'constructor', 'prototype'].includes(name)) fail('Forbidden object key');
          names.add(name); whitespace();
          if (text[offset++] !== ':') fail('Expected a colon');
          result[name] = value(depth + 1); whitespace();
          const delimiter = text[offset++];
          if (delimiter === '}') return result;
          if (delimiter !== ',') fail('Expected an object delimiter');
        }
      }
      if (text[offset] === '[') {
        offset++; whitespace(); const result = [];
        if (text[offset] === ']') { offset++; return result; }
        for (;;) {
          result.push(value(depth + 1)); whitespace();
          const delimiter = text[offset++];
          if (delimiter === ']') return result;
          if (delimiter !== ',') fail('Expected an array delimiter');
        }
      }
      for (const [word, result] of [['true', true], ['false', false], ['null', null]]) {
        if (text.startsWith(word, offset)) { offset += word.length; return result; }
      }
      const match = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(text.slice(offset));
      if (!match) return fail('Expected a JSON value');
      offset += match[0].length; const number = Number(match[0]);
      if (!Number.isFinite(number)) fail('Non-finite JSON number');
      return number;
    }
    const output = value(0); whitespace();
    if (offset !== text.length) fail('Unexpected trailing content');
    return output;
  }
  return Object.freeze({parse});
}));
