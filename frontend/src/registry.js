/**
 * Reading a registry row: what the badge says, and why.
 *
 * The server computes readiness (services/api/jalraksha_service/registry.py);
 * this only words it. Every label here has to survive the question "how do you
 * know?", so each one carries the reason the server gave rather than a shape
 * decided on screen.
 *
 * Pure (no React) so `node --test` can pin it.
 */

export const TIERS = {
  verified_run: {
    label: "Verified run",
    tone: "ok",
    blurb: "A run has finished here, with exports on disk.",
  },
  dem_cached: {
    label: "Terrain staged",
    tone: "info",
    blurb: "A DEM covering this domain is cached; no run has finished yet.",
  },
  metadata_only: {
    label: "Metadata only",
    tone: "warn",
    blurb: "Nothing has been staged or solved for this site yet.",
  },
};

/** The badge for a row: {label, tone, blurb, reason}. Unknown tiers say so. */
export function tierBadge(row) {
  const tier = TIERS[row?.tier];
  if (!tier) {
    return { label: "Unknown", tone: "warn", blurb: "", reason: row?.tier_reason || "" };
  }
  return { ...tier, reason: row?.tier_reason || "" };
}

/**
 * The DEM cell. A cached file that does not cover the domain is NOT "cached" on
 * screen: a cache hit says the file exists, not that it contains the domain.
 */
export function demLabel(row) {
  const dem = row?.dem || {};
  if (!dem.cached) return { text: "DEM not cached", ok: false, detail: dem.reason || "" };
  if (!dem.covers_domain) {
    return { text: "Staged, does not cover the domain", ok: false, detail: dem.reason || "" };
  }
  return { text: "Cached and covers the domain", ok: true, detail: dem.path || "" };
}

/**
 * The full-reservoir-level cell. Where no FRL is published the source string is
 * shown INSTEAD of a value — never a number carried over from another dam.
 */
export function frlLabel(row) {
  const frl = row?.frl || {};
  if (frl.frl_m == null) {
    return { text: "not published for this dam", value: null, source: frl.frl_source || "" };
  }
  const crest = frl.crest_m == null ? "" : ` · crest ${frl.crest_m} m`;
  return { text: `${frl.frl_m} m${crest}`, value: frl.frl_m, source: frl.frl_source || "" };
}

/** Rows a run may actually be submitted for. Selecting one never starts a run. */
export function isSelectable(row) {
  return Boolean(row && row.id);
}
