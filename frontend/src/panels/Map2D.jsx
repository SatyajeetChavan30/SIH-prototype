import React from "react";
import { MapContainer, TileLayer, ImageOverlay, CircleMarker, Tooltip } from "react-leaflet";
import { useSimulationClock } from "../state/SimulationClock.jsx";
import { DAM, GAUGES } from "../data/entities.js";

/**
 * 2D panel — Leaflet map consuming the SAME inundation polygons / keyframe PNGs
 * the existing export produces (brief §5.4, functional parity with Streamlit Tab 1).
 * The active keyframe is driven by the shared SimulationClock, so it stays in
 * lock-step with the 3D view.
 */
export default function Map2D() {
  const { current } = useSimulationClock();
  const bounds = current?.bounds; // [west, south, east, north] WGS84

  return (
    <MapContainer
      center={[DAM.lat, DAM.lon]}
      zoom={11}
      style={{ height: "100%", width: "100%" }}
    >
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap" />

      {bounds && (
        <ImageOverlay
          url={current.png_url}
          bounds={[[bounds[1], bounds[0]], [bounds[3], bounds[2]]]}
          opacity={0.7}
        />
      )}

      <CircleMarker center={[DAM.lat, DAM.lon]} radius={8} pathOptions={{ color: "red" }}>
        <Tooltip>{DAM.name} ({DAM.height_m} m)</Tooltip>
      </CircleMarker>

      {GAUGES.map((g) => (
        <CircleMarker key={g.name} center={[g.lat, g.lon]} radius={6}
                      pathOptions={{ color: "blue" }}>
          <Tooltip>{g.name} — {g.distance_km} km</Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
