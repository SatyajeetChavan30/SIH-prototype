/**
 * What produced this run's numbers, read off the run's own payload.
 *
 * Every row names the RunResult path it was read from. That is the point of
 * the Provenance tab: the table is emitted by the run that produced the
 * numbers, not typed into a spreadsheet afterwards, and a reader can check
 * any row against GET /runs/{id}/result.
 *
 * Pure (no React), so `node --test` can pin the one rule that matters most
 * here: a field the run did not record says so, and never renders as a blank
 * that reads like "nothing to report". Runs written before a field existed
 * are still in the shipped database and still load.
 */

export const NOT_RECORDED = "not recorded for this run";

const MINORITY_PREFIX = "MINORITY ARRIVAL";

function text(value) {
  if (value == null || value === "") return null;
  if (Array.isArray(value)) return value.length ? value.join(", ") : null;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : null;
  return String(value);
}

function row(label, value, path) {
  const shown = text(value);
  return { label, value: shown ?? NOT_RECORDED, path, missing: shown == null };
}

// A projected coordinate, not a quantity: no digit grouping, which would read
// "3,61,962" under the en-IN locale the counts below use.
function fmtMetres(value) {
  return value == null ? null : `${Number(value).toFixed(1)} m`;
}

function fmtCount(value) {
  return value == null ? null : Number(value).toLocaleString("en-IN");
}

/**
 * Sections for the Provenance tab. Each is {id, title, rows, caveats}; a
 * caveat is {tone, title, body} in the Caveat component's own tones.
 */
export function provenanceSections(result) {
  if (!result) return [];
  const backend = result.solver_backend || {};
  const engine = result.engine || {};
  const grid = result.grid || {};
  const ensemble = result.ensemble || {};
  const hazard = result.hazard_summary || {};
  const par = result.population_at_risk;
  const impact = result.impact;
  const exposure = impact?.exposure_provenance || {};
  const damage = impact?.damage;
  const gauges = result.gauges || [];

  const run = {
    id: "run",
    title: "Run",
    rows: [
      row("Run id", result.run_id, "run_id"),
      row("Dam", result.dam_name, "dam_name"),
      row("Solver requested", result.solver, "solver"),
      row("Synthetic (no solver ran)", result.is_synthetic, "is_synthetic"),
      row("3D dataset kind", result.paraview_dataset_kind, "paraview_dataset_kind"),
    ],
    caveats: result.is_synthetic
      ? [{
          tone: "danger",
          title: "SYNTHETIC — NOT A REAL SIMULATION",
          body: result.synthetic_note || "No solver ran for this run.",
        }]
      : [],
  };

  const compute = {
    id: "compute",
    title: "Compute",
    rows: [
      row("Computed on", backend.solver_backend_label, "solver_backend.solver_backend_label"),
      row("Why this backend", backend.solver_backend_reason, "solver_backend.solver_backend_reason"),
      row("Device", backend.solver_device, "solver_backend.solver_device"),
      row("Engine", engine.label || engine.name, "engine.label"),
      row("Delft3D FM kernel ran", engine.delft3d_binary_used, "engine.delft3d_binary_used"),
      // Only where something fell back. On a run where the kernel ran, a
      // "not recorded" fallback row reads as a lost explanation.
      ...(engine.fallback_reason
        ? [row("Fallback reason", engine.fallback_reason, "engine.fallback_reason")]
        : []),
      // Only a run that carried a near-field handoff has an SPH engine; a
      // "not recorded" row on every other run would read as a lost field.
      ...(result.sph ? [row("Near-field SPH engine", result.sph.engine_label || result.sph.engine, "sph.engine_label")] : []),
    ],
    // The naming rule in CLAUDE.md: a Delft3D request that fell back must say
    // so. Scoped to runs that asked for Delft3D, where "fallback" means something.
    caveats: engine.delft3d_binary_used === false && ["delft3d", "both"].includes(result.solver)
      ? [{
          tone: "warn",
          title: "JalRaksha built-in 2D SWE — Delft3D-class, NOT Delft3D FM",
          body: engine.fallback_reason || "The Deltares kernel did not run for this result.",
        }]
      : [],
  };

  const demUpdate = result.dem_update;
  const terrain = {
    id: "terrain",
    title: "Terrain",
    rows: [
      row("DEM used", result.dem_used, "dem_used"),
      // dem_used and dem_update are written together (run_summary.json "dem"),
      // so a recorded dem_used makes an absent dem_update a real "no". Without
      // it the run predates the field and nothing can be said either way.
      row("DEM modified for this run",
        demUpdate ? true : (result.dem_used ? false : null), "dem_update"),
      row("Grid (cells)", grid.nx != null && grid.ny != null ? `${grid.nx} × ${grid.ny}` : null, "grid.nx, grid.ny"),
      row("Cell size", grid.dx != null ? `${grid.dx} × ${grid.dy ?? grid.dx} m` : null, "grid.dx, grid.dy"),
      row("CRS", grid.crs, "grid.crs"),
      // A null origin is common on backfilled runs, and it is withheld rather
      // than guessed: a wrong one georeferences every download incorrectly.
      row("Grid origin (x0, y0)",
        grid.x0 != null && grid.y0 != null ? `${fmtMetres(grid.x0)}, ${fmtMetres(grid.y0)}` : null,
        "grid.x0, grid.y0"),
    ],
    caveats: demUpdate
      ? [{
          tone: "info",
          title: "Observation-conditioned DEM update — not a survey",
          body: demUpdate.not_a_survey ||
            "Copernicus GLO-30 with a landslide barrier burned in. Not photogrammetry.",
        }]
      : [],
  };

  const unverified = ensemble.unverified_regressions || [];
  const breach = {
    id: "ensemble",
    title: "Breach ensemble",
    rows: [
      row("Scenario", ensemble.scenario_type, "ensemble.scenario_type"),
      row("Members converged",
        ensemble.num_completed != null && ensemble.num_ensemble != null
          ? `${ensemble.num_completed} of ${ensemble.num_ensemble}` : null,
        "ensemble.num_completed, ensemble.num_ensemble"),
      row("Regressions used", ensemble.regressions_used, "ensemble.regressions_used"),
      row("Unverified regressions", unverified.length ? unverified : (result.ensemble ? "none" : null),
        "ensemble.unverified_regressions"),
      row("Dam type", ensemble.dam_type, "ensemble.dam_type"),
      row("Dam class outside fitted population", ensemble.dam_class_outside_fitted_population,
        "ensemble.dam_class_outside_fitted_population"),
    ],
    caveats: [
      ...(ensemble.uses_unverified_regression
        ? [{
            tone: "warn",
            title: `Unverified regression in this ensemble: ${unverified.join(", ")}`,
            body: ensemble.unverified_regression_note || "",
          }]
        : []),
      ...(ensemble.dam_class_outside_fitted_population
        ? [{
            tone: "warn",
            title: "Dam class outside the regressions' fitted population",
            body: ensemble.dam_class_note || "",
          }]
        : []),
    ],
  };

  const hazardSection = {
    id: "hazard",
    title: "Hazard classification",
    rows: [
      row("Scheme", hazard.scheme, "hazard_summary.scheme"),
      row("Debris factor", hazard.debris_factor, "hazard_summary.debris_factor"),
    ],
    caveats: [],
  };

  const builtUp = exposure.built_up;
  const cropland = exposure.cropland;
  // A sector whose fetch was refused has no provenance block but does have a
  // reason (damage.py's three states per sector). Show the reason, because
  // "not recorded" there would hide a refusal the run did write down.
  const refusal = (sector) => {
    const block = damage?.sectors?.[sector];
    return block && block.available === false ? `refused — ${block.reason}` : null;
  };
  const exposureSection = {
    id: "exposure",
    title: "Exposure and impact",
    rows: [
      row("Population grid",
        par?.available
          ? [par.population_source, par.population_epoch && `epoch ${par.population_epoch}`]
              .filter(Boolean).join(" · ")
          : null,
        "population_at_risk.population_source"),
      // A refusal row only where there was a refusal: on a run with a figure,
      // "not recorded" beside "reason" would read as a lost explanation.
      ...(par && !par.available
        ? [row("Population refusal", par.reason, "population_at_risk.reason")]
        : []),
      row("Built-up exposure",
        builtUp ? [builtUp.source, builtUp.collection].filter(Boolean).join(" · ") : refusal("residential"),
        "impact.exposure_provenance.built_up"),
      row("Cropland exposure",
        cropland ? [cropland.source, cropland.collection].filter(Boolean).join(" · ") : refusal("agricultural"),
        "impact.exposure_provenance.cropland"),
      row("Damage model published", damage ? damage.model_is_published === true : null,
        "impact.damage.model_is_published"),
      row("Sectors without a figure", damage ? (damage.missing_sectors?.length ? damage.missing_sectors : "none") : null,
        "impact.damage.missing_sectors"),
    ],
    caveats: damage && damage.model_is_published === false
      ? [{
          tone: "warn",
          title: "Damage figures use an unpublished depth-damage curve",
          body: "The exposure is measured; the curve shape and the unit costs are UNVETTED. " +
            "Read the rupee figures as an order of magnitude.",
        }]
      : [],
  };

  const nearBoundary = gauges.filter((g) => g.near_boundary).length;
  const minority = gauges.filter((g) => (g.note || "").startsWith(MINORITY_PREFIX)).length;
  const gaugeSection = {
    id: "gauges",
    title: "Gauges",
    rows: [
      row("Gauges reported", gauges.length ? fmtCount(gauges.length) : null, "gauges"),
      row("Shaped by the domain boundary", gauges.length ? fmtCount(nearBoundary) : null,
        "gauges[].near_boundary"),
      row("Minority arrivals", gauges.length ? fmtCount(minority) : null, "gauges[].note"),
    ],
    caveats: [
      ...(nearBoundary
        ? [{
            tone: "warn",
            title: `${nearBoundary} gauge${nearBoundary === 1 ? "" : "s"} near the domain edge`,
            body: "Their depth and arrival are shaped by the outflow boundary as well as by the flood.",
          }]
        : []),
      ...(minority
        ? [{
            tone: "warn",
            title: `${minority} minority arrival${minority === 1 ? "" : "s"}`,
            body: "Fewer than half the ensemble members reached these gauges; the figure is not a median.",
          }]
        : []),
    ],
  };

  return [run, compute, terrain, breach, hazardSection, exposureSection, gaugeSection];
}
