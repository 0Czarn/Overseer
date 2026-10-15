// One-off: the app's localStorage (settings of the UI) lived in a profile named after package.json - renaming the app
// (hoi4-debugger -> project-overseer -> the-overseer) started empty profiles. This reads the app://ui storage of every
// profile and writes the merged keys (newest profile wins per key) into the profile main.cjs now pins (USER_DATA).
//   npx electron app/tools/merge-profiles.cjs        (the app must be closed)
const { app, BrowserWindow, protocol } = require('electron');
const path = require('node:path');

const TARGET = 'hoi4-debugger';
const SOURCES = ['hoi4-debugger', 'project-overseer', 'the-overseer'];   // oldest first: later ones win
const step = process.argv.find((a) => a.startsWith('--step='))?.slice(7);

protocol.registerSchemesAsPrivileged([{ scheme: 'app', privileges: { standard: true, secure: true } }]);

async function page() {
  protocol.handle('app', () => new Response('<!doctype html><title>merge</title>', { headers: { 'content-type': 'text/html' } }));
  const win = new BrowserWindow({ show: false });
  await win.loadURL('app://ui/merge.html');
  return win;
}

// Each profile needs its own process (the user data folder is fixed at start): this script runs itself once per profile.
if (step === undefined) {
  const { execFileSync } = require('node:child_process');
  const merged = {};
  for (const name of SOURCES) {
    const out = execFileSync(process.execPath, [__filename, `--step=read:${name}`], { encoding: 'utf8' });
    const dump = JSON.parse(out.split('\n').find((l) => l.startsWith('{')) ?? '{}');
    console.log(`${name}: ${Object.keys(dump).length} keys`);
    Object.assign(merged, dump);
  }
  const file = path.join(require('node:os').tmpdir(), 'overseer-merged-storage.json');
  require('node:fs').writeFileSync(file, JSON.stringify(merged));
  execFileSync(process.execPath, [__filename, `--step=write:${file}`], { stdio: 'inherit' });
  console.log(`merged ${Object.keys(merged).length} keys into ${TARGET}`);
  process.exit(0);
} else {
  const [kind, arg] = [step.slice(0, step.indexOf(':')), step.slice(step.indexOf(':') + 1)];
  app.setPath('userData', path.join(app.getPath('appData'), kind === 'read' ? arg : TARGET));
  app.whenReady().then(async () => {
    const win = await page();
    if (kind === 'read') {
      const dump = await win.webContents.executeJavaScript('JSON.stringify(Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)])))');
      process.stdout.write(`${dump}\n`);
    } else {
      const data = require('node:fs').readFileSync(arg, 'utf8');
      await win.webContents.executeJavaScript(`(() => { const d = ${data}; for (const [k, v] of Object.entries(d)) localStorage.setItem(k, v); return Object.keys(d).length; })()`);
      await new Promise((r) => setTimeout(r, 500));   // let the storage reach the disk
    }
    app.quit();
  });
}
