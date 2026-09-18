// The only bridge between the desktop shell and the dashboard page.
//
// Sandboxed, context-isolated, and READ-ONLY: it exposes a frozen object of
// plain values — where the API is, the optional Cesium settings, and build
// provenance for display. No function is exposed, so the page gains no shell,
// filesystem or process access through it. Actions that need the shell (import
// a data pack, open the logs folder) live in the application menu instead.
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

const config = ipcRenderer.sendSync("jalraksha:get-runtime-config") || {};

contextBridge.exposeInMainWorld("jalrakshaDesktop", Object.freeze({
  isDesktop: true,
  apiUrl: String(config.apiUrl || ""),
  tilesUrl: String(config.tilesUrl || ""),
  cesiumIonToken: String(config.cesiumIonToken || ""),
  cesiumIonAssetId: String(config.cesiumIonAssetId || ""),
  version: String(config.version || ""),
  gitSha: String(config.gitSha || ""),
  buildTime: String(config.buildTime || ""),
  variant: String(config.variant || ""),
}));
