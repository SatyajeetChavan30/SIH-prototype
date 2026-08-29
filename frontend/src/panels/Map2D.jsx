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
export default function Map2D({ dam = DAM, gauges = GAUGES, reach, result }) {
  // `reach` defaulted to "tehri" and App.jsx never passed it, so the SAR
  // layer showed the Tehri reach whichever dam was selected. It follows the
  // selected dam now, falling back only until /dams resolves.
  const sarReach = reach || dam.id || "tehri";
  const { current } = useSimulationClock();
  const bounds = current?.bounds; // [west, south, east, north] WGS84

  const [sar, setSar] = useState(null);
  const [showSar, setShowSar] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getSar(sarReach)
      .then((d) => { if (!cancelled) setSar(d); })
      .catch((e) => { if (!cancelled) setSar({ source: "unavailable", reason: String(e) }); });
    return () => { cancelled = true; };
  }, [sarReach]);

  const sarObserved = sar && sar.source !== "unavailable" && sar.bbox && sar.observed_extent_url;

  return (
    <div style={{ position: "relative", height: "100%", width: "100%" }}>
      <MapContainer
        // key= forces a remount when the dam changes: MapContainer treats
        // `center` as an initial value only and will not recentre on its own.
        key={`${dam.lat},${dam.lon}`}
        center={[dam.lat, dam.lon]}
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

        <CircleMarker center={[dam.lat, dam.lon]} radius={8} pathOptions={{ color: "red" }}>
          <Tooltip>{dam.name}{dam.height_m ? ` (${dam.height_m} m)` : ""}</Tooltip>
        </CircleMarker>

        {gauges.map((g) => (
          // A gauge carrying a `note` is flagged amber, not hidden. Baramati is
          // inside Khadakwasla's domain but off its river, and a viewer reading
          // "no arrival" there deserves to see why.
          <CircleMarker key={g.name} center={[g.lat, g.lon]} radius={6}
                        pathOptions={{ color: g.note ? "#e65100" : "blue" }}>
            <Tooltip>
              {g.name} — {g.distance_km} km{g.river ? ` (${g.river})` : ""}
              {g.note ? <div style={{ maxWidth: 260 }}>⚠ {g.note}</div> : null}
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>

      <SarStatus sar={sar} show={showSar} onToggle={() => setShowSar((v) => !v)} />
      <HazardLegend
        hazard={current?.hazard_summary || result?.hazard_summary}
        grid={result?.grid}
      />
    </div>
  );
}

/**
 * Depth-hazard colour key for the flood overlay.
 *
 * The keyframe PNGs are coloured by jalraksha.impact.hazard.HazardClassifier,
 * and every keyframe already carries a `hazard_summary` with each level's
 * colour, cell count and share of the domain. None of it was rendered, so the
 * map showed a coloured flood with no way to read what the colours meant.
 *
 * Colours are taken from the payload rather than hardcoded here, so the legend
 * cannot drift from the classifier that actually painted the pixels.
 */
function HazardLegend({ hazard, grid }) {
  if (!hazard) return null;
  const levels = ["low", "moderate", "significant", "severe", "extreme"];

  // Share of the FLOODED area, not of the whole domain.
  //
  // HazardClassifier.summarize() divides every class count by
  // classification.size — every cell in the domain, dry included. On a real
  // run that is overwhelmingly dry: the drain run floods 349 of 72,900 cells,
  // so a class holding 41% of the water displays as 0.2%, and the shallower
  // classes round away to nothing. The legend then reads as though the flood
  // is one uniform severity that stops dead at its edge, which is both wrong
  // and the opposite of what the data says — that flood has a full gradient
  // from 10% low through 29% severe.
  //
  // Recomputed here from the per-level `count`, which every keyframe manifest
  // already stores. That deliberately avoids changing summarize()'s persisted
  // `percentage` field, and it means runs exported before this fix display
  // correctly too, with no backfill.
  const wetCells = levels.reduce((sum, l) => sum + (hazard[l]?.count || 0), 0);
  if (!wetCells) return null;

  const rows = levels
    .filter((l) => (hazard[l]?.count || 0) > 0)
    .map((l) => ({
      name: l,
      share: (hazard[l].count / wetCells) * 100,
      color: `rgb(${(hazard[l].color || [128, 128, 128]).join(",")})`,
    }));
  if (rows.length === 0) return null;

  // Severity over the water only. The stored weighted_hazard_index divides by
  // the whole domain too, so it reads 0.002 for a genuinely dangerous flood.
  const weighted =
    levels.reduce((sum, l) => sum + (hazard[l]?.weight || 0) * (hazard[l]?.count || 0), 0) /
    wetCells;

  // Absolute extent, so the domain share it used to show is still available —
  // just labelled as what it is rather than standing in for composition.
  const cellKm2 = grid?.dx && grid?.dy ? (grid.dx * grid.dy) / 1e6 : null;
  const floodedKm2 = cellKm2 ? wetCells * cellKm2 : null;
  const domainShare = hazard.total_cells
    ? (wetCells / hazard.total_cells) * 100
    : null;

  return (
    <div style={{
      position: "absolute", bottom: 20, left: 8, zIndex: 1000,
      background: "rgba(255,255,255,0.94)", border: "1px solid #bbb",
      borderRadius: 4, padding: "7px 9px", fontSize: 10, lineHeight: 1.5,
      minWidth: 150,
    }}>
      <div style={{ fontWeight: 700 }}>Flood hazard (FD2320)</div>
      <div style={{ color: "#777", marginBottom: 4 }}>share of flooded area</div>
      {rows.map((r) => (
        <div key={r.name} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 12, height: 12, background: r.color,
                         border: "1px solid #999", flexShrink: 0 }} />
          <span style={{ flex: 1, textTransform: "capitalize" }}>{r.name}</span>
          <span style={{ color: "#666" }}>
            {r.share < 0.5 ? "<1%" : `${Math.round(r.share)}%`}
          </span>
        </div>
      ))}
      <div style={{ marginTop: 5, paddingTop: 4, borderTop: "1px solid #eee",
                    color: "#555" }}>
        {floodedKm2 != null && (
          <div>Flooded <strong>{floodedKm2.toFixed(2)} km²</strong>
            {domainShare != null ? ` — ${domainShare.toFixed(1)}% of domain` : ""}
          </div>
        )}
        <div>Severity index <strong>{weighted.toFixed(2)}</strong> (over water)</div>
      </div>
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
  const [expanded, setExpanded] = React.useState(false);
  if (!sar) return null;

  const unavailable = sar.source === "unavailable";
  const cached = sar.source === "cached";

  // A refusal is a STATUS, not an error, and it was rendering as a large orange
  // block covering a quarter of the map. Earth Engine fetched a real Sentinel-1
  // scene, scored its mask at 0.486 precision against JRC permanent water,
  // and declined to show it — the quality guard working exactly as intended.
  // Collapsed to one line, expandable, because the full reason is worth reading
  // but not worth dominating the view.
  if (unavailable && !expanded) {
    return (
      <div
        role="status"
        onClick={() => setExpanded(true)}
        title="Click for the full reason"
        style={{
          position: "absolute", top: 8, right: 8, zIndex: 1000,
          padding: "4px 9px", borderRadius: 4, cursor: "pointer",
          background: "rgba(255,255,255,0.94)", border: "1px solid #b0863a",
          fontSize: 11, color: "#7a3e00", maxWidth: 260,
        }}
      >
        Sentinel-1: no usable mask for this reach ⓘ
      </div>
    );
  }

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
