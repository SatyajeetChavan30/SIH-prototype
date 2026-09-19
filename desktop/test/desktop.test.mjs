// Unit tests for the desktop shell's pure pieces: `node --test desktop/test/`.
//
// The Electron process itself is exercised by `npm run desktop:smoke`; these
// cover the decisions that fail silently when they regress — a fixed port, a
// backend that never reports healthy, a config key smuggled into the backend's
// environment, a navigation that escapes the dashboard, a static request that
// escapes the frontend directory.
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const { desktopPaths, ensureDesktopDirs, loadDesktopConfig } = require("../electron/paths.js");
const { backendCommand, buildBackendEnv, findFreePort, waitForHealth } = require("../electron/backend.js");
const { classifyNavigation } = require("../electron/navigation.js");
const { resolveStaticPath, startStaticServer } = require("../electron/static-server.js");
const { projectVersion } = await import("../scripts/sync-version.mjs");

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "jalraksha-desktop-"));

test("writable paths all live under LOCALAPPDATA\\JalRaksha", () => {
  const p = desktopPaths({ localAppData: "C:\\Users\\u\\AppData\\Local" });
  const root = path.resolve("C:\\Users\\u\\AppData\\Local\\JalRaksha");
  assert.equal(p.root, root);
  for (const key of ["dataDir", "databaseFile", "logsDir", "numbaCacheDir", "configFile", "electronUserData"]) {
    assert.ok(p[key].startsWith(root), `${key} = ${p[key]}`);
  }
  // The backend runs from the data directory's parent (stored paths are data\...).
  assert.equal(p.backendCwd, root);
});

test("a dataDir override moves data and the backend cwd, not logs", () => {
  const p = desktopPaths({ localAppData: "C:\\L", dataDirOverride: "D:\\checkout\\data" });
  assert.equal(p.dataDir, path.resolve("D:\\checkout\\data"));
  assert.equal(p.backendCwd, path.resolve("D:\\checkout"));
  assert.ok(p.logsDir.startsWith(path.resolve("C:\\L\\JalRaksha")));
});

test("first run creates the writable tree", () => {
  const root = tmp();
  const p = desktopPaths({ rootOverride: path.join(root, "JalRaksha") });
  ensureDesktopDirs(p);
  for (const dir of [p.dataDir, p.logsDir, p.numbaCacheDir, p.configDir]) assert.ok(fs.statSync(dir).isDirectory());
});

test("desktop.json keeps only known string keys", () => {
  const dir = tmp();
  const file = path.join(dir, "desktop.json");
  fs.writeFileSync(file, JSON.stringify({
    geeProject: "my-project", cesiumIonToken: "tok", PATH: "C:\\evil", dataDir: "relative\\data", paraviewExe: 42,
  }));
  const { config, warning } = loadDesktopConfig(file);
  assert.deepEqual(config, { geeProject: "my-project", cesiumIonToken: "tok" });
  assert.match(warning, /PATH/);
  assert.match(warning, /dataDir/);
  assert.deepEqual(loadDesktopConfig(path.join(dir, "missing.json")), { config: {}, warning: null });
  fs.writeFileSync(file, "{ not json");
  assert.match(loadDesktopConfig(file).warning, /not valid JSON/);
});

test("packaged backend env pins data, database, caches and eager tasks", () => {
  const p = desktopPaths({ localAppData: "C:\\L" });
  const env = buildBackendEnv({
    baseEnv: { PATH: "x", DATABASE_URL: "postgresql://someone/else" }, paths: p,
    config: { geeProject: "proj", cesiumIonToken: "secret" }, packaged: true,
  });
  assert.equal(env.CELERY_EAGER, "1");
  assert.equal(env.JALRAKSHA_DATA_DIR, p.dataDir);
  assert.equal(env.DATABASE_URL, `sqlite:///${p.databaseFile.replace(/\\/g, "/")}`);
  assert.equal(env.NUMBA_CACHE_DIR, p.numbaCacheDir);
  assert.equal(env.JALRAKSHA_GEE_PROJECT, "proj");
  assert.equal(env.PATH, "x");
  // The Cesium token is for the page only; the backend never needs it.
  assert.ok(!Object.values(env).includes("secret"));
});

test("development backend env leaves the checkout's data defaults alone", () => {
  const p = desktopPaths({ localAppData: "C:\\L" });
  const env = buildBackendEnv({ baseEnv: {}, paths: p, config: {}, packaged: false });
  assert.equal(env.JALRAKSHA_DATA_DIR, undefined);
  assert.equal(env.DATABASE_URL, undefined);
  assert.equal(env.CELERY_EAGER, "1");
});

test("backend commands: frozen subcommands when packaged, run_api.py in development", () => {
  const packaged = backendCommand({ packaged: true, resourcesPath: "C:\\App\\resources", command: "serve", args: ["--port", "5"] });
  assert.equal(packaged.file, path.join("C:\\App\\resources", "backend", "jalraksha-backend.exe"));
  assert.deepEqual(packaged.args, ["serve", "--port", "5"]);
  const dev = backendCommand({ packaged: false, repoRoot: "D:\\repo", python: "py", command: "serve", args: ["--port", "5"] });
  assert.deepEqual(dev.args, [path.join("D:\\repo", "scripts", "run_api.py"), "--port", "5"]);
  const devPack = backendCommand({ packaged: false, repoRoot: "D:\\repo", python: "py", command: "pack", args: ["import", "x"] });
  assert.deepEqual(devPack.args, [path.join("D:\\repo", "desktop", "backend", "jalraksha_backend.py"), "pack", "import", "x"]);
});

test("findFreePort returns distinct usable loopback ports", async () => {
  const a = await findFreePort();
  const b = await findFreePort();
  assert.ok(a > 0 && b > 0);
  assert.notEqual(a, 8000);
  await new Promise((resolve, reject) => {
    const server = http.createServer().listen(a, "127.0.0.1", () => server.close(resolve)).on("error", reject);
  });
});

test("waitForHealth resolves once /health says ok", async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    if (calls < 3) throw new Error("ECONNREFUSED");
    return { ok: true, json: async () => ({ status: "ok" }) };
  };
  const body = await waitForHealth("http://127.0.0.1:1", { fetchImpl, intervalMs: 5, timeoutMs: 2000 });
  assert.equal(body.status, "ok");
  assert.equal(calls, 3);
});

test("waitForHealth is bounded", async () => {
  const fetchImpl = async () => { throw new Error("ECONNREFUSED"); };
  await assert.rejects(
    waitForHealth("http://127.0.0.1:1", { fetchImpl, intervalMs: 5, timeoutMs: 60 }),
    /did not become healthy within/);
});

test("waitForHealth stops early when the backend has exited", async () => {
  const started = Date.now();
  await assert.rejects(
    waitForHealth("http://127.0.0.1:1", { fetchImpl: async () => { throw new Error("x"); }, isAlive: () => false, timeoutMs: 60000 }),
    /exited before it became healthy/);
  assert.ok(Date.now() - started < 1000);
});

test("navigation stays inside the dashboard", () => {
  const origins = { uiOrigin: "http://127.0.0.1:5100", apiOrigin: "http://127.0.0.1:5200" };
  assert.equal(classifyNavigation("http://127.0.0.1:5100/", origins), "allow");
  assert.equal(classifyNavigation("http://127.0.0.1:5200/files/exports/r/h_max.tif", origins), "download");
  assert.equal(classifyNavigation("http://127.0.0.1:5200/runs", origins), "deny");
  assert.equal(classifyNavigation("https://cesium.com/ion", origins), "external");
  assert.equal(classifyNavigation("http://example.com/", origins), "deny");
  assert.equal(classifyNavigation("file:///C:/Windows/win.ini", origins), "deny");
  assert.equal(classifyNavigation("javascript:alert(1)", origins), "deny");
  assert.equal(classifyNavigation("not a url", origins), "deny");
});

test("static paths cannot escape the frontend directory", () => {
  const root = path.resolve("C:\\app\\frontend");
  assert.equal(resolveStaticPath(root, "/assets/index.js"), path.join(root, "assets", "index.js"));
  assert.equal(resolveStaticPath(root, "/"), root);
  for (const evil of ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%5c..%5csecret.txt", "/a%00b"]) {
    const resolved = resolveStaticPath(root, evil);
    // Either refused outright, or normalised by URL parsing to a path that is
    // still inside the root ("/../secret.txt" is "/secret.txt" to a browser too).
    assert.ok(resolved === null || resolved.startsWith(root + path.sep), `${evil} -> ${resolved}`);
  }
  assert.equal(resolveStaticPath(root, "/assets/..%5c..%5csecret.txt"), null);
});

test("static server serves the build and nothing else", async () => {
  const root = tmp();
  fs.mkdirSync(path.join(root, "assets"));
  fs.writeFileSync(path.join(root, "index.html"), "<h1>ok</h1>");
  fs.writeFileSync(path.join(root, "assets", "app.js"), "console.log(1)");
  fs.writeFileSync(path.join(path.dirname(root), "outside.txt"), "secret");
  const server = await startStaticServer(root);
  try {
    assert.match(server.url, /^http:\/\/127\.0\.0\.1:\d+$/);
    let r = await fetch(`${server.url}/`);
    assert.equal(r.status, 200);
    assert.equal(await r.text(), "<h1>ok</h1>");
    r = await fetch(`${server.url}/assets/app.js`);
    assert.equal(r.headers.get("content-type"), "text/javascript; charset=utf-8");
    r = await fetch(`${server.url}/missing.js`);
    assert.equal(r.status, 404);
    r = await fetch(`${server.url}/`, { method: "POST" });
    assert.equal(r.status, 405);
  } finally {
    await server.close();
  }
});

test("the desktop version is the project version", () => {
  const pkg = JSON.parse(fs.readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(pkg.version, projectVersion());
});
