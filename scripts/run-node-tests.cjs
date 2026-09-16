#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
let failed = 0;
const files = fs.readdirSync(path.join(root, 'tests')).filter(name => /^test_.*\.cjs$/.test(name)).sort();
for (const name of files) {
  console.log('\n--- ' + name + ' ---');
  const result = spawnSync(process.execPath, [path.join(root, 'tests', name)], {
    cwd: root, env: process.env, stdio: 'inherit', timeout: 90000,
  });
  if (result.error || result.status !== 0) {
    failed++;
    console.error(name + ': failed' + (result.error ? ' (' + result.error.message + ')' : ''));
  }
}
console.log(`\n${files.length - failed}/${files.length} JavaScript test programs passed.`);
process.exitCode = failed ? 1 : 0;
