#!/usr/bin/env node
// Development source wrapper only; no postinstall downloads or npm release yet.
'use strict';
const path = require('path');
const {spawnSync} = require('child_process');
const root = path.resolve(__dirname, '..');
const python = process.env.CREO_CLI_PYTHON || 'python';
const env = {...process.env, PYTHONIOENCODING: 'utf-8', PYTHONPATH: [root, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter)};
const result = spawnSync(python, ['-m', 'creo_cli', ...process.argv.slice(2)], {env, stdio: 'inherit', shell: false});
if (result.error) {
  process.stdout.write(JSON.stringify({ok:false,schema_version:'1.0',error:{code:'E_CONFIG',message:'Python source runtime is unavailable; install Python 3.11+ or set CREO_CLI_PYTHON',details:{},retryable:false},meta:{duration_ms:0}})+'\n');
  process.exit(4);
}
process.exit(result.status === null ? 130 : result.status);
