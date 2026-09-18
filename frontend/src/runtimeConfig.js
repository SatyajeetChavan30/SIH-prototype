// Where the dashboard finds its API, tiles and Cesium settings, decided at RUN
// time rather than baked in at build time.
//
// Two hosts load this bundle:
//
//   * A browser (Vite dev server, Docker Compose, any web deployment). Nothing
//     is injected, so the build-time VITE_* values apply exactly as before —
//     vite.config.js still defines them, and their defaults are unchanged.
//   * The Windows desktop app (desktop/). Its backend listens on whatever
//     localhost port was free at launch, so no build-time URL can be right.
//     desktop/electron/preload.js exposes a frozen, read-only
//     `window.jalrakshaDesktop` object before this module runs, and its values
//     win. The desktop build also bakes NO Cesium token into the bundle: the
//     token reaches the page from the user's own desktop.json at runtime, so an
//     installer never carries anyone's credential.
//
// Read once at module load, which is safe for both hosts: the preload script
// runs before any page script.
const desktop =
  typeof window !== "undefined" && window.jalrakshaDesktop ? window.jalrakshaDesktop : null;

const pick = (desktopValue, buildValue, fallback = "") =>
  desktopValue || buildValue || fallback;

export const IS_DESKTOP = Boolean(desktop);

export const API_URL = pick(
  desktop?.apiUrl, import.meta.env.VITE_API_URL, "http://localhost:8000");

export const TILES_URL = pick(
  desktop?.tilesUrl, import.meta.env.VITE_TILES_URL, "http://localhost:8080");

export const CESIUM_ION_TOKEN = pick(
  desktop?.cesiumIonToken, import.meta.env.VITE_CESIUM_ION_TOKEN);

export const CESIUM_ION_ASSET_ID = pick(
  desktop?.cesiumIonAssetId, import.meta.env.VITE_CESIUM_ION_ASSET_ID);
