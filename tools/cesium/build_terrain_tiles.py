"""
Build a self-hosted CesiumJS terrain tileset from the project's own DEM.

Why self-hosted (integration brief §5.5.1): Cesium World Terrain is global,
low-resolution, and — critically — NOT the surface the solver ran on. If the 3D
terrain and the simulation terrain disagree, the flood overlay floats through
hills or clips underground at the seams, which reads as fake immediately. Tiling
the same Copernicus GLO-30 DEM that jalraksha/terrain/conditioning.py feeds the
solver makes them match by construction.

Format: heightmap-1.0, not quantized-mesh. cesium-terrain-builder is a C++ build
we do not have, and the Python quantized-mesh encoders (pydelatin, pymartini) are
compiled packages without Python 3.14 wheels. heightmap-1.0 needs nothing but
numpy and is still supported natively — see
@cesium/engine/Source/Core/CesiumTerrainProvider.js, which branches on
`data.format === "heightmap-1.0"` and decodes via HeightmapTerrainData.

Tile format (per Cesium's heightmap-1.0 spec):
  * 65 x 65 grid of little-endian uint16, row-major, NORTH-WEST corner first.
  * height_metres = value / 5 - 1000  -> representable range -1000 .. 12107 m,
    which covers the Garhwal Himalaya (domain max ~6.7 km) comfortably.
  * followed by one child-availability mask byte (bit 0 SW, 1 SE, 2 NW, 3 NE).

Tiling scheme: Cesium's default GeographicTilingScheme — 2 x 1 tiles at level 0
covering the whole globe, each level halving the tile span. Tiles are addressed
{z}/{x}/{y}.terrain with y counted from the SOUTH (TMS).

Usage:
    python tools/cesium/build_terrain_tiles.py \\
        --dem data/dem/dem_30.38_78.48_clipped.tif \\
        --out data/tiles/terrain --max-level 12
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import rasterio
from rasterio.enums import Resampling as RioResampling

TILE_SAMPLES = 65  # Cesium heightmap tiles are 65 x 65
HEIGHT_SCALE = 5.0  # encoded = (metres + 1000) * 5
HEIGHT_OFFSET = -1000.0
ENCODED_MAX = 256 * 256 - 1


def tile_bounds(level: int, x: int, y: int) -> Tuple[float, float, float, float]:
    """
    Geographic bounds (west, south, east, north) in degrees for a TMS tile.

    Level 0 is two tiles spanning the globe, so a tile spans 180/2^level degrees
    in both directions.
    """
    span = 180.0 / (2 ** level)
    west = -180.0 + x * span
    south = -90.0 + y * span
    return west, south, west + span, south + span


def tile_range_for_bbox(
    level: int, west: float, south: float, east: float, north: float
) -> Tuple[int, int, int, int]:
    """Inclusive (x_min, y_min, x_max, y_max) tile indices covering a bbox."""
    span = 180.0 / (2 ** level)
    x_min = max(0, int(math.floor((west + 180.0) / span)))
    x_max = min(2 ** (level + 1) - 1, int(math.floor((east + 180.0) / span)))
    y_min = max(0, int(math.floor((south + 90.0) / span)))
    y_max = min(2 ** level - 1, int(math.floor((north + 90.0) / span)))
    return x_min, y_min, x_max, y_max


def encode_heightmap(heights_m: np.ndarray, child_mask: int) -> bytes:
    """
    Encode a 65x65 metre-elevation array as a heightmap-1.0 tile.

    heights_m must be ordered NORTH-WEST first (row 0 = northernmost), which is
    the raster convention and the opposite of the solver Grid's south-up rows.
    """
    if heights_m.shape != (TILE_SAMPLES, TILE_SAMPLES):
        raise ValueError(f"expected {TILE_SAMPLES}x{TILE_SAMPLES}, got {heights_m.shape}")
    encoded = np.rint((heights_m - HEIGHT_OFFSET) * HEIGHT_SCALE)
    encoded = np.clip(encoded, 0, ENCODED_MAX).astype("<u2")
    return encoded.tobytes() + struct.pack("<B", child_mask)


class DemSampler:
    """
    Bilinear sampler over an in-memory DEM.

    The DEM is read once into RAM (a 3891 x 4510 float32 array is ~70 MB) and
    every tile is sampled from that. Reading windows straight from the GeoTIFF
    per tile is what the first version did, and it was unusable: the file is
    deflate-compressed, low-zoom tiles span the entire raster, and each of the
    ~800 tiles paid a fresh decompression.
    """

    def __init__(self, dem_path: Path, nodata_fill: float = 0.0):
        with rasterio.open(dem_path) as src:
            self.data = src.read(1).astype(np.float32)
            self.transform = src.transform
            self.bounds = src.bounds
            nodata = src.nodata
        if nodata is not None:
            self.data = np.where(self.data == nodata, np.float32(nodata_fill), self.data)
        self.data = np.nan_to_num(
            self.data, nan=nodata_fill, posinf=nodata_fill, neginf=nodata_fill
        )
        self.nodata_fill = float(nodata_fill)
        self.height, self.width = self.data.shape
        # Geographic (EPSG:4326) north-up transform: |e| is the degrees-per-pixel
        # in x, |a| in y. Precompute the inverse to map lon/lat -> pixel.
        self.west = self.transform.c
        self.north = self.transform.f
        self.px = self.transform.a       # +degrees per pixel eastward
        self.py = self.transform.e       # -degrees per pixel southward (negative)

    def sample(self, west: float, south: float, east: float, north: float) -> np.ndarray:
        """
        Sample a TILE_SAMPLES x TILE_SAMPLES grid over a tile's bounds.

        Returns metres with row 0 = NORTH (heightmap-1.0 order). Points outside
        the DEM footprint return nodata_fill, so edge tiles still decode rather
        than leaving a hole in the terrain.
        """
        lons = np.linspace(west, east, TILE_SAMPLES)
        lats = np.linspace(north, south, TILE_SAMPLES)  # row 0 = north
        col = (lons - self.west) / self.px
        row = (lats - self.north) / self.py
        cc, rr = np.meshgrid(col, row)

        inside = (rr >= 0) & (rr <= self.height - 1) & (cc >= 0) & (cc <= self.width - 1)
        rr_c = np.clip(rr, 0, self.height - 1)
        cc_c = np.clip(cc, 0, self.width - 1)

        r0 = np.floor(rr_c).astype(np.intp)
        c0 = np.floor(cc_c).astype(np.intp)
        r1 = np.minimum(r0 + 1, self.height - 1)
        c1 = np.minimum(c0 + 1, self.width - 1)
        fr = (rr_c - r0)[..., None][..., 0]
        fc = (cc_c - c0)[..., None][..., 0]

        d = self.data
        top = d[r0, c0] * (1 - fc) + d[r0, c1] * fc
        bot = d[r1, c0] * (1 - fc) + d[r1, c1] * fc
        out = (top * (1 - fr) + bot * fr).astype(np.float64)
        return np.where(inside, out, self.nodata_fill)


def build_tileset(
    dem_path: Path, out_dir: Path, max_level: int, min_level: int = 0
) -> Dict:
    """Write the full tile pyramid plus layer.json. Returns a summary dict."""
    out_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(dem_path) as src:
        if src.crs is None or not src.crs.is_geographic:
            raise ValueError(
                f"{dem_path} must be in a geographic CRS (EPSG:4326) to tile onto "
                f"Cesium's geographic scheme; got {src.crs}."
            )
        bounds = src.bounds

    # Sea level is the safe fill: it never invents terrain above the real
    # surface, so an edge tile cannot poke through the flood overlay.
    sampler = DemSampler(dem_path, nodata_fill=0.0)
    elev_min = float(sampler.data.min())
    elev_max = float(sampler.data.max())

    available: List[List[Dict[str, int]]] = []
    n_tiles = 0
    total_bytes = 0

    for level in range(min_level, max_level + 1):
        x_min, y_min, x_max, y_max = tile_range_for_bbox(
            level, bounds.left, bounds.bottom, bounds.right, bounds.top
        )
        available.append(
            [{"startX": x_min, "startY": y_min, "endX": x_max, "endY": y_max}]
        )

        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                west, south, east, north = tile_bounds(level, x, y)
                heights = sampler.sample(west, south, east, north)

                # Declare all four children present unless this is the last
                # level; Cesium uses the mask to decide whether to refine.
                child_mask = 0 if level >= max_level else 0b1111

                payload = encode_heightmap(heights, child_mask)
                tile_path = out_dir / str(level) / str(x) / f"{y}.terrain"
                tile_path.parent.mkdir(parents=True, exist_ok=True)
                tile_path.write_bytes(payload)
                n_tiles += 1
                total_bytes += len(payload)

        print(
            f"  level {level:2d}: x {x_min}..{x_max}, y {y_min}..{y_max} "
            f"({(x_max - x_min + 1) * (y_max - y_min + 1)} tiles)"
        )

    layer = {
        "tilejson": "2.1.0",
        "name": dem_path.stem,
        "description": "JalRaksha self-hosted terrain (Copernicus GLO-30, same DEM as solver)",
        "version": "1.0.0",
        "format": "heightmap-1.0",
        "attribution": "Copernicus DEM GLO-30 (c) ESA",
        "scheme": "tms",
        "tiles": ["{z}/{x}/{y}.terrain"],
        "minzoom": min_level,
        "maxzoom": max_level,
        "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
        "projection": "EPSG:4326",
        "available": available,
    }
    (out_dir / "layer.json").write_text(json.dumps(layer, indent=2), encoding="utf-8")

    return {
        "tiles": n_tiles,
        "megabytes": total_bytes / 1e6,
        "elevation_range_m": (elev_min, elev_max),
        "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
        "out_dir": str(out_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", type=Path, default=Path("data/dem/dem_30.38_78.48_clipped.tif"),
                        help="Geographic (EPSG:4326) DEM — the same one the solver conditions.")
    parser.add_argument("--out", type=Path, default=Path("data/tiles/terrain"))
    parser.add_argument("--max-level", type=int, default=12,
                        help="Deepest zoom. Level 12 is ~44 m/sample at 65 samples/tile, "
                             "which already exceeds GLO-30's real 30 m detail after "
                             "reprojection; 13 doubles tile count for little gain.")
    args = parser.parse_args()

    if not args.dem.exists():
        raise SystemExit(f"DEM not found: {args.dem} — run jalraksha.dem.fetch_dem first.")

    print(f"Tiling {args.dem} -> {args.out} (levels 0..{args.max_level})")
    summary = build_tileset(args.dem, args.out, args.max_level)
    print(
        f"\nDone: {summary['tiles']} tiles, {summary['megabytes']:.1f} MB\n"
        f"  elevation {summary['elevation_range_m'][0]:.0f}..{summary['elevation_range_m'][1]:.0f} m\n"
        f"  bounds {summary['bounds']}\n"
        f"  serve at <VITE_TILES_URL>/terrain"
    )


if __name__ == "__main__":
    main()
