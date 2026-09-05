import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";

// Leaflet's stylesheet, bundled rather than pulled from unpkg.com at runtime.
// It was a <link> to a CDN in index.html, which meant the map rendered as
// unstyled tiles with no zoom control the moment the machine was offline -
// in a project whose whole design premise is offline-first demo day.
import "leaflet/dist/leaflet.css";

// The app's own stylesheet, imported AFTER Leaflet's so app rules win on ties.
// Its element-level defaults (button, input, select, table) are deliberately
// low-specificity for that reason: Leaflet's own chrome is class-scoped
// (.leaflet-control-zoom a, .leaflet-popup-content) and keeps its styling,
// while the app's bare <button>s pick these up.
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
