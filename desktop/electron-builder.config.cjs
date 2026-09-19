// electron-builder configuration for the JalRaksha Windows installer.
//
// Driven by desktop/scripts/build.mjs, which sets JALRAKSHA_BUILD_VARIANT and
// JALRAKSHA_GIT_SHA and stages build/frontend, build/backend-<variant> and
// build/build-info-<variant>.json before calling electron-builder.
//
// No auto-update: `publish` is null and no updater is wired. A new installer is
// produced by CI for every change instead (.github/workflows/windows-installer.yml).
"use strict";

const variant = (process.env.JALRAKSHA_BUILD_VARIANT || "cpu").toLowerCase();
if (!["cpu", "gpu"].includes(variant)) {
  throw new Error(`JALRAKSHA_BUILD_VARIANT must be cpu or gpu, not ${variant}`);
}
const sha = process.env.JALRAKSHA_GIT_SHA || "nogit";

module.exports = {
  appId: "in.sih2026.jalraksha",
  productName: "JalRaksha",
  executableName: "JalRaksha",
  copyright: "JalRaksha Team (SIH 2026)",
  directories: {
    output: `build/electron-${variant}`,
    buildResources: "resources",
  },
  // The shell only. The dashboard and the backend are resources, not app code.
  files: ["electron/**/*", "package.json"],
  asar: true,
  extraResources: [
    { from: "build/frontend", to: "frontend" },
    { from: `build/backend-${variant}/jalraksha-backend`, to: "backend" },
    { from: `build/build-info-${variant}.json`, to: "build-info.json" },
  ],
  electronLanguages: ["en-US"],
  compression: "normal",
  publish: null,
  win: {
    target: [{ target: "nsis", arch: ["x64"] }],
    // Unsigned unless CSC_LINK / CSC_KEY_PASSWORD are provided (desktop/README.md).
    signAndEditExecutable: true,
  },
  nsis: {
    oneClick: false,
    // Default install is per-user (no admin prompt); the installer offers
    // "all users" (Program Files) too. User data never goes in either place.
    perMachine: false,
    allowElevation: true,
    allowToChangeInstallationDirectory: true,
    createStartMenuShortcut: true,
    createDesktopShortcut: false,
    shortcutName: "JalRaksha",
    uninstallDisplayName: `JalRaksha \${version} (${variant.toUpperCase()})`,
    // %LOCALAPPDATA%\JalRaksha holds the user's runs and imported packs; an
    // uninstall must not destroy them.
    deleteAppDataOnUninstall: false,
    artifactName: `JalRaksha-\${version}+${sha}-win-x64-${variant.toUpperCase()}-Setup.\${ext}`,
  },
};
