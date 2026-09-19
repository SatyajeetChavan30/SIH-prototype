// Build the JalRaksha Windows desktop app.
//
//   node desktop/scripts/build.mjs --stage build|package|dist --variant cpu|gpu
//       [--skip-frontend] [--skip-backend] [--skip-install]
//       [--python <interpreter used to create the build venv>]
//       [--use-python-env]   freeze from --python's own environment, no venv
//
// Stages (each includes the previous one):
//   build    1. build-info.json (version, git SHA, UTC time, variant)
//            2. the React dashboard, built WITHOUT any Cesium token
//            3. the frozen backend: pinned venv + PyInstaller
//   package  4. electron-builder --dir (an unpacked app, for testing)
//   dist     5. the NSIS installer, copied to dist/windows/
//
// Output:
//   desktop/build/frontend, desktop/build/backend-<variant>/jalraksha-backend,
//   desktop/build/electron-<variant>/win-unpacked,
//   dist/windows/JalRaksha-<version>+<sha>-win-x64-<VARIANT>-Setup.exe
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { projectVersion } from "./sync-version.mjs";

const desktopDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(desktopDir, "..");
const buildDir = path.join(desktopDir, "build");
const isWindows = process.platform === "win32";

function parseArgs(argv) {
  // The interpreter is verified to be 3.14 below, whatever name it is found by.
  const opts = { stage: "dist", variant: "cpu", python: isWindows ? "python" : "python3" };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--stage") opts.stage = argv[++i];
    else if (arg === "--variant") opts.variant = argv[++i];
    else if (arg === "--python") opts.python = argv[++i];
    else if (arg === "--skip-frontend") opts.skipFrontend = true;
    else if (arg === "--skip-backend") opts.skipBackend = true;
    else if (arg === "--skip-install") opts.skipInstall = true;
    else if (arg === "--use-python-env") opts.usePythonEnv = true;
    else throw new Error(`unknown argument ${arg}`);
  }
  if (!["build", "package", "dist"].includes(opts.stage)) throw new Error(`--stage must be build, package or dist`);
  if (!["cpu", "gpu"].includes(opts.variant)) throw new Error(`--variant must be cpu or gpu`);
  return opts;
}

function run(file, args, { cwd = repoRoot, env = process.env, capture = false, shell = false } = {}) {
  const shown = [file, ...args].join(" ");
  console.log(`\n> ${shown}`);
  const result = spawnSync(file, args, {
    cwd, env, shell, stdio: capture ? ["ignore", "pipe", "inherit"] : "inherit", encoding: "utf8",
  });
  if (result.error) throw new Error(`${shown}: ${result.error.message}`);
  if (result.status !== 0) throw new Error(`${shown} exited with ${result.status}`);
  return capture ? result.stdout : "";
}

// npm is a .cmd shim on Windows, which Node only runs through a shell.
const npm = (args, opts = {}) => run(isWindows ? "npm.cmd" : "npm", args, { ...opts, shell: isWindows });

function gitSha() {
  const sha = spawnSync("git", ["rev-parse", "--short", "HEAD"], { cwd: repoRoot, encoding: "utf8" });
  if (sha.status !== 0) return "nogit";
  const dirty = spawnSync("git", ["status", "--porcelain"], { cwd: repoRoot, encoding: "utf8" });
  // A build from uncommitted changes must not carry a clean commit's name.
  return `${sha.stdout.trim()}${dirty.stdout.trim() ? "-dirty" : ""}`;
}

function writeBuildInfo(variant) {
  const info = {
    version: projectVersion(repoRoot),
    gitSha: gitSha(),
    buildTime: new Date().toISOString(),
    variant,
    python: "3.14",
  };
  fs.mkdirSync(buildDir, { recursive: true });
  fs.writeFileSync(path.join(buildDir, `build-info-${variant}.json`), JSON.stringify(info, null, 2));
  // The unpackaged shell (npm run dev / smoke) reads this name.
  fs.writeFileSync(path.join(buildDir, "build-info.json"), JSON.stringify(info, null, 2));
  console.log(`build info: ${JSON.stringify(info)}`);
  return info;
}

function readEnvValue(file, key) {
  try {
    const line = fs.readFileSync(file, "utf8").split(/\r?\n/).find((l) => l.startsWith(`${key}=`));
    return line ? line.slice(key.length + 1).trim().replace(/^["']|["']$/g, "") : "";
  } catch {
    return "";
  }
}

function listFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? listFiles(full) : [full];
  });
}

function buildFrontend(opts) {
  const frontendDir = path.join(repoRoot, "frontend");
  const outDir = path.join(buildDir, "frontend");
  if (!opts.skipInstall) npm(["ci"], { cwd: frontendDir });
  // Empty strings, not unset: vite.config.js lets process.env win over
  // frontend/.env.local, so "" guarantees no developer's token is baked into an
  // installer. The desktop app supplies the token at run time from the user's
  // own desktop.json.
  const env = { ...process.env, VITE_CESIUM_ION_TOKEN: "", VITE_CESIUM_ION_ASSET_ID: "" };
  // Vite's own CLI through node, not `npm run build -- ...`: npm is a .cmd shim
  // that needs a shell, and a shell splits this repository's path at its spaces.
  run(process.execPath, [path.join(frontendDir, "node_modules", "vite", "bin", "vite.js"),
    "build", "--outDir", outDir, "--emptyOutDir"], { cwd: frontendDir, env });

  // Prove it: the local token, if there is one, must appear nowhere in the output.
  const token = readEnvValue(path.join(frontendDir, ".env.local"), "VITE_CESIUM_ION_TOKEN");
  if (token && token.length >= 16) {
    for (const file of listFiles(outDir)) {
      if (/\.(js|html|css|json|map)$/.test(file) && fs.readFileSync(file, "utf8").includes(token)) {
        throw new Error(`the Cesium token from frontend/.env.local leaked into ${file}; refusing to package it`);
      }
    }
    console.log("verified: no Cesium token in the desktop frontend build");
  }

  // Prove the fonts and stylesheets are bundled: the dashboard is offline-first,
  // and a font pulled from a CDN renders fine on a connected dev machine and
  // falls back to other metrics on demo day. Only CSS and HTML are checked —
  // the JS legitimately carries network URLs (OSM tiles, the API default).
  const external = findExternalStyleRefs(outDir);
  if (external.length) {
    throw new Error(`the frontend build loads styles or fonts from the network:\n  ${external.join("\n  ")}`);
  }
  console.log("verified: no external font or stylesheet URL in the desktop frontend build");
}

/**
 * Every CSS url()/@import and HTML <link href> in `dir` that points off-machine.
 * data: URIs (Cesium's widget icons) and relative paths are fine; an absolute
 * or protocol-relative http(s) URL is not.
 */
function findExternalStyleRefs(dir) {
  const offMachine = String.raw`['"]?\s*(?:https?:)?\/\/`;
  const patterns = [
    new RegExp(String.raw`url\(\s*${offMachine}`, "i"),
    new RegExp(String.raw`@import\s+${offMachine}`, "i"),
    new RegExp(String.raw`<link\b[^>]*\bhref=${offMachine}`, "i"),
    /fonts\.(?:googleapis|gstatic)\.com/i,
  ];
  const hits = [];
  for (const file of listFiles(dir)) {
    if (!/\.css$/.test(file) && path.basename(file) !== "index.html") continue;
    const text = fs.readFileSync(file, "utf8");
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) hits.push(`${path.relative(dir, file)}: ${match[0]}`);
    }
  }
  return hits;
}

function buildBackend(opts) {
  const reqs = path.join(desktopDir, "backend", `requirements-${opts.variant}.txt`);
  let python;
  if (opts.usePythonEnv) {
    python = opts.python;
  } else {
    const venv = path.join(buildDir, `venv-${opts.variant}`);
    python = path.join(venv, isWindows ? "Scripts\\python.exe" : "bin/python");
    if (!fs.existsSync(python)) {
      const base = opts.python === "py" ? ["py", ["-3.14", "-m", "venv", venv]] : [opts.python, ["-m", "venv", venv]];
      run(base[0], base[1]);
      // The venv must NOT see the user site-packages of the interpreter it was
      // made from, or a build would silently freeze whatever happens to be
      // installed there instead of the pinned requirements.
    }
    const userSite = run(python, ["-c", "import site, sys; print(site.ENABLE_USER_SITE)"], { capture: true }).trim();
    if (userSite === "True") {
      throw new Error(`the build venv ${venv} can see user site-packages; recreate it`);
    }
    if (!opts.skipInstall) {
      run(python, ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"]);
      run(python, ["-m", "pip", "install", "--pre", "-r", reqs]);
      // PySPH is built against the packages just installed; its isolated build
      // fails on 3.14 (requirements-cpu.txt explains).
      run(python, ["-m", "pip", "install", "--pre", "--no-build-isolation",
        "-r", path.join(desktopDir, "backend", "requirements-sph.txt")]);
    }
  }
  const version = run(python, ["-c", "import sys; print(sys.version.split()[0])"], { capture: true }).trim();
  if (!version.startsWith("3.14")) {
    throw new Error(`the backend must be frozen with Python 3.14 (the validated interpreter), got ${version}`);
  }
  const distPath = path.join(buildDir, `backend-${opts.variant}`);
  run(python, [
    "-m", "PyInstaller", path.join(desktopDir, "backend", "jalraksha-backend.spec"),
    "--noconfirm", "--clean", "--distpath", distPath, "--workpath", path.join(buildDir, `pyi-${opts.variant}`),
  ], { env: { ...process.env, JALRAKSHA_BUILD_VARIANT: opts.variant } });

  // Sanity: the frozen exe imports the solver stack and answers the probe.
  // What it answers is reported, not asserted — GPU availability is a fact
  // about the build machine, not about the installer.
  const exe = path.join(distPath, "jalraksha-backend", isWindows ? "jalraksha-backend.exe" : "jalraksha-backend");
  const probe = run(exe, ["probe-backends"], { capture: true, cwd: buildDir });
  console.log(`frozen backend probe on this build machine: ${probe.trim().split(/\r?\n/).pop()}`);
}

function ensureElectronBinary() {
  // Electron's binary arrives through a postinstall script, which some npm
  // configurations skip without an error — observed here on npm 11. Fetch it
  // explicitly rather than failing later inside electron-builder.
  const pathTxt = path.join(desktopDir, "node_modules", "electron", "path.txt");
  if (!fs.existsSync(pathTxt)) {
    run(process.execPath, [path.join(desktopDir, "node_modules", "electron", "install.js")], { cwd: desktopDir });
  }
}

function electronBuilder(opts, info) {
  if (!opts.skipInstall) npm(["ci"], { cwd: desktopDir });
  ensureElectronBinary();
  const outDir = path.join(buildDir, `electron-${opts.variant}`);
  // Installers from earlier commits would otherwise sit beside the new one and
  // make "which file is this build" ambiguous.
  if (fs.existsSync(outDir)) {
    for (const stale of fs.readdirSync(outDir).filter((f) => /-Setup\.(exe|exe\.blockmap)$/.test(f))) {
      fs.rmSync(path.join(outDir, stale));
    }
  }
  const env = { ...process.env, JALRAKSHA_BUILD_VARIANT: opts.variant, JALRAKSHA_GIT_SHA: info.gitSha };
  const args = ["electron-builder", "--win", "--x64", "--config", "electron-builder.config.cjs", "--publish", "never"];
  if (opts.stage === "package") args.push("--dir");
  // electron-builder's CLI through node for the same reason as Vite above.
  args[0] = path.join(desktopDir, "node_modules", "electron-builder", "cli.js");
  run(process.execPath, args, { cwd: desktopDir, env });

  if (opts.stage === "dist") {
    const expected = `+${info.gitSha}-win-x64-${opts.variant.toUpperCase()}-Setup.exe`;
    const installers = fs.readdirSync(outDir).filter((f) => f.endsWith(expected));
    if (installers.length !== 1) {
      throw new Error(`expected one installer ending ${expected} in ${outDir}, found ${installers.join(", ") || "none"}`);
    }
    const target = path.join(repoRoot, "dist", "windows");
    fs.mkdirSync(target, { recursive: true });
    const dest = path.join(target, installers[0]);
    fs.copyFileSync(path.join(outDir, installers[0]), dest);
    const mb = (fs.statSync(dest).size / 1024 / 1024).toFixed(1);
    console.log(`\ninstaller: ${dest} (${mb} MB)`);
  }
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  run(process.execPath, [path.join(desktopDir, "scripts", "sync-version.mjs"), "--check"]);
  const info = writeBuildInfo(opts.variant);
  if (!opts.skipFrontend) buildFrontend(opts);
  else if (!fs.existsSync(path.join(buildDir, "frontend", "index.html"))) {
    throw new Error("--skip-frontend given but desktop/build/frontend has no build");
  }
  if (!opts.skipBackend) buildBackend(opts);
  if (opts.stage !== "build") electronBuilder(opts, info);
}

try {
  main();
} catch (err) {
  console.error(`\nBUILD FAILED: ${err.message}`);
  process.exit(1);
}
