import React from "react";

/**
 * "The terrain you are looking at has been modified."
 *
 * NON-NEGOTIABLE WHENEVER A RUN CARRIES dem_update. The barrier appears in the
 * 3D globe for free, because Scene3D builds its surface from the run's own
 * terrain_elevation and that IS the updated bed. So a viewer sees modified
 * terrain whether or not anything tells them — and unlabelled modified terrain
 * presented as a satellite-derived product is precisely the overclaim this
 * project refuses everywhere else.
 *
 * The wording follows the same discipline as the Delft3D-vs-Delft3D-class
 * label: say what the thing IS, name what it is not, and let the numbers be
 * checkable. A manual run never shows a scene id, because the presence of one
 * is what distinguishes an observation from an assumption.
 */
export default function DemUpdateBanner({ demUpdate }) {
  if (!demUpdate) return null;

  const observed = demUpdate.observation_source !== "manual_operator_input";
  const barrier = demUpdate.barrier || {};
  const lake = demUpdate.lake || {};
  const raster = demUpdate.raster || {};

  return (
    <div
      style={{
        padding: "7px 12px",
        borderBottom: "1px solid #e0b070",
        background: "#fff4e5",
        color: "#5c3000",
        fontSize: 11,
        lineHeight: 1.5,
      }}
    >
      <strong>Terrain modified — observation-conditioned DEM update.</strong>{" "}
      Base: Copernicus GLO-30.{" "}
      {observed ? (
        <>
          Landslide barrier burned in from Sentinel-1 scene{" "}
          <code>{demUpdate.observation_scene_id}</code>
          {demUpdate.observation_acquired_at
            ? `, acquired ${demUpdate.observation_acquired_at}`
            : ""}
          .
        </>
      ) : (
        <>
          Barrier geometry supplied by the operator (
          {fmt(barrier.lat, 4)}, {fmt(barrier.lon, 4)}; crest{" "}
          {fmt(barrier.crest_height_m, 0)} m, width{" "}
          {fmt(barrier.width_m_final, 0)} m).{" "}
          <strong>No satellite observation was used.</strong>
        </>
      )}{" "}
      <strong>This is not photogrammetry and not a survey product.</strong>{" "}
      {fmt(raster.cells_modified, 0)} cells modified, maximum change{" "}
      {Number(raster.max_elevation_change_m) >= 0 ? "+" : ""}
      {fmt(raster.max_elevation_change_m, 1)} m. Impounded lake{" "}
      {fmt(lake.volume_mm3, 2)} MCM over {fmt(lake.area_km2, 2)} km², measured by
      filling the updated DEM — a landslide dam has no published storage.
      {lake.spill_detected_at_m != null && (
        <>
          {" "}
          <strong>
            Lateral spill detected at {fmt(lake.spill_detected_at_m, 1)} m
          </strong>{" "}
          — the usable capacity is capped there, above which the pool escapes
          over a saddle into a neighbouring catchment.
        </>
      )}
      {lake.iou != null && (
        <> Modelled lake vs observed extent: IoU {fmt(lake.iou, 2)}.</>
      )}
    </div>
  );
}

function fmt(value, digits) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
