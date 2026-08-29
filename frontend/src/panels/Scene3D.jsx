import React, { useEffect, useRef } from "react";
import { Viewer, Entity } from "resium";
import * as Cesium from "cesium";
import { useSimulationClock } from "../state/SimulationClock.jsx";
import { DAM, GAUGES, camerasFor } from "../data/entities.js";

const TILES = import.meta.env.VITE_TILES_URL || "http://localhost:8080";
const ION_TOKEN = import.meta.env.VITE_CESIUM_ION_TOKEN || "";
const ION_ASSET_ID = import.meta.env.VITE_CESIUM_ION_ASSET_ID || "";
const EPOCH = "2026-01-01T00:00:00Z";

/**
 * Terrain source (§5.5.1). Exact-DEM-match terrain is what keeps the flood
 * overlay from floating through hills or clipping underground — this is the
 * single most common failure mode in dam-break 3D demos. Two sources:
 *   - Cesium ion, if VITE_CESIUM_ION_TOKEN + VITE_CESIUM_ION_ASSET_ID are set
 *     (the conditioned DEM uploaded via tools/cesium/upload_terrain_to_ion.py).
 *   - The self-hosted tileset at {TILES}/terrain, for when a cesium-terrain-
 *     builder pipeline exists.
 * If neither is configured, fall back to Cesium's default ellipsoid and show
 * an on-screen warning — never silently wrong in a demo.
 */
function useTerrainProvider() {
  const [state, setState] = React.useState({ provider: undefined, warning: null });
  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (ION_TOKEN && ION_ASSET_ID) {
        try {
          Cesium.Ion.defaultAccessToken = ION_TOKEN;
          const provider = await Cesium.CesiumTerrainProvider.fromIonAssetId(Number(ION_ASSET_ID));
          if (!cancelled) setState({ provider, warning: null });
          return;
        } catch (err) {
          if (!cancelled) {
            setState({
              provider: undefined,
              warning: `Cesium ion terrain asset ${ION_ASSET_ID} failed to load (${err.message}). Falling back to flat ellipsoid.`,
            });
          }
          return;
        }
      }
      try {
        const provider = await Cesium.CesiumTerrainProvider.fromUrl(`${TILES}/terrain`);
        if (!cancelled) setState({ provider, warning: null });
      } catch {
        if (!cancelled) {
          setState({
            provider: undefined,
            warning:
              "No terrain source configured (set VITE_CESIUM_ION_TOKEN + VITE_CESIUM_ION_ASSET_ID, " +
              "or build a self-hosted tileset at " + TILES + "/terrain). " +
              "Flood overlay is NOT aligned with real topography.",
          });
        }
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);
  return state;
}

/**
 * 3D panel — CesiumJS via resium (brief §5.5, the flagship deliverable).
 *
 * Tier-1 flood overlay (§5.5.3): each keyframe PNG becomes a geo-registered
 * SingleTileImageryProvider layer; the shared SimulationClock selects which one
 * is visible, so scrubbing the 2D slider moves the 3D flood in lock-step.
 * Terrain source is picked by useTerrainProvider() above —
 * Cesium ion (exact DEM match, needs a token) or the self-hosted tileset, with
 * a visible warning if neither is configured.
 *
 * The shared SimulationClock (§5.5.5) drives viewer.clock.currentTime so the
 * 2D and 3D views are one tool.
 */
export default function Scene3D({ dam = DAM, gauges = GAUGES }) {
  const { keyframes, index, currentTimeS } = useSimulationClock();
  const viewerRef = useRef(null);
  const [selected, setSelected] = React.useState("dam");
  const { provider: terrainProvider, warning: terrainWarning } = useTerrainProvider();

  // Build one imagery layer per keyframe, up front, all hidden. Only the layer
  // for the active keyframe is shown (see the effect below) — Cesium has no API
  // that swaps ImageryLayers off its own clock, so the shared SimulationClock
  // drives visibility directly. Pre-building means scrubbing costs a `.show`
  // toggle rather than a network fetch + provider construction per frame.
  const layersRef = useRef([]);
  useEffect(() => {
    const viewer = viewerRef.current?.cesiumElement;
    if (!viewer || !keyframes.length) return;
    let cancelled = false;
    viewer.imageryLayers.removeAll();
    layersRef.current = [];

    (async () => {
      for (const kf of keyframes) {
        // Cesium >= 1.104: the SingleTileImageryProvider constructor requires
        // explicit tileWidth/tileHeight; fromUrl() reads them from the image.
        const provider = await Cesium.SingleTileImageryProvider.fromUrl(kf.png_url, {
          rectangle: Cesium.Rectangle.fromDegrees(kf.bounds[0], kf.bounds[1], kf.bounds[2], kf.bounds[3]),
        });
        if (cancelled || viewer.isDestroyed()) return;
        const layer = viewer.imageryLayers.addImageryProvider(provider);
        layer.show = false;
        layer.alpha = 0.75;
        layersRef.current.push(layer);
      }
    })();

    return () => { cancelled = true; };
  }, [keyframes]);

  // Show only the active keyframe's layer.
  useEffect(() => {
    layersRef.current.forEach((layer, i) => {
      if (layer && !layer.isDestroyed?.()) layer.show = i === index;
    });
  }, [index, keyframes]);

  // Keep the Cesium clock synced to the shared SimulationClock.
  useEffect(() => {
    const viewer = viewerRef.current?.cesiumElement;
    if (!viewer) return;
    const jd = Cesium.JulianDate.addSeconds(
      Cesium.JulianDate.fromIso8601(EPOCH), currentTimeS, new Cesium.JulianDate()
    );
    viewer.clock.currentTime = jd;
  }, [currentTimeS]);

  // Derived per dam, so the fly-to list names the towns actually on screen.
  const cameras = React.useMemo(() => camerasFor(dam, gauges), [dam, gauges]);
  const preset = cameras.find((p) => p.id === selected) || cameras[0];

  // Camera fly-to on preset change (brief §5.5.5).
  useEffect(() => {
    const viewer = viewerRef.current?.cesiumElement;
    if (!viewer) return;
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(preset.lon, preset.lat, preset.height),
      duration: 1.5,
    });
  }, [selected, preset.lon, preset.lat, preset.height]);

  return (
    // position:relative both anchors the absolutely-positioned overlays below
    // and keeps the Cesium canvas inside this pane — resium's `full` prop makes
    // the viewer fill the whole window, which covers the control panel and
    // swallows its clicks.
    <div style={{ height: "100%", width: "100%", position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", zIndex: 10, top: 8, left: 8 }}>
        {cameras.map((p) => (
          <button key={p.id} onClick={() => setSelected(p.id)} style={{ marginRight: 4 }}>
            {p.label}
          </button>
        ))}
      </div>
      {terrainWarning && (
        <div style={{
          position: "absolute", zIndex: 10, bottom: 30, left: 8, right: 8,
          background: "#7a1f1f", color: "white", padding: "6px 10px",
          fontSize: 12, borderRadius: 4,
        }}>
          ⚠ {terrainWarning}
        </div>
      )}
      <Viewer
        ref={viewerRef}
        baseLayerPicker={false}
        terrainProvider={terrainProvider}
        animation={true}
        timeline={true}
        style={{ height: "100%", width: "100%" }}
      >
        <Entity
          position={Cesium.Cartesian3.fromDegrees(dam.lon, dam.lat, 0)}
          point={{ pixelSize: 12, color: Cesium.Color.RED }}
          label={{
            text: dam.height_m ? `${dam.name} (${dam.height_m} m)` : dam.name,
            font: "14px sans-serif",
          }}
        />
        {gauges.map((g) => (
          <Entity
            key={g.name}
            position={Cesium.Cartesian3.fromDegrees(g.lon, g.lat, 0)}
            point={{ pixelSize: 9, color: Cesium.Color.BLUE }}
            label={{ text: `${g.name} — ${g.distance_km} km`, font: "12px sans-serif" }}
          />
        ))}
      </Viewer>
    </div>
  );
}
