/**
 * FD2320 hazard classes, as the dashboard sees them.
 *
 * The authority is floodview/impact/hazard.py — HR = depth * (|V| + 0.5) + DF,
 * classed at 0.75 / 1.25 / 2.5. This file exists only so the panels that read a
 * stored `hazard_summary` agree with each other; it must never grow a threshold
 * of its own. Colours come from the payload, not from here.
 */

/** The four published wet categories, shallowest first. */
export const HAZARD_LEVELS = ["low", "moderate", "significant", "extreme"];

/**
 * Fold a pre-unification summary onto the current level set.
 *
 * Runs exported before the unification carry a fifth "severe" bucket between
 * significant and extreme. FD2320 publishes four wet categories and no boundary
 * that would split extreme, so the level was retired — but those runs are still
 * in the shipped database and the run picker loads them, and a level that is
 * simply not read would drop its cells out of both the bars and the wet-cell
 * denominator. Silently losing a stored run's flood is worse than showing it in
 * the next class up, so `severe` is folded into EXTREME.
 *
 * @param {object|null|undefined} hazard A stored hazard_summary.
 * @returns {object|null|undefined} The same object when there is nothing to fold.
 */
export function foldLegacyLevels(hazard) {
  const legacy = hazard?.severe?.count || 0;
  if (!legacy) return hazard;
  return {
    ...hazard,
    extreme: {
      ...(hazard.extreme || {}),
      count: (hazard.extreme?.count || 0) + legacy,
    },
  };
}
