// UI smoke test: launches the real Electron app (hidden window) which visits every tab at two
// window sizes, captures screenshots into smoke-output/ and fails on console errors or broken views.
// Usage: npm run smoke          (live game detection)
//        HOI4DBG_NO_GAME=1 npm run smoke   (never touches the game)
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const outDir = path.join(root, 'smoke-output');
fs.rmSync(outDir, { recursive: true, force: true });

const electronBinary = require('electron');
const child = spawn(electronBinary, [root], {
  env: { ...process.env, HOI4DBG_SMOKE_DIR: outDir },
  stdio: 'inherit',
});

const timeout = setTimeout(() => {
  console.error('Smoke test timed out');
  child.kill();
  process.exit(1);
}, 120000);

child.on('exit', (code) => {
  clearTimeout(timeout);
  const resultFile = path.join(outDir, 'result.json');
  if (!fs.existsSync(resultFile)) {
    console.error(`No result.json (electron exit code ${code})`);
    process.exit(1);
  }
  const result = JSON.parse(fs.readFileSync(resultFile, 'utf8'));
  for (const t of result.tabs) {
    console.log(`${t.loaded ? 'ok  ' : 'FAIL'} ${t.size.padEnd(6)} ${t.tab.padEnd(15)} heading="${t.heading}" demoBadges=${t.demoBadges}`);
  }
  if (result.consoleErrors.length) console.log('Console errors:', result.consoleErrors);
  if (result.failures.length) {
    console.error('Failures:\n - ' + result.failures.join('\n - '));
    process.exit(1);
  }
  console.log(`Smoke test passed: ${result.tabs.length} views, screenshots in ${outDir}`);
});
