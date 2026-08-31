// FALLBACK dam geometry, used only until GET /dams resolves.
//
// This file used to be the truth: the map, the gauge markers and the camera
// presets all read these constants, so every panel showed the Tehri corridor no
// matter which dam was selected. The dam and its downstream gauges now come
// from the API (GET /dams publishes a `gauges` array per dam, sourced from
// jalraksha.presets.GAUGES), and these constants exist only so the first paint
// has something real to draw instead of flashing empty.
//
// Keep them consistent with the tehri preset. Do NOT add new dams here.
export const DAM = {
  id: "tehri",
  name: "Tehri Dam",
  lat: 30.3789,
  lon: 78.4789,
  height_m: 260,
  storage_mm3: 3540,
};

export const GAUGES = [
  { name: "Koteshwar", distance_km: 13.0, lat: 30.3167, lon: 78.4833, river: "Bhagirathi" },
  { name: "Devprayag", distance_km: 28.0, lat: 30.15, lon: 78.6, river: "Ganga" },
  { name: "Rishikesh", distance_km: 34.8, lat: 30.0869, lon: 78.2676, river: "Ganga" },
  { name: "Haridwar", distance_km: 58.4, lat: 29.9457, lon: 78.1642, river: "Ganga" },
];

/**
 * Camera fly-to presets (brief §5.5.5) for a given dam — dam site, each gauge,
 * then a catchment overview.
 *
 * Was a module-level CAMERA_PRESETS constant built from the Tehri literals
 * above, which meant the 3D view's fly-to list named Himalayan towns while
 * showing Pune. It has to be derived per dam, so it is a function.
 *
 * The overview height scales with the dam's own domain radius: a 100 km domain
 * framed at Tehri's fixed 90 km altitude cuts off its own furthest gauge.
 */
export function camerasFor(dam = DAM, gauges = GAUGES) {
  const radiusKm = dam.domain_radius_km || 60;
  return [
    { id: "dam", label: "Dam site", lon: dam.lon, lat: dam.lat, height: 12000 },
    ...gauges.map((g) => ({
      id: g.name,
      label: g.name,
      lon: g.lon,
      lat: g.lat,
      height: 9000,
    })),
    {
      id: "overview",
      label: "Catchment overview",
      // Centred on the dam rather than a hardcoded point, so it frames
      // whichever catchment is actually loaded.
      lon: dam.lon,
      lat: dam.lat,
      height: Math.round(radiusKm * 1500),
    },
  ];
}
