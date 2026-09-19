import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";

// Leaflet's stylesheet, bundled rather than pulled from unpkg.com at runtime.
// It was a <link> to a CDN in index.html, which meant the map rendered as
// unstyled tiles with no zoom control the moment the machine was offline -
// in a project whose whole design premise is offline-first demo day.
import "leaflet/dist/leaflet.css";

// Fonts and the design system, bundled for the same reason: a font fetched from
// a CDN looks right on a connected machine and silently falls back offline.
// Inter carries the UI (it has tabular figures for the gauge and ensemble
// columns), Space Grotesk the wordmark only, IBM Plex Mono run ids and figures.
// Latin subsets only where the package splits them; Inter's variable file ships
// every subset behind unicode-range, so a browser still downloads only Latin.
import "@fontsource-variable/inter/wght.css";
import "@fontsource/space-grotesk/latin-500.css";
import "@fontsource/space-grotesk/latin-700.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/ui.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
