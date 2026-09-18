'use strict';
const {spawnSync} = require('child_process');
const path = require('path');
const result = spawnSync(process.env.CREO_CLI_PYTHON || 'python', [path.join(__dirname, 'version.py'), '--sync'], {stdio:'inherit',shell:false});
process.exit(result.status === null ? 1 : result.status);
