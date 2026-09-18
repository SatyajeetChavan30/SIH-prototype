// Lifecycle of the Python backend: pick a port, start it, wait for it, stop it.
//
// The backend is the FastAPI service. In a packaged app it is the frozen
// jalraksha-backend.exe under resources\backend; in development it is
// scripts/run_api.py from the checkout. Either way it listens on 127.0.0.1 only,
// on a port chosen here — never a fixed 8000, which a second app or a dev
// server may already hold.
"use strict";

const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { spawn, execFile } = require("node:child_process");

/** Ask the OS for a free loopback port. */
function findFreePort(host = "127.0.0.1") {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, host, () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

/**
 * Poll GET <baseUrl>/health until it answers {status: "ok"}.
 *
 * Bounded, and it stops early if the process has already exited — a backend
 * that crashed on import should surface in seconds, not after the timeout.
 *
 * @param {string} baseUrl
 * @param {object} [opts]
 * @param {number} [opts.timeoutMs=120000]  first launch of a frozen build unpacks and imports a lot
 * @param {number} [opts.intervalMs=500]
 * @param {() => boolean} [opts.isAlive]  false once the process has exited
 * @param {typeof fetch} [opts.fetchImpl]
 */
async function waitForHealth(baseUrl, opts = {}) {
  const {
    timeoutMs = 120000, intervalMs = 500, isAlive = () => true, fetchImpl = fetch,
  } = opts;
  const deadline = Date.now() + timeoutMs;
  let lastError = "no response yet";
  while (Date.now() < deadline) {
    if (!isAlive()) {
      throw new Error(`the backend process exited before it became healthy (last: ${lastError})`);
    }
    try {
      const response = await fetchImpl(`${baseUrl}/health`, { signal: AbortSignal.timeout(3000) });
      if (response.ok) {
        const body = await response.json();
        if (body && body.status === "ok") return body;
        lastError = `unexpected /health body ${JSON.stringify(body)}`;
      } else {
        lastError = `HTTP ${response.status}`;
      }
    } catch (err) {
      lastError = err.message;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`the backend did not become healthy within ${Math.round(timeoutMs / 1000)} s (last: ${lastError})`);
}

/**
 * Environment for the backend and every CLI call made against the same data.
 *
 * Starts from the parent environment so PATH, SystemRoot and the user's own
 * Earth Engine credentials location keep working, then pins everything the
 * desktop app owns. In development the data locations are left to
 * scripts/run_api.py's own defaults (the checkout's ./data) unless desktop.json
 * sets dataDir.
 */
function buildBackendEnv({ baseEnv, paths, config, packaged }) {
  const env = { ...baseEnv };
  // Eager tasks: runs go to a detached subprocess instead of a Celery broker.
  // The desktop app has no Redis, by design (offline-first).
  env.CELERY_EAGER = "1";
  env.NUMBA_CACHE_DIR = paths.numbaCacheDir;
  env.MPLCONFIGDIR = paths.matplotlibDir;
  env.PYTHONUNBUFFERED = "1";
  env.PYTHONIOENCODING = "utf-8";
  if (packaged || config.dataDir) {
    env.JALRAKSHA_DATA_DIR = paths.dataDir;
    // Absolute, so the database never depends on a working directory.
    env.DATABASE_URL = `sqlite:///${paths.databaseFile.replace(/\\/g, "/")}`;
  }
  const mapping = {
    geeProject: "JALRAKSHA_GEE_PROJECT",
    paraviewExe: "JALRAKSHA_PARAVIEW_EXE",
    pvpythonExe: "JALRAKSHA_PVPYTHON_EXE",
    dflowfmExe: "JALRAKSHA_DFLOWFM_EXE",
  };
  for (const [key, variable] of Object.entries(mapping)) {
    if (config[key]) env[variable] = config[key];
  }
  // A Postgres URL inherited from a developer shell would point the desktop app
  // at someone else's database; the packaged app always uses its own SQLite.
  if (packaged && /^postgres/i.test(baseEnv.DATABASE_URL || "")) {
    env.DATABASE_URL = `sqlite:///${paths.databaseFile.replace(/\\/g, "/")}`;
  }
  return env;
}

/**
 * The command that runs one backend entry point.
 *
 * @param {object} opts
 * @param {boolean} opts.packaged
 * @param {string} opts.resourcesPath  process.resourcesPath (packaged)
 * @param {string} opts.repoRoot  the checkout (development)
 * @param {string} [opts.python]  interpreter for development
 * @param {"serve"|"stop-active-runs"|"pack"} opts.command
 * @param {string[]} [opts.args]
 */
function backendCommand({ packaged, resourcesPath, repoRoot, python = "python", command, args = [] }) {
  if (packaged) {
    const exe = path.join(resourcesPath, "backend", "jalraksha-backend.exe");
    return { file: exe, args: [command, ...args], cwdHint: null };
  }
  // Development serves through scripts/run_api.py, exactly as the browser
  // workflow does, so its defaults (the checkout's ./data, the working
  // directory, the Earth Engine project) stay the ones developers rely on.
  if (command === "serve") {
    return { file: python, args: [path.join(repoRoot, "scripts", "run_api.py"), ...args], cwdHint: repoRoot };
  }
  // The CLI subcommands run through the frozen build's own entry script.
  const entry = path.join(repoRoot, "desktop", "backend", "jalraksha_backend.py");
  return { file: python, args: [entry, command, ...args], cwdHint: repoRoot };
}

function timestamp() {
  return new Date().toISOString().slice(0, 10).replace(/-/g, "");
}

/**
 * Start the backend and wait until it is healthy.
 *
 * @returns {Promise<{url: string, port: number, pid: number, logFile: string, child: import("node:child_process").ChildProcess}>}
 */
async function startBackend({ packaged, resourcesPath, repoRoot, python, paths, env, healthTimeoutMs }) {
  const port = await findFreePort();
  const { file, args } = backendCommand({
    packaged, resourcesPath, repoRoot, python,
    command: "serve", args: ["--host", "127.0.0.1", "--port", String(port)],
  });
  if (packaged && !fs.existsSync(file)) {
    throw new Error(`the packaged backend is missing: ${file}`);
  }
  const logFile = path.join(paths.logsDir, `backend-${timestamp()}.log`);
  const logFd = fs.openSync(logFile, "a");
  fs.writeSync(logFd, `\n==== ${new Date().toISOString()} starting ${file} ${args.join(" ")}\n`);

  // Packaged: cwd is the data directory's parent (paths.js explains why).
  // Development without a dataDir override: the checkout, as run_api.py expects.
  const cwd = packaged || env.JALRAKSHA_DATA_DIR ? paths.backendCwd : repoRoot;
  const child = spawn(file, args, {
    cwd, env, windowsHide: true, stdio: ["ignore", logFd, logFd],
  });
  fs.closeSync(logFd);

  let exited = false;
  let spawnError = null;
  child.on("exit", () => { exited = true; });
  child.on("error", (err) => { exited = true; spawnError = err; });

  const url = `http://127.0.0.1:${port}`;
  try {
    await waitForHealth(url, { timeoutMs: healthTimeoutMs, isAlive: () => !exited });
  } catch (err) {
    stopProcess(child.pid, { tree: true });
    const reason = spawnError ? `could not start ${file}: ${spawnError.message}` : err.message;
    const wrapped = new Error(reason);
    wrapped.logFile = logFile;
    throw wrapped;
  }
  return { url, port, pid: child.pid, logFile, child };
}

/**
 * Stop a process.
 *
 * `tree: false` is deliberate when the user chose to keep runs going: run
 * workers are the backend's CHILDREN by pid even though they are detached from
 * its console and job, and `taskkill /T` walks exactly that relationship, so it
 * would kill the very runs the user asked to keep.
 */
function stopProcess(pid, { tree }) {
  if (!pid) return Promise.resolve();
  return new Promise((resolve) => {
    if (process.platform === "win32") {
      const args = ["/PID", String(pid), "/F"];
      if (tree) args.splice(2, 0, "/T");
      execFile("taskkill", args, { windowsHide: true }, () => resolve());
    } else {
      try {
        process.kill(pid, "SIGTERM");
      } catch {
        // already gone
      }
      resolve();
    }
  });
}

/** Run a backend CLI subcommand to completion and parse its final JSON line. */
function runBackendCli({ packaged, resourcesPath, repoRoot, python, paths, env, command, args, timeoutMs = 600000 }) {
  const { file, args: argv } = backendCommand({ packaged, resourcesPath, repoRoot, python, command, args });
  const cwd = packaged || env.JALRAKSHA_DATA_DIR ? paths.backendCwd : repoRoot;
  return new Promise((resolve) => {
    execFile(file, argv, { cwd, env, windowsHide: true, timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024 },
      (error, stdout, stderr) => {
        const lines = String(stdout || "").split(/\r?\n/).filter((l) => l.startsWith("{"));
        let payload = null;
        try {
          payload = lines.length ? JSON.parse(lines[lines.length - 1]) : null;
        } catch {
          payload = null;
        }
        if (!payload) {
          payload = { ok: false, error: (stderr || error?.message || "no output").trim().slice(-2000) };
        }
        resolve(payload);
      });
  });
}

module.exports = {
  backendCommand, buildBackendEnv, findFreePort, runBackendCli, startBackend, stopProcess, waitForHealth,
};
