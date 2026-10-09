'use strict';
// Starts the Python backend (backend/hoi4dbg) and resolves once it reports its port.

const { spawn } = require('node:child_process');
const readline = require('node:readline');

/** Python launch candidates, in order. HOI4DBG_PYTHON overrides everything. */
function pythonCandidates(env = process.env, platform = process.platform) {
  if (env.HOI4DBG_PYTHON) return [{ command: env.HOI4DBG_PYTHON, args: [] }];
  const list = [];
  if (platform === 'win32') list.push({ command: 'py', args: ['-3'] });
  list.push({ command: 'python', args: [] }, { command: 'python3', args: [] });
  return list;
}

/** Parses one stdout line; returns the ready message or null. */
function parseReadyLine(line) {
  try {
    const msg = JSON.parse(line);
    if (msg && msg.event === 'ready' && Number.isInteger(msg.port) && msg.port > 0) return msg;
  } catch {
    /* not a JSON line */
  }
  return null;
}

function spawnOnce(candidate, { backendDir, token, extraArgs, env, timeoutMs, onLog }) {
  return new Promise((resolve, reject) => {
    const child = spawn(candidate.command, [...candidate.args, '-m', 'hoi4dbg', '--watch-stdin', ...extraArgs], {
      cwd: backendDir,
      env: { ...env, HOI4DBG_TOKEN: token, PYTHONPATH: backendDir, PYTHONUTF8: '1' },
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    let settled = false;
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish(reject, new Error(`Backend did not start within ${timeoutMs} ms`));
    }, timeoutMs);

    child.on('error', (err) => finish(reject, err));
    child.on('exit', (code) => finish(reject, new Error(`Backend exited early with code ${code}`)));
    readline.createInterface({ input: child.stderr }).on('line', (line) => onLog('stderr', line));
    readline.createInterface({ input: child.stdout }).on('line', (line) => {
      const ready = parseReadyLine(line);
      if (ready) finish(resolve, { child, port: ready.port, candidate });
      else onLog('stdout', line);
    });
  });
}

/**
 * Starts the backend, trying each Python candidate until one launches.
 * Returns { port, child, candidate, stop() }.
 */
async function startBackend({ backendDir, token, extraArgs = [], env = process.env, timeoutMs = 20000,
  onLog = () => {} }) {
  const errors = [];
  for (const candidate of pythonCandidates(env)) {
    try {
      const started = await spawnOnce(candidate, { backendDir, token, extraArgs, env, timeoutMs, onLog });
      started.stop = () => {
        if (started.child.exitCode === null) {
          started.child.stdin.end(); // backend exits on stdin EOF
          setTimeout(() => started.child.exitCode === null && started.child.kill(), 3000).unref();
        }
      };
      return started;
    } catch (err) {
      errors.push(`${candidate.command}: ${err.message}`);
      if (err.code !== 'ENOENT') break; // Python found but backend failed: retrying another interpreter won't help
    }
  }
  throw new Error(`Could not start the Python backend.\n${errors.join('\n')}`);
}

module.exports = { pythonCandidates, parseReadyLine, startBackend };
