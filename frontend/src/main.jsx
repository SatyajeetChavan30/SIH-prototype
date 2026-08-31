import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";

// Leaflet's stylesheet, bundled rather than pulled from unpkg.com at runtime.
// It was a <link> to a CDN in index.html, which meant the map rendered as
// unstyled tiles with no zoom control the moment the machine was offline -
// in a project whose whole design premise is offline-first demo day.
import "leaflet/dist/leaflet.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
