import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import cesium from "vite-plugin-cesium";

// API + tile server URLs are injected at build time.
//
// vite-plugin-cesium copies Cesium's Workers/Assets/Widgets/ThirdParty static
// files and sets window.CESIUM_BASE_URL — without it resium/cesium fail at
// runtime under Vite (missing workers, missing widget CSS).
//
// WHY loadEnv AND NOT process.env
// -------------------------------
// This config used to read `process.env.VITE_*` directly inside `define`. That
// reads the SHELL environment only — it does not read `.env`, `.env.local` or
// any of the files Vite loads by convention. Worse, because `define` performs a
// literal text substitution, it *overwrote* the values Vite had loaded from
// those files with empty strings. So putting the Cesium Ion token in
// `frontend/.env.local` looked correct, changed nothing, and the 3D globe kept
// rendering Cesium's default-token warning with no terrain.
//
// loadEnv reads the .env files for the current mode and merges them, and
// process.env still wins where it is set — so Docker Compose and CI keep
// working exactly as before while a local .env.local now actually takes effect.
export default defineConfig(({ mode }) => {
  // "" as the third argument loads every variable, not just VITE_-prefixed
  // ones; we only forward the VITE_ ones below.
  const fileEnv = loadEnv(mode, process.cwd(), "");
  const read = (key, fallback = "") =>
    process.env[key] ?? fileEnv[key] ?? fallback;

  return {
    plugins: [react(), cesium()],
    server: { port: 3000 },
    define: {
      "import.meta.env.VITE_API_URL": JSON.stringify(
        read("VITE_API_URL", "http://localhost:8000")),
      // Default to the API's own /tiles mount so local dev needs no separate
      // tile server. Docker Compose overrides this with the nginx `tiles`
      // service.
      "import.meta.env.VITE_TILES_URL": JSON.stringify(
        read("VITE_TILES_URL", "http://localhost:8000/tiles")),
      "import.meta.env.VITE_CESIUM_ION_TOKEN": JSON.stringify(
        read("VITE_CESIUM_ION_TOKEN")),
      "import.meta.env.VITE_CESIUM_ION_ASSET_ID": JSON.stringify(
        read("VITE_CESIUM_ION_ASSET_ID")),
    },
  };
});
