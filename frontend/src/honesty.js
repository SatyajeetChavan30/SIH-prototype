/**
 * Wording for per-gauge honesty labels shared by the Gauges tab and the
 * sidebar, so the two can never describe the same gauge differently.
 */

/**
 * The boundary-proximity label, or null when the gauge is clear of the edge or
 * its distance to the edge is unknown (runs written before the field existed,
 * or whose grid origin was never recorded).
 *
 * The threshold is decided server-side (BOUNDARY_CONTAMINATION_KM in
 * services/api/jalraksha_service/script_runs.py); this only states the result.
 */
export function boundaryNote(gauge) {
  if (!gauge?.near_boundary || gauge.boundary_clearance_km == null) return null;
  return (
    `${gauge.boundary_clearance_km.toFixed(1)} km from the domain edge — its ` +
    "depth and arrival are shaped by the outflow boundary as well as by the " +
    "flood, so it is not a clean measurement."
  );
}
