// JalRaksha desktop — Electron main process.
//
//   1. choose writable locations under %LOCALAPPDATA%\JalRaksha (paths.js)
//   2. start the Python backend on a free 127.0.0.1 port and wait for /health
//   3. serve the built dashboard from a loopback static server (packaged) or the
//      Vite dev server (development), and open it in a locked-down window
//   4. on exit, ask what to do with simulations still running, then stop the
//      backend accordingly
//
// Flags: --dev (development, implied when not packaged), --smoke (load, probe,
// write logs\smoke.json, quit), --smoke-run=<run_id>, --smoke-out=<file>.
// Environment: JALRAKSHA_DESKTOP_ROOT (override the writable root),
// JALRAKSHA_DESKTOP_PYTHON (development interpreter), JALRAKSHA_DESKTOP_UI_URL
// (development: use an already-running Vite server). See desktop/README.md.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { app, BrowserWindow, Menu, dialog, ipcMain, session, shell } = require("electron");

const { desktopPaths, ensureDesktopDirs, loadDesktopConfig } = require("./paths");
const { buildBackendEnv, findFreePort, runBackendCli, startBackend, stopProcess } = require("./backend");
const { startStaticServer } = require("./static-server");
const { classifyNavigation, originOf } = require("./navigation");

const PACKAGED = app.isPackaged;
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const argValue = (name) => {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : null;
};
const SMOKE = process.argv.includes("--smoke");

// ---------------------------------------------------------------- locations
const earlyConfigPaths = desktopPaths({
  localAppData: process.env.LOCALAPPDATA,
  rootOverride: process.env.JALRAKSHA_DESKTOP_ROOT,
});
const { config, warning: configWarning } = loadDesktopConfig(earlyConfigPaths.configFile);
const PATHS = desktopPaths({
  localAppData: process.env.LOCALAPPDATA,
  rootOverride: process.env.JALRAKSHA_DESKTOP_ROOT,
  dataDirOverride: config.dataDir,
});
ensureDesktopDirs(PATHS);
// Electron's own cache and storage go under the same root, not %APPDATA%.
app.setPath("userData", PATHS.electronUserData);

const desktopLog = path.join(PATHS.logsDir, `desktop-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}.log`);
function log(message) {
  const line = `${new Date().toISOString()} ${message}\n`;
  try {
    fs.appendFileSync(desktopLog, line);
  } catch {
    // logging must never take the app down
  }
  if (!PACKAGED) process.stdout.write(line);
}
if (configWarning) log(`[config] ${configWarning}`);

function readBuildInfo() {
  const candidates = PACKAGED
    ? [path.join(process.resourcesPath, "build-info.json")]
    : [path.join(__dirname, "..", "build", "build-info.json")];
  for (const file of candidates) {
    try {
      return JSON.parse(fs.readFileSync(file, "utf8"));
    } catch {
      // fall through
    }
  }
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
  return { version: pkg.version, gitSha: "development", buildTime: null, variant: "development" };
}
const BUILD = readBuildInfo();

// ---------------------------------------------------------------- state
let mainWindow = null;
let backend = null; // {url, pid, logFile}
let backendEnv = null;
let uiServer = null; // {url, close}
let viteChild = null;
let uiUrl = null;
let quitDecision = null; // null | "stop-runs" | "keep-runs"
let shutdownStarted = false;
let shutdownComplete = false;

const cliContext = () => ({
  packaged: PACKAGED, resourcesPath: process.resourcesPath, repoRoot: REPO_ROOT,
  python: config.python || process.env.JALRAKSHA_DESKTOP_PYTHON || "python",
  paths: PATHS, env: backendEnv,
});

// The page asks once, synchronously, from the sandboxed preload.
ipcMain.on("jalraksha:get-runtime-config", (event) => {
  const senderOrigin = originOf(event.senderFrame?.url || "");
  // Only the dashboard gets the config (the Cesium token is in it).
  if (!backend || !uiUrl || senderOrigin !== originOf(uiUrl)) {
    event.returnValue = {};
    return;
  }
  event.returnValue = {
    apiUrl: backend.url,
    tilesUrl: `${backend.url}/tiles`,
    cesiumIonToken: config.cesiumIonToken || "",
    cesiumIonAssetId: config.cesiumIonAssetId || "",
    version: BUILD.version,
    gitSha: BUILD.gitSha,
    buildTime: BUILD.buildTime,
    variant: BUILD.variant,
  };
});

// ---------------------------------------------------------------- window
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 1000,
    minHeight: 700,
    title: `JalRaksha ${BUILD.version}`,
    backgroundColor: "#f5f5f2",
    show: !SMOKE,
    autoHideMenuBar: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      spellcheck: false,
    },
  });

  const contents = mainWindow.webContents;
  contents.setWindowOpenHandler(({ url }) => {
    if (backend && uiUrl && classifyNavigation(url, { uiOrigin: originOf(uiUrl), apiOrigin: originOf(backend.url) }) === "external") {
      shell.openExternal(url);
    } else if (backend && uiUrl && classifyNavigation(url, { uiOrigin: originOf(uiUrl), apiOrigin: originOf(backend.url) }) === "download") {
      contents.downloadURL(url);
    }
    return { action: "deny" };
  });
  contents.on("will-navigate", (event, url) => {
    // Before the dashboard loads, only the bundled loading/error pages exist.
    if (!backend || !uiUrl) {
      if (!url.startsWith("file:")) event.preventDefault();
      return;
    }
    const verdict = classifyNavigation(url, { uiOrigin: originOf(uiUrl), apiOrigin: originOf(backend.url) });
    if (verdict === "allow") return;
    event.preventDefault();
    if (verdict === "download") contents.downloadURL(url);
    else if (verdict === "external") shell.openExternal(url);
    else log(`[navigation] blocked ${url}`);
  });
  contents.on("will-attach-webview", (event) => event.preventDefault());

  mainWindow.on("close", (event) => {
    if (shutdownComplete || quitDecision) return;
    event.preventDefault();
    requestQuit();
  });
  mainWindow.on("closed", () => { mainWindow = null; });
  return mainWindow;
}

function showErrorPage(message, logFile) {
  log(`[startup] FAILED: ${message}`);
  if (!mainWindow) return;
  mainWindow.loadFile(path.join(__dirname, "error.html"), {
    query: { message, log: logFile || PATHS.logsDir, logs: PATHS.logsDir },
  });
  mainWindow.show();
}

// ---------------------------------------------------------------- menu
async function importDataPack() {
  if (!backend) return;
  const pick = await dialog.showOpenDialog(mainWindow, {
    title: "Import JalRaksha data pack",
    filters: [{ name: "JalRaksha data pack", extensions: ["jrpack"] }],
    properties: ["openFile"],
  });
  if (pick.canceled || !pick.filePaths.length) return;
  const file = pick.filePaths[0];
  log(`[pack] importing ${file}`);
  mainWindow?.setTitle(`JalRaksha ${BUILD.version} — importing data pack…`);
  const result = await runBackendCli({ ...cliContext(), command: "pack", args: ["import", file], timeoutMs: 60 * 60 * 1000 });
  mainWindow?.setTitle(`JalRaksha ${BUILD.version}`);
  log(`[pack] result ${JSON.stringify(result)}`);
  if (result.ok) {
    const detail = [
      `Pack: ${result.name || path.basename(file)}`,
      `Runs imported: ${result.imported_runs.length}`,
      result.skipped_existing_runs.length ? `Already present (left unchanged): ${result.skipped_existing_runs.length}` : null,
      `Files copied: ${result.files_copied} (already present: ${result.files_already_present})`,
      result.synthetic_run_ids.length ? `SYNTHETIC runs (labelled, not simulations): ${result.synthetic_run_ids.join(", ")}` : null,
      `Data folder: ${result.data_dir}`,
    ].filter(Boolean).join("\n");
    await dialog.showMessageBox(mainWindow, { type: "info", message: "Data pack imported", detail });
    mainWindow?.webContents.reload();
  } else {
    await dialog.showMessageBox(mainWindow, {
      type: "error", message: "Data pack was not imported", detail: `${result.error}\n\nNothing was changed.`,
    });
  }
}

function buildMenu() {
  const template = [
    {
      label: "File",
      submenu: [
        { label: "Import data pack…", accelerator: "CmdOrCtrl+I", click: () => importDataPack() },
        { type: "separator" },
        { label: "Quit", accelerator: "CmdOrCtrl+Q", click: () => requestQuit() },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
        ...(PACKAGED ? [] : [{ role: "toggleDevTools" }]),
      ],
    },
    {
      label: "Help",
      submenu: [
        { label: "Open logs folder", click: () => shell.openPath(PATHS.logsDir) },
        { label: "Open data folder", click: () => shell.openPath(PATHS.dataDir) },
        { label: "Open settings folder (desktop.json)", click: () => shell.openPath(PATHS.configDir) },
        { type: "separator" },
        {
          label: "About JalRaksha",
          click: () => dialog.showMessageBox(mainWindow, {
            type: "info",
            message: `JalRaksha ${BUILD.version}`,
            detail: [
              `Build: ${BUILD.variant} · commit ${BUILD.gitSha}`,
              BUILD.buildTime ? `Built: ${BUILD.buildTime}` : null,
              `API: ${backend ? backend.url : "not running"}`,
              `Data: ${PATHS.dataDir}`,
              "Tier-1 dam-break screening. Point depths are indicative only (30 m Copernicus GLO-30).",
            ].filter(Boolean).join("\n"),
          }),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---------------------------------------------------------------- startup
async function startUi() {
  if (PACKAGED) {
    uiServer = await startStaticServer(path.join(process.resourcesPath, "frontend"));
    return uiServer.url;
  }
  if (process.env.JALRAKSHA_DESKTOP_UI_URL) return process.env.JALRAKSHA_DESKTOP_UI_URL;
  // Development: the frontend's own Vite dev server, on a free port. The API
  // URL reaches the page through the preload bridge, so Vite needs no env.
  const port = await findFreePort();
  const command = `npm run dev --prefix "${path.join(REPO_ROOT, "frontend")}" -- --port ${port} --strictPort --host 127.0.0.1`;
  viteChild = spawn(command, { cwd: REPO_ROOT, shell: true, windowsHide: true, stdio: "ignore" });
  const url = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (response.ok) return url;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`the Vite dev server did not start on ${url} within 120 s`);
}

function lockDownSession() {
  const ses = session.defaultSession;
  // The dashboard needs no camera, microphone, notifications or geolocation.
  ses.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  ses.on("will-download", (_event, item) => {
    const target = path.join(app.getPath("downloads"), item.getFilename());
    item.setSaveDialogOptions({ defaultPath: target, title: "Save JalRaksha export" });
    log(`[download] ${item.getURL()}`);
  });
}

async function startup() {
  buildMenu();
  lockDownSession();
  createWindow();
  mainWindow.loadFile(path.join(__dirname, "loading.html"));

  backendEnv = buildBackendEnv({ baseEnv: process.env, paths: PATHS, config, packaged: PACKAGED });
  log(`[startup] JalRaksha ${BUILD.version} (${BUILD.variant}, ${BUILD.gitSha}) packaged=${PACKAGED}`);
  log(`[startup] data=${PATHS.dataDir} logs=${PATHS.logsDir}`);
  try {
    backend = await startBackend({ ...cliContext(), healthTimeoutMs: 120000 });
    log(`[startup] backend healthy at ${backend.url} (pid ${backend.pid}, log ${backend.logFile})`);
    uiUrl = await startUi();
    log(`[startup] dashboard at ${uiUrl}`);
  } catch (err) {
    backend = null;
    showErrorPage(err.message, err.logFile);
    if (SMOKE) {
      writeSmoke({ ok: false, error: err.message, log: err.logFile || null });
      shutdownComplete = true;
      app.exit(1);
    }
    return;
  }
  await mainWindow.loadURL(uiUrl);
  if (SMOKE) runSmoke();
}

// ---------------------------------------------------------------- smoke
function writeSmoke(report) {
  const out = argValue("smoke-out") || path.join(PATHS.logsDir, "smoke.json");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, JSON.stringify({ ...report, build: BUILD, paths: PATHS, packaged: PACKAGED }, null, 2));
  log(`[smoke] wrote ${out}`);
  return out;
}

async function runSmoke() {
  // A run id is 32 hex characters; anything else is ignored rather than
  // interpolated into the page script below.
  const requestedRun = argValue("smoke-run");
  const runId = requestedRun && /^[0-9a-f]{32}$/.test(requestedRun) ? requestedRun : null;
  let report;
  try {
    // Give React a moment to mount and issue its own first requests.
    await new Promise((r) => setTimeout(r, 4000));
    report = await mainWindow.webContents.executeJavaScript(`(async () => {
      const d = window.jalrakshaDesktop;
      const out = {
        bridge: Boolean(d), bridgeFrozen: Boolean(d) && Object.isFrozen(d),
        bridgeFunctions: d ? Object.values(d).filter((v) => typeof v === "function").length : null,
        apiUrl: d ? d.apiUrl : null,
        nodeGlobalsVisible: typeof require !== "undefined" || typeof process !== "undefined",
        heading: document.querySelector("h3") ? document.querySelector("h3").textContent : null,
      };
      const get = async (p) => {
        const r = await fetch(d.apiUrl + p);
        let body = null; try { body = await r.json(); } catch (e) {}
        return { status: r.status, body };
      };
      out.health = await get("/health");
      out.capabilities = await get("/capabilities");
      out.backends = await get("/backends");
      const runs = await get("/runs?limit=200");
      out.runs = { status: runs.status, count: Array.isArray(runs.body) ? runs.body.length : null,
                   done: Array.isArray(runs.body) ? runs.body.filter((r) => r.status === "done").map((r) => r.run_id) : [] };
      const runId = ${JSON.stringify(runId)};
      if (runId) {
        const result = await get("/runs/" + runId + "/result");
        out.result = { status: result.status, keyframe_manifest_url: result.body && result.body.keyframe_manifest_url,
                       exports: result.body && result.body.exports ? result.body.exports.length : null };
        if (out.result.keyframe_manifest_url) {
          const manifestUrl = new URL(out.result.keyframe_manifest_url, d.apiUrl).href;
          const m = await fetch(manifestUrl);
          const manifest = m.ok ? await m.json() : null;
          out.manifest = { status: m.status, keyframes: manifest && manifest.keyframes ? manifest.keyframes.length : null };
          if (manifest && manifest.keyframes && manifest.keyframes.length) {
            const png = await fetch(new URL(manifest.keyframes[0].png_url, manifestUrl).href);
            out.firstKeyframe = { status: png.status, type: png.headers.get("content-type") };
          }
        }
      }
      return out;
    })()`, true);
    if (runId) {
      // Load the run through the dashboard's own run picker, the way an
      // operator would, so the screenshot shows the run rather than an empty map.
      report.pickerLoaded = await mainWindow.webContents.executeJavaScript(`(() => {
        const option = document.querySelector('option[value="${runId}"]');
        if (!option) return false;
        const select = option.parentElement;
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
        setter.call(select, ${JSON.stringify(runId)});
        select.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      })()`, true);
      await new Promise((r) => setTimeout(r, 8000));
    }
    const image = await mainWindow.webContents.capturePage();
    const screenshot = path.join(PATHS.logsDir, "smoke.png");
    fs.writeFileSync(screenshot, image.toPNG());
    report = { ok: report.health && report.health.status === 200, ...report, uiUrl, screenshot };
  } catch (err) {
    report = { ok: false, error: err.message, uiUrl };
  }
  writeSmoke(report);
  quitDecision = "stop-runs";
  app.quit();
}

// ---------------------------------------------------------------- shutdown
async function activeRuns() {
  if (!backend) return [];
  try {
    const response = await fetch(`${backend.url}/runs?limit=500`, { signal: AbortSignal.timeout(5000) });
    const runs = await response.json();
    return Array.isArray(runs) ? runs.filter((r) => r.status === "running" || r.status === "queued") : [];
  } catch {
    return [];
  }
}

async function requestQuit() {
  if (quitDecision || shutdownStarted) return;
  const running = await activeRuns();
  if (running.length === 0) {
    quitDecision = "stop-runs";
  } else {
    const names = running.map((r) => `• ${r.dam_name || r.dam_id || "run"} (${r.run_id.slice(0, 8)}, ${r.status})`).join("\n");
    const choice = await dialog.showMessageBox(mainWindow, {
      type: "question",
      buttons: ["Stop runs and quit", "Keep running in background", "Cancel"],
      defaultId: 1,
      cancelId: 2,
      noLink: true,
      message: `${running.length} simulation${running.length === 1 ? " is" : "s are"} still running`,
      detail: `${names}\n\nStop runs: the simulations are terminated and marked failed.\n`
        + "Keep running: they finish in the background and appear in the run picker next time "
        + "JalRaksha opens. Their progress is not visible until then.",
    });
    if (choice.response === 2) return;
    quitDecision = choice.response === 0 ? "stop-runs" : "keep-runs";
  }
  log(`[shutdown] decision ${quitDecision} (${running.length} active)`);
  app.quit();
}

async function shutdown() {
  // System shutdown or a crash path without a decision: keep runs (the
  // service's own durability default) and stop only the server.
  const decision = quitDecision || "keep-runs";
  if (backend) {
    if (decision === "stop-runs") {
      const running = await activeRuns();
      if (running.length) {
        const result = await runBackendCli({ ...cliContext(), command: "stop-active-runs", args: [], timeoutMs: 60000 });
        log(`[shutdown] stop-active-runs ${JSON.stringify(result)}`);
      }
      await stopProcess(backend.pid, { tree: true });
    } else {
      // NOT the tree: run workers are the backend's children by pid.
      await stopProcess(backend.pid, { tree: false });
    }
    log(`[shutdown] backend ${backend.pid} stopped (${decision})`);
  }
  if (viteChild) await stopProcess(viteChild.pid, { tree: true });
  if (uiServer) await uiServer.close();
}

// ---------------------------------------------------------------- app events
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
  app.whenReady().then(startup);
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", (event) => {
    if (shutdownComplete) return;
    event.preventDefault();
    if (shutdownStarted) return;
    shutdownStarted = true;
    shutdown()
      .catch((err) => log(`[shutdown] error ${err.message}`))
      .finally(() => {
        shutdownComplete = true;
        app.quit();
      });
  });
}
