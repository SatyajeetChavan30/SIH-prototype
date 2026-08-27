import React, { useEffect, useState } from "react";
import { MapContainer, TileLayer, ImageOverlay, CircleMarker, Tooltip } from "react-leaflet";
import { useSimulationClock } from "../state/SimulationClock.jsx";
import { DAM, GAUGES } from "../data/entities.js";
import { getSar, resolveApiUrl } from "../api.js";

/**
 * 2D panel — Leaflet map consuming the SAME inundation polygons / keyframe PNGs
 * the existing export produces (brief §5.4).
 * The active keyframe is driven by the shared SimulationClock, so it stays in
 * lock-step with the 3D view.
 *
 * It also shows the OBSERVED water extent from Sentinel-1 (brief §5.6) beneath
 * the simulated flood, so the two can be compared directly. That layer only
 * appears when a real scene was fetched or cached; when Earth Engine is
 * unavailable the panel says so and draws nothing.
 */
export default function Map2D({ reach = "tehri" }) {
  const { current } = useSimulationClock();
  const bounds = current?.bounds; // [west, south, east, north] WGS84

  const [sar, setSar] = useState(null);
  const [showSar, setShowSar] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getSar(reach)
      .then((d) => { if (!cancelled) setSar(d); })
      .catch((e) => { if (!cancelled) setSar({ source: "unavailable", reason: String(e) }); });
    return () => { cancelled = true; };
  }, [reach]);

  const sarObserved = sar && sar.source !== "unavailable" && sar.bbox && sar.observed_extent_url;

  return (
    <div style={{ position: "relative", height: "100%", width: "100%" }}>
      <MapContainer
        center={[DAM.lat, DAM.lon]}
        zoom={11}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap" />

        {/* Observed water FIRST, so the simulated flood draws on top of it. */}
        {sarObserved && showSar && (
          <ImageOverlay
            url={resolveApiUrl(sar.observed_extent_url)}
            crossOrigin="anonymous"
            bounds={[[sar.bbox[1], sar.bbox[0]], [sar.bbox[3], sar.bbox[2]]]}
            opacity={0.55}
          />
        )}

        {bounds && (
          // crossOrigin is not cosmetic: Scene3D loads these exact same keyframe
          // PNGs through Cesium, which requests them as CORS requests. Without
          // this, Leaflet's plain <img> fetches them with no Origin header, the
          // browser caches a copy carrying no Access-Control-Allow-Origin, and
          // Cesium is then blocked reusing that cached copy — so whichever panel
          // loaded first decided whether the other one worked.
          <ImageOverlay
            url={current.png_url}
            crossOrigin="anonymous"
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

      <SarStatus sar={sar} show={showSar} onToggle={() => setShowSar((v) => !v)} />
    </div>
  );
}

/**
 * Says what the observed layer is, and — when there isn't one — why.
 *
 * Deliberately explicit that this is observed WATER, not an observed flood. On
 * an ordinary day the Sentinel-1 mask over Tehri is the reservoir and the
 * Bhagirathi channel, because those are water. Labelling it "observed flood"
 * would turn a correct measurement into a false claim.
 */
export function SarStatus({ sar, show, onToggle }) {
  if (!sar) return null;

  const unavailable = sar.source === "unavailable";
  const cached = sar.source === "cached";

  return (
    <div
      role="status"
      style={{
        position: "absolute", top: 8, right: 8, zIndex: 1000,
        maxWidth: 340, padding: "8px 10px", borderRadius: 4,
        background: "rgba(255,255,255,0.94)",
        border: `2px solid ${unavailable ? "#e65100" : cached ? "#f9a825" : "#1565C0"}`,
        fontSize: 11, lineHeight: 1.35,
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 4 }}>
        {unavailable
          ? "⚠️ No observed SAR extent"
          : cached
          ? "🛰️ Observed water extent — cached scene"
          : "🛰️ Observed water extent — Sentinel-1"}
      </div>

      {unavailable ? (
        <div style={{ color: "#7a3e00" }}>{sar.reason}</div>
      ) : (
        <>
          <div>
            Acquired <strong>{(sar.acquired_at || "").slice(0, 16).replace("T", " ")} UTC</strong>
            {sar.scene_id ? <> · scene <code>{String(sar.scene_id).slice(0, 24)}</code></> : null}
          </div>
          <div>
            VV threshold <strong>{sar.threshold_db?.toFixed?.(2)} dB</strong>
            {sar.threshold_method === "otsu_per_scene" ? " (Otsu, from this scene)" : ""}
            {typeof sar.water_fraction === "number"
              ? ` · ${(sar.water_fraction * 100).toFixed(1)}% water`
              : ""}
          </div>
          <div style={{ marginTop: 4, color: "#555" }}>
            This is observed <strong>water</strong> — reservoir and river included —
            not a detected flood.
          </div>
          {cached && sar.reason && (
            <div style={{ marginTop: 4, color: "#7a5c00" }}>{sar.reason}</div>
          )}
          <label style={{ display: "block", marginTop: 6 }}>
            <input type="checkbox" checked={show} onChange={onToggle} /> Show observed layer
          </label>
        </>
      )}
    </div>
  );
}
