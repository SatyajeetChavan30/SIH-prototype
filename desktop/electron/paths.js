// Where the desktop app keeps everything it writes, and the optional user config.
//
// Nothing is ever written under the install directory. Program Files is
// read-only for a normal user, and even a per-user install would lose data on
// uninstall or upgrade. So every writable path lives under one root,
// %LOCALAPPDATA%\JalRaksha by default:
//
//   data\            JALRAKSHA_DATA_DIR — DEMs, runs, exports, keyframes, the
//                    SQLite database. Same layout as a checkout's ./data.
//   logs\            the shell's and the backend's own logs (per-run logs stay
//                    in data\runs\<run_id>.log, where the service writes them)
//   cache\numba\     NUMBA_CACHE_DIR — compiled kernels, rebuilt on demand
//   cache\matplotlib MPLCONFIGDIR — matplotlib's font cache
//   config\desktop.json   optional, user-edited (see loadDesktopConfig)
//   electron\        Electron's own userData (Chromium cache, local storage)
"use strict";

const fs = require("node:fs");
const path = require("node:path");

/** Keys desktop.json may set. Anything else is ignored, never passed through. */
const CONFIG_KEYS = Object.freeze([
  "dataDir", // absolute path; overrides <root>\data (e.g. point at a checkout's data\)
  "cesiumIonToken", // Cesium ion token for 3D terrain — the installer carries none
  "cesiumIonAssetId",
  "geeProject", // JALRAKSHA_GEE_PROJECT; Earth Engine credentials stay the user's own
  "paraviewExe", // JALRAKSHA_PARAVIEW_EXE
  "pvpythonExe", // JALRAKSHA_PVPYTHON_EXE
  "dflowfmExe", // JALRAKSHA_DFLOWFM_EXE
  "python", // development mode only: the interpreter that runs the source checkout
]);

/**
 * Every writable location, derived from one root.
 *
 * @param {object} opts
 * @param {string} opts.localAppData  %LOCALAPPDATA%
 * @param {string} [opts.rootOverride]  JALRAKSHA_DESKTOP_ROOT, for tests and side-by-side installs
 * @param {string} [opts.dataDirOverride]  desktop.json "dataDir"
 */
function desktopPaths({ localAppData, rootOverride, dataDirOverride }) {
  if (!rootOverride && !localAppData) {
    throw new Error("LOCALAPPDATA is not set; cannot choose a writable data location");
  }
  const root = path.resolve(rootOverride || path.join(localAppData, "JalRaksha"));
  const dataDir = path.resolve(dataDirOverride || path.join(root, "data"));
  return {
    root,
    dataDir,
    // The backend's working directory is the data directory's PARENT. A
    // checkout's database stores export paths relative to its working
    // directory ("data\exports\..."), so pointing dataDir at a checkout's data\
    // keeps every one of those rows resolvable.
    backendCwd: path.dirname(dataDir),
    databaseFile: path.join(dataDir, "jalraksha.db"),
    logsDir: path.join(root, "logs"),
    numbaCacheDir: path.join(root, "cache", "numba"),
    matplotlibDir: path.join(root, "cache", "matplotlib"),
    configDir: path.join(root, "config"),
    configFile: path.join(root, "config", "desktop.json"),
    electronUserData: path.join(root, "electron"),
  };
}

/** Create the writable tree on first run. Idempotent. */
function ensureDesktopDirs(paths) {
  for (const dir of [paths.dataDir, paths.logsDir, paths.numbaCacheDir,
    paths.matplotlibDir, paths.configDir, paths.electronUserData]) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

/**
 * Read desktop.json. Missing is normal; malformed is reported, not fatal.
 *
 * Only string values for known keys are kept, so a typo cannot inject an
 * arbitrary environment variable into the backend.
 *
 * @returns {{config: object, warning: string|null}}
 */
function loadDesktopConfig(file) {
  let raw;
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch (err) {
    if (err.code === "ENOENT") return { config: {}, warning: null };
    return { config: {}, warning: `Could not read ${file}: ${err.message}` };
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    return { config: {}, warning: `${file} is not valid JSON (${err.message}); ignoring it` };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { config: {}, warning: `${file} must contain a JSON object; ignoring it` };
  }
  const config = {};
  const ignored = [];
  for (const [key, value] of Object.entries(parsed)) {
    if (CONFIG_KEYS.includes(key) && typeof value === "string" && value.trim()) {
      config[key] = value.trim();
    } else {
      ignored.push(key);
    }
  }
  if (config.dataDir && !path.isAbsolute(config.dataDir)) {
    ignored.push("dataDir");
    delete config.dataDir;
  }
  return {
    config,
    warning: ignored.length ? `${file}: ignored unknown or invalid keys: ${ignored.join(", ")}` : null,
  };
}

module.exports = { CONFIG_KEYS, desktopPaths, ensureDesktopDirs, loadDesktopConfig };
