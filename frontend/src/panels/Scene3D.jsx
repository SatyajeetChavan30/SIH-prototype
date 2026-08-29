import React, { useEffect, useRef } from "react";
import { Viewer, Entity } from "resium";
import * as Cesium from "cesium";
import { useSimulationClock } from "../state/SimulationClock.jsx";
import { DAM, GAUGES, camerasFor } from "../data/entities.js";

const TILES = import.meta.env.VITE_TILES_URL || "http://localhost:8080";
const ION_TOKEN = import.meta.env.VITE_CESIUM_ION_TOKEN || "";
const ION_ASSET_ID = import.meta.env.VITE_CESIUM_ION_ASSET_ID || "";
const EPOCH = "2026-01-01T00:00:00Z";

// Set at MODULE scope, before any component renders.
//
// This used to live inside useTerrainProvider's effect. React runs child
// effects before parent ones, so resium had already constructed the Cesium
// Viewer by the time it ran — and that Viewer immediately requested default Ion
// base imagery using Cesium's built-in public token, which is what produced the
// "This application is using Cesium's default ion access token" banner even
// though a real token was configured.
if (ION_TOKEN) {
  Cesium.Ion.defaultAccessToken = ION_TOKEN;
}

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
  // Returns a PROMISE for the provider, not a resolved value from state.
  //
  // This is the whole fix for "the globe renders flat with no terrain and no
  // error". resium's <Viewer> lists `terrainProvider` in its `otherProps` and
  // NOT in its `cesiumProps`, and the Viewer definition has no `update`
  // handler — so resium's generic prop-update path explicitly skips it. The
  // previous arrangement therefore:
  //
  //   1. rendered once with provider === undefined, so the Viewer was built
  //      with an EllipsoidTerrainProvider (a flat globe);
  //   2. resolved the Ion request, called setState, re-rendered —
  //   3. and resium SILENTLY DISCARDED the new provider.
  //
  // Flat globe forever. And because the Ion request had *succeeded*, `warning`
  // stayed null, so there was no banner either — no terrain, no explanation.
  //
  // resium's Viewer `create` does `isPromise(v) ? await v : v`, so handing it
  // the promise gets the provider applied at CONSTRUCTION time, which is the
  // only time the Viewer accepts it. (resium's <Globe> does honour updates;
  // <Viewer> does not.)
  const [warning, setWarning] = React.useState(null);

  const promise = React.useMemo(() => {
    if (ION_TOKEN && ION_ASSET_ID) {
      return Cesium.CesiumTerrainProvider.fromIonAssetId(Number(ION_ASSET_ID))
        .then((provider) => {
          if (!provider) {
            // Never fail silently again: a null provider here is exactly the
            // state that used to render a flat globe with no explanation.
            setWarning(
              `Cesium ion returned no terrain for asset ${ION_ASSET_ID}. ` +
              `The globe is a flat ellipsoid and the flood overlay is NOT ` +
              `aligned with real topography.`);
          }
          return provider;
        })
        .catch((err) => {
          setWarning(
            `Cesium ion terrain asset ${ION_ASSET_ID} failed to load ` +
            `(${err.message}). Falling back to flat ellipsoid.`);
          return undefined;
        });
    }
    return Cesium.CesiumTerrainProvider.fromUrl(`${TILES}/terrain`)
      .catch(() => {
        setWarning(
          "No terrain source configured (set VITE_CESIUM_ION_TOKEN + " +
          "VITE_CESIUM_ION_ASSET_ID, or build a self-hosted tileset at " +
          TILES + "/terrain). Flood overlay is NOT aligned with real " +
          "topography.");
        return undefined;
      });
    // Built once. Rebuilding it would hand the Viewer a new promise on every
    // render, and the Viewer only reads it at construction anyway.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { provider: promise, warning };
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
    // Remove only the layers THIS effect added, never removeAll().
    //
    // removeAll() also destroyed the base imagery layer, so the globe rendered
    // as untextured grey geometry — which, on top of the flat-terrain bug
    // above, is why the 3D panel looked like a plain blue sphere. The keyframe
    // overlays are all created here, so tracking them is exact.
    for (const layer of layersRef.current) {
      if (layer && !layer.isDestroyed?.()) {
        viewer.imageryLayers.remove(layer, true);
      }
    }
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
  //
  // WAITS for the viewer, rather than giving up when it is not there yet.
  // resium attaches viewerRef asynchronously, so on mount this effect ran
  // BEFORE `cesiumElement` existed, hit the `if (!viewer) return` and never ran
  // again — the initial fly-to was silently dropped and the globe sat at
  // Cesium's default home view over North America. Clicking "Dam site" did not
  // rescue it either, because `selected` was already "dam" so nothing changed
  // and the effect did not re-fire. The 3D panel therefore showed the whole
  // Earth for the entire demo.
  useEffect(() => {
    let cancelled = false;
    let attempts = 0;

    const fly = () => {
      if (cancelled) return;
      const viewer = viewerRef.current?.cesiumElement;
      if (!viewer || viewer.isDestroyed?.()) {
        // ~5 s of retries at 100 ms. Bounded so a viewer that never mounts
        // cannot leave a timer running for the life of the page.
        if (attempts++ < 50) setTimeout(fly, 100);
        return;
      }
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(preset.lon, preset.lat, preset.height),
        duration: 1.5,
      });
    };

    fly();
    return () => { cancelled = true; };
  }, [selected, preset.lon, preset.lat, preset.height]);

  // Re-fly even when the SAME preset is clicked again. Without this, pressing
  // the button for the already-selected view does nothing, which reads as a
  // dead button — and is exactly what made the lost initial fly-to impossible
  // to recover from.
  const flyToPreset = (id) => {
    if (id === selected) {
      const viewer = viewerRef.current?.cesiumElement;
      const target = cameras.find((p) => p.id === id);
      if (viewer && target && !viewer.isDestroyed?.()) {
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(target.lon, target.lat, target.height),
          duration: 1.5,
        });
      }
      return;
    }
    setSelected(id);
  };

  return (
    // position:relative both anchors the absolutely-positioned overlays below
    // and keeps the Cesium canvas inside this pane — resium's `full` prop makes
    // the viewer fill the whole window, which covers the control panel and
    // swallows its clicks.
    <div style={{ height: "100%", width: "100%", position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", zIndex: 10, top: 8, left: 8 }}>
        {cameras.map((p) => (
          <button key={p.id} onClick={() => flyToPreset(p.id)} style={{ marginRight: 4 }}>
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
