import React from "react";
import { Caveat } from "../ui/index.jsx";

/**
 * "No solver ran."
 *
 * scripts/make_synthetic_demo_run.py paints a prescribed wave onto the real
 * Copernicus DEM so the long-reach picture follows the actual valley. It is
 * labelled three times over — the run name, a caption burned into every
 * keyframe PNG, and is_synthetic in its params and run_summary.json — so that
 * no single omission unlabels it. This is the dashboard's copy of that label:
 * above every tab, like the DEM-update banner, because the painted wave is
 * visible on the 2D and 3D views whether or not anything says what it is.
 *
 * Renders nothing for a real run.
 */
export default function SyntheticRunBanner({ result }) {
  if (!result?.is_synthetic) return null;
  return (
    <Caveat tone="danger" strip role="alert" title="SYNTHETIC — NOT A REAL SIMULATION">
      {result.synthetic_note ||
        "No solver ran for this run. The flood shown was prescribed, not computed."}
    </Caveat>
  );
}
