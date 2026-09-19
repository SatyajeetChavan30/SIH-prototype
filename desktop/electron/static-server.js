// Serves the built React dashboard to the desktop window over http://127.0.0.1.
//
// Why a loopback HTTP server rather than file:// or a custom protocol: the
// production bundle references /assets/... and /cesium/... from the root, and
// Cesium starts Web Workers and fetches its own assets relative to its base URL.
// Both work unmodified from an ordinary http origin. file:// breaks the absolute
// paths and blocks the fetches, and custom schemes have a history of Worker and
// fetch restrictions — so no CORS or file:// workarounds are needed anywhere.
//
// Bound to 127.0.0.1 on a random port, read-only, GET/HEAD only, and every
// request is confined to the frontend directory.
"use strict";

const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const CONTENT_TYPES = Object.freeze({
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".wasm": "application/wasm",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".xml": "application/xml",
  ".txt": "text/plain; charset=utf-8",
  ".glb": "model/gltf-binary",
  ".gltf": "model/gltf+json",
  ".ktx2": "image/ktx2",
  ".b3dm": "application/octet-stream",
  ".bin": "application/octet-stream",
  ".czml": "application/json; charset=utf-8",
  ".kml": "application/vnd.google-earth.kml+xml",
});

/**
 * Map a request path onto a file under root, or null if it escapes root.
 * Exported for tests.
 */
function resolveStaticPath(root, requestUrl) {
  let pathname;
  try {
    pathname = decodeURIComponent(new URL(requestUrl, "http://127.0.0.1").pathname);
  } catch {
    return null;
  }
  if (pathname.includes("\0")) return null;
  const absoluteRoot = path.resolve(root);
  const target = path.resolve(absoluteRoot, `.${pathname}`);
  if (target !== absoluteRoot && !target.startsWith(absoluteRoot + path.sep)) return null;
  return target;
}

/** @returns {Promise<{url: string, close: () => Promise<void>}>} */
function startStaticServer(root) {
  const server = http.createServer((req, res) => {
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.writeHead(405, { Allow: "GET, HEAD" });
      res.end();
      return;
    }
    let target = resolveStaticPath(root, req.url);
    if (!target) {
      res.writeHead(403);
      res.end();
      return;
    }
    fs.stat(target, (err, stat) => {
      if (!err && stat.isDirectory()) {
        target = path.join(target, "index.html");
      }
      fs.stat(target, (err2, stat2) => {
        if (err2 || !stat2.isFile()) {
          res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
          res.end("Not found");
          return;
        }
        const type = CONTENT_TYPES[path.extname(target).toLowerCase()] || "application/octet-stream";
        res.writeHead(200, {
          "Content-Type": type,
          "Content-Length": stat2.size,
          "X-Content-Type-Options": "nosniff",
          // Hashed assets never change for a given install; index.html must
          // always be re-read so an upgrade picks up new asset names.
          "Cache-Control": path.basename(target) === "index.html" ? "no-cache" : "max-age=31536000, immutable",
        });
        if (req.method === "HEAD") {
          res.end();
          return;
        }
        fs.createReadStream(target).pipe(res);
      });
    });
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({
        url: `http://127.0.0.1:${port}`,
        close: () => new Promise((r) => server.close(() => r())),
      });
    });
  });
}

module.exports = { resolveStaticPath, startStaticServer };
