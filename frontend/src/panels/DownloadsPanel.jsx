import React from "react";
import { resolveApiUrl } from "../api.js";
import { DataTable, Empty } from "../ui/index.jsx";

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
    id: "terrain",
    title: "Terrain — modified DEM",
    blurb:
      "Present only when this run's terrain was changed. Copernicus GLO-30 " +
      "with a landslide barrier burned into it — NOT photogrammetry, not " +
      "InSAR, and not a survey. Every pixel outside the barrier footprint is " +
      "bit-identical to the Copernicus source; the sidecar JSON records what " +
      "was modified, from which observation, and the lake's stage-storage curve.",
    match: (kind) => kind.startsWith("dem_update"),
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
  shp_hazard_moderate_zip: "Hazard class — moderate",
  shp_hazard_significant_zip: "Hazard class — significant",
  // Runs exported before the FD2320 unification carry the old class names.
  // They are still in the shipped database and the run picker loads them, so
  // they keep a label rather than falling back to a de-underscored kind.
  shp_hazard_medium_zip: "Hazard class — medium (pre-FD2320-unification run)",
  shp_hazard_high_zip: "Hazard class — high (pre-FD2320-unification run)",
  shp_hazard_extreme_zip: "Hazard class — extreme",
  kml_inundation: "Inundation envelope",
  kml_animation: "Time-animated flood wave",
  kmz_depth_overlay: "Maximum-depth ground overlay (KMZ)",
  keyframe_manifest: "Keyframe manifest",
  xdmf: "ParaView 3D dataset (XDMF)",
  comparison_metrics: "Comparison metrics (JSON)",
  run_summary: "Run summary (JSON)",
  population_at_risk: "Population at risk (JSON)",
  impact: "Economic damage by sector (JSON)",
  sph_near_field: "Near-field SPH summary (JSON)",
  dem_update: "Observation-conditioned DEM (GeoTIFF)",
  dem_update_provenance: "DEM modification provenance (JSON)",
  dem_update_lake: "Impounded lake extent — initial condition, not a solver output",
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
    return <Empty>Run a simulation first, or load a run id.</Empty>;
  }

  const exports = result.exports || [];
  if (!exports.length) {
    return (
      <Empty>
        This run recorded no export products. A run only records an export once the file is verified on disk, so an empty list means nothing was written — check the worker log for [FAIL] lines.
      </Empty>
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
    <div className="jr-page">
      <h3 className="jr-h1">Downloads — {result.dam_name}</h3>
      <p className="jr-lede jr-measure">
        {exports.length} products for run <code>{result.run_id}</code>. All
        coordinates are metric UTM except the KML/KMZ, which are WGS84 as the
        format requires. Tier-1 screening outputs from 30&nbsp;m Copernicus
        GLO-30 — read the arrival times and inundation extent; point depths are
        indicative only.
      </p>

      {grouped.map((group) => (
        <section key={group.id} className="jr-section jr-measure">
          <h4 className="jr-h2">{group.title}</h4>
          <p className="jr-lede">{group.blurb}</p>
          <DataTable>
            <tbody>
              {group.items.map((e) => (
                <tr key={e.kind}>
                  <td>{label(e.kind)}</td>
                  <td className="file">
                    {filename(e.path_or_url)}
                  </td>
                  <td className="num">
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
          </DataTable>
        </section>
      ))}
    </div>
  );
}
