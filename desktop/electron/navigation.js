// What the desktop window may navigate to.
//
// The window shows the dashboard and nothing else. Every navigation request is
// classified here, in one pure function the tests exercise directly:
//
//   allow     same origin as the dashboard (reloads, in-app anchors)
//   download  a file the API serves (/files/...) — saved through a dialog
//             instead of replacing the dashboard with a raw GeoTIFF or JSON
//   external  an https link (e.g. an attribution) — opened in the user's browser
//   deny      everything else: other schemes, other API paths, other hosts
"use strict";

function originOf(url) {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

/**
 * @param {string} targetUrl
 * @param {{uiOrigin: string, apiOrigin: string}} origins
 * @returns {"allow"|"download"|"external"|"deny"}
 */
function classifyNavigation(targetUrl, { uiOrigin, apiOrigin }) {
  let parsed;
  try {
    parsed = new URL(targetUrl);
  } catch {
    return "deny";
  }
  if (parsed.origin === uiOrigin) return "allow";
  if (parsed.origin === apiOrigin) {
    return parsed.pathname.startsWith("/files/") ? "download" : "deny";
  }
  if (parsed.protocol === "https:") return "external";
  return "deny";
}

module.exports = { classifyNavigation, originOf };
