import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import cesium from "vite-plugin-cesium";

// API + tile server URLs are injected at build time from the compose environment.
// vite-plugin-cesium copies Cesium's Workers/Assets/Widgets/ThirdParty static
// files and sets window.CESIUM_BASE_URL — without it resium/cesium fail at
// runtime under Vite (missing workers, missing widget CSS).
export default defineConfig({
  plugins: [react(), cesium()],
  server: { port: 3000 },
  define: {
    "import.meta.env.VITE_API_URL": JSON.stringify(process.env.VITE_API_URL || "http://localhost:8000"),
    // Default to the API's own /tiles mount so local dev needs no separate tile
    // server. Docker Compose overrides this with the nginx `tiles` service.
    "import.meta.env.VITE_TILES_URL": JSON.stringify(process.env.VITE_TILES_URL || "http://localhost:8000/tiles"),
    "import.meta.env.VITE_CESIUM_ION_TOKEN": JSON.stringify(process.env.VITE_CESIUM_ION_TOKEN || ""),
    "import.meta.env.VITE_CESIUM_ION_ASSET_ID": JSON.stringify(process.env.VITE_CESIUM_ION_ASSET_ID || ""),
  },
});
