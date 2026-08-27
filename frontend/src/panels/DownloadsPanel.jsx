import React from "react";
import { resolveApiUrl } from "../api.js";

/**
 * Downloads tab — the problem statement's ".shp or .Kml" deliverable, made
 * reachable in one click.
 *
 * Everything here comes from GET /runs/{id}/result's `exports` array. The
 * worker only records a row once the file has been verified on disk
 * (jalraksha.run.write_export_products, then _existing_exports in tasks.py),
 * so a link rendered here is backed by bytes. Nothing is invented client-side:
 * if a product is missing from the array it is missing from this list, which is
 * the honest reading — previously the exports table named four GeoTIFFs that
 * no code ever wrote and the API served 404s for all of them.
 */

const GROUPS = [
  {
    id: "vector",
    title: "Vector — Shapefile (.shp)",
    blurb:
      "Zipped ESRI Shapefile bundles. Each archive holds .shp/.shx/.dbf/.prj — " +
      "a bare .shp carries no attributes and no CRS, so it is served zipped. " +
      "Opens directly in QGIS or ArcGIS.",
    match: (kind) => kind.startsWith("shp_"),
  },
  {
    id: "earth",
    title: "Google Earth — KML / KMZ",
    blurb:
      "WGS84 lat/lon. The animation carries TimeSpan elements — open it in " +
      "Google Earth and use the time slider to watch the wave advance.",
    match: (kind) => kind.startsWith("kml_") || kind.startsWith("kmz_"),
  },
  {
    id: "raster",
    title: "Raster — Cloud-Optimized GeoTIFF (.tif)",
    blurb:
      "Ensemble median plus 5th/95th percentile bands for maximum depth, " +
      "maximum speed and arrival time, in the domain's UTM CRS.",
    match: (kind) => kind.startsWith("cog_"),
  },
  {
    id: "other",
    title: "Other artifacts",
    blurb: "Playback manifest, 3D dataset and comparison metrics.",
    match: () => true, // catch-all; evaluated last
  },
];

// Human-readable names for the export kinds, so the list does not read as
// filenames. Anything unmatched falls back to a de-underscored kind.
const LABELS = {
  shp_inundation_zip: "Inundation envelope",
  shp_arrival_contours_zip: "Arrival-time contours (isochrones)",
  shp_hazard_low_zip: "Hazard class — low",
  shp_hazard_medium_zip: "Hazard class — medium",
  shp_hazard_high_zip: "Hazard class — high",
  shp_hazard_extreme_zip: "Hazard class — extreme",
  kml_inundation: "Inundation envelope",
  kml_animation: "Time-animated flood wave",
  kmz_depth_overlay: "Maximum-depth ground overlay (KMZ)",
  keyframe_manifest: "Keyframe manifest",
  xdmf: "ParaView 3D dataset (XDMF)",
  comparison_metrics: "Comparison metrics (JSON)",
};

function label(kind) {
  if (LABELS[kind]) return LABELS[kind];
  if (kind.startsWith("cog_")) {
    const rest = kind.slice(4);
    const pct = rest.endsWith("_median")
      ? "median"
      : rest.endsWith("_p05")
      ? "5th percentile"
      : rest.endsWith("_p95")
      ? "95th percentile"
      : "";
    const variable = rest
      .replace(/_(median|p05|p95)$/, "")
      .replace("h_max", "Maximum depth")
      .replace("v_max", "Maximum speed")
      .replace("t_arrival", "Arrival time");
    return pct ? `${variable} — ${pct}` : variable;
  }
  return kind.replace(/_/g, " ");
}

function filename(pathOrUrl) {
  return String(pathOrUrl).split("/").pop();
}

export default function DownloadsPanel({ result }) {
  if (!result) {
    return <Empty text="Run a simulation first, or load a run id." />;
  }

  const exports = result.exports || [];
  if (!exports.length) {
    return (
      <Empty text="This run recorded no export products. A run only records an export once the file is verified on disk, so an empty list means nothing was written — check the worker log for [FAIL] lines." />
    );
  }

  // Assign each export to the first group that claims it.
  const claimed = new Set();
  const grouped = GROUPS.map((group) => {
    const items = exports.filter((e) => {
      if (claimed.has(e.kind)) return false;
      if (!group.match(e.kind)) return false;
      claimed.add(e.kind);
      return true;
    });
    return { ...group, items };
  }).filter((g) => g.items.length);

  return (
    <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
      <h3>Downloads — {result.dam_name}</h3>
      <p style={{ fontSize: 12, color: "#555", maxWidth: 680 }}>
        {exports.length} products for run <code>{result.run_id}</code>. All
        coordinates are metric UTM except the KML/KMZ, which are WGS84 as the
        format requires. Tier-1 screening outputs from 30&nbsp;m Copernicus
        GLO-30 — read the arrival times and inundation extent; point depths are
        indicative only.
      </p>

      {grouped.map((group) => (
        <section key={group.id} style={{ marginTop: 20 }}>
          <h4 style={{ marginBottom: 4 }}>{group.title}</h4>
          <div style={{ fontSize: 12, color: "#666", maxWidth: 680, marginBottom: 8 }}>
            {group.blurb}
          </div>
          <table style={{ borderCollapse: "collapse", width: "100%", maxWidth: 680 }}>
            <tbody>
              {group.items.map((e) => (
                <tr key={e.kind} style={{ borderBottom: "1px solid #eee" }}>
                  <td style={{ padding: "6px 8px 6px 0" }}>{label(e.kind)}</td>
                  <td style={{ padding: "6px 8px", fontSize: 11, color: "#888" }}>
                    {filename(e.path_or_url)}
                  </td>
                  <td style={{ padding: "6px 0", textAlign: "right" }}>
                    <a
                      href={resolveApiUrl(e.path_or_url)}
                      download={filename(e.path_or_url)}
                    >
                      Download
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}

function Empty({ text }) {
  return <div style={{ padding: 24, color: "#777", maxWidth: 620 }}>{text}</div>;
}
