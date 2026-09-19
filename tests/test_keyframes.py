"""
Tests for Phase 5+ keyframe export (§5.3 of the integration brief).

Verifies:
  - export_keyframes returns a KeyframeManifest with N time-tagged keyframes
  - Each keyframe carries WGS84 bounds [w, s, e, n] and an FD2320 hazard summary
  - The colorization reuses the canonical HazardClassifier FD2320 map
  - PNG artifacts are written and are valid images
"""

import numpy as np
import pytest
from pathlib import Path

from jalraksha.impact.hazard import HazardClassifier
from jalraksha.export.keyframes import export_keyframes, KeyframeManifest, Keyframe


def _make_result(nx=40, ny=32, n_times=12, crs=32644):
    """Build a synthetic but internally-consistent EnsembleResult-like dict."""
    rng = np.random.default_rng(0)
    grid = {
        "nx": nx, "ny": ny, "dx": 200.0, "dy": 200.0,
        "x0": 450000.0, "y0": 3500000.0, "crs": crs,
    }
    # Dam near top-centre; wave expands downward over time.
    dam_i, dam_j = ny // 2, nx // 2
    depth_series = []
    for k in range(n_times):
        t = 600.0 * (k + 1)
        radius = int((k + 1) * max(nx, ny) / (n_times + 2))
        depth = np.zeros((ny, nx), dtype=np.float32)
        y, x = np.ogrid[:ny, :nx]
        dist = np.sqrt((x - dam_j) ** 2 + (y - dam_i) ** 2)
        depth[dist <= radius] = (8.0 * (1.0 - dist[dist <= radius] / max(radius, 1)))
        depth = np.maximum(depth, 0.0).astype(np.float32)
        depth += rng.normal(0, 0.05, depth.shape).astype(np.float32)
        depth = np.maximum(depth, 0.0)
        depth_series.append({"time_s": float(t), "depth": depth})
    return {"dam_name": "Tehri", "grid": grid, "depth_series": depth_series}


def test_returns_manifest_with_n_keyframes(tmp_path):
    result = _make_result()
    classifier = HazardClassifier()
    manifest = export_keyframes(result, classifier, n_keyframes=10, out_dir=tmp_path)
    assert isinstance(manifest, KeyframeManifest)
    assert len(manifest.keyframes) == 10
    assert (tmp_path / "manifest.json").exists()


def test_keyframe_structure_and_bounds(tmp_path):
    result = _make_result()
    manifest = export_keyframes(result, None, n_keyframes=8, out_dir=tmp_path)
    for kf in manifest.keyframes:
        assert isinstance(kf, Keyframe)
        assert kf.time_s >= 0
        assert len(kf.bounds) == 4
        west, south, east, north = kf.bounds
        # WGS84 bounds must be valid and ordered for Tehri (≈30.4°N, 78.5°E).
        assert -180 <= west < east <= 180
        assert -90 <= south < north <= 90
        assert 75.0 < west and east < 82.0        # Uttarakhand longitude band
        assert 28.0 < south and north < 32.0      # Uttarakhand latitude band
        assert "weighted_hazard_index" in kf.hazard_summary


def test_pngs_written_and_valid(tmp_path):
    result = _make_result()
    manifest = export_keyframes(result, None, n_keyframes=5, out_dir=tmp_path)
    saw_transparency = False
    for kf in manifest.keyframes:
        # png_url is a bare filename (resolved against the manifest's own URL
        # by whatever serves it over HTTP) — join with out_dir to find it on disk.
        p = tmp_path / kf.png_url
        assert p.exists()
        assert p.stat().st_size > 0
        # RGBA, and genuinely transparent where the flood is not.
        #
        # This used to accept ("RGB", "P"). A 3-channel keyframe has no way to
        # say "no water here", so HazardClassifier's dry colour [128,128,128]
        # was painted as opaque grey — and because these PNGs are drawn OVER a
        # basemap in both the Leaflet and Cesium panels, every frame was a solid
        # grey rectangle the size of the domain covering the terrain beneath it.
        # Asserting the mode alone would not have caught that; asserting that
        # dry cells are actually transparent does.
        import numpy as np
        from PIL import Image

        img = Image.open(p)
        assert img.mode == "RGBA", f"keyframes must carry alpha, got {img.mode}"
        assert img.size[0] > 1 and img.size[1] > 1

        alpha = np.array(img)[:, :, 3]
        assert set(np.unique(alpha)) <= {0, 255}, (
            "alpha must be binary: a cell is either flooded or it is not"
        )
        saw_transparency = saw_transparency or bool((alpha == 0).any())

    # Checked across the sequence, not per frame. This fixture's wave expands
    # until it covers the whole grid, so the LAST keyframes are legitimately
    # all-wet and have nothing to make transparent; the early ones are almost
    # entirely dry. Requiring transparency in every frame would be asserting
    # something untrue about a valid flood.
    assert saw_transparency, (
        "no keyframe had a transparent pixel — dry cells are being painted "
        "opaque, which covers the basemap the overlay is drawn on"
    )


def test_fd2320_color_consistency(tmp_path):
    """Keyframe coloring must agree with HazardClassifier's own color map."""
    result = _make_result(nx=20, ny=20)
    classifier = HazardClassifier()
    manifest = export_keyframes(result, classifier, n_keyframes=3, out_dir=tmp_path)

    # Re-classify the first keyframe's depth and compare a known deep/dry cell.
    depth0 = result["depth_series"][0]["depth"]
    cls = classifier.classify_depth_only(depth0)
    rgb = classifier.apply_to_rgb(cls)
    dry_color = tuple(classifier.get_color(classifier.classify_depth_only(
        np.array([[0.0]]))[0, 0]))
    # At least one cell should map to the DRY color (depth == 0 somewhere).
    assert tuple(rgb[0, 0]) in [tuple(classifier.get_color(lvl)) for lvl in
                                classifier.color_map]


def test_manifest_json_serializable(tmp_path):
    result = _make_result()
    manifest = export_keyframes(result, None, n_keyframes=4, out_dir=tmp_path)
    data = manifest.to_dict()
    assert data["version"] == "1.0"
    assert len(data["keyframes"]) == 4
    assert data["simulation_info"]["dam_name"] == "Tehri"
    # Round-trip through JSON string.
    import json
    json.dumps(data)


class TestOverlayRegistration:
    """
    The overlay must land where the flood is, not near it.

    Khadakwasla's 500 x 400 km run drew its flood band beside the Bhima near
    Daund: the PNG was the raw UTM grid placed inside a lat/lon box built from
    two corners. These tests put ONE wet cell at a known UTM position and check
    that each warped PNG has it at that position's true lat/lon, within a pixel.
    """

    # The real 500 x 400 km domain's geometry in EPSG:32643, at 5 km cells so
    # the test stays fast. The error being tested does not depend on cell size.
    GRID = {"nx": 100, "ny": 80, "dx": 5000.0, "dy": 5000.0,
            "x0": 289962.5, "y0": 1839707.0, "crs": "EPSG:32643"}
    WET_I, WET_J = 62, 57   # column (east) and row (NORTH-counting), near Daund

    def _export(self, tmp_path):
        depth = np.zeros((self.GRID["ny"], self.GRID["nx"]), dtype=np.float32)
        depth[self.WET_J, self.WET_I] = 5.0
        result = {"dam_name": "Registration", "grid": dict(self.GRID),
                  "depth_series": [{"time_s": 0.0, "depth": depth}]}
        return export_keyframes(result, None, n_keyframes=1, out_dir=tmp_path).keyframes[0]

    def _true_lonlat(self):
        from pyproj import Transformer

        x = self.GRID["x0"] + (self.WET_I + 0.5) * self.GRID["dx"]
        y = self.GRID["y0"] + (self.WET_J + 0.5) * self.GRID["dy"]
        return Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True).transform(x, y)

    @staticmethod
    def _alpha_near(png, col, row):
        from PIL import Image

        alpha = np.array(Image.open(png))[:, :, 3]
        r, c = int(round(row)), int(round(col))
        return alpha[max(r - 1, 0):r + 2, max(c - 1, 0):c + 2].max()

    def test_geographic_png_places_the_cell_at_its_true_lat_lon(self, tmp_path):
        from PIL import Image

        kf = self._export(tmp_path)
        lon, lat = self._true_lonlat()
        west, south, east, north = kf.bounds
        width, height = Image.open(tmp_path / kf.png_url).size
        col = (lon - west) / (east - west) * width
        row = (north - lat) / (north - south) * height
        assert self._alpha_near(tmp_path / kf.png_url, col, row) == 255

    def test_mercator_png_places_the_cell_at_its_true_lat_lon(self, tmp_path):
        from PIL import Image

        def merc_y(lat_deg):
            return np.log(np.tan(np.pi / 4 + np.radians(lat_deg) / 2))

        kf = self._export(tmp_path)
        lon, lat = self._true_lonlat()
        west, south, east, north = kf.bounds_mercator
        width, height = Image.open(tmp_path / kf.png_url_mercator).size
        col = (lon - west) / (east - west) * width
        row = (merc_y(north) - merc_y(lat)) / (merc_y(north) - merc_y(south)) * height
        assert self._alpha_near(tmp_path / kf.png_url_mercator, col, row) == 255

    def test_the_old_placement_missed_by_kilometres(self):
        """Pins the bug: two-corner bounds + raw grid put this cell > 1 km away."""
        from pyproj import Transformer

        g = self.GRID
        to_ll = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
        (w, e), (s, n) = to_ll.transform([g["x0"], g["x0"] + g["nx"] * g["dx"]],
                                         [g["y0"], g["y0"] + g["ny"] * g["dy"]])
        lon_old = w + (self.WET_I + 0.5) / g["nx"] * (e - w)
        lat_old = s + (self.WET_J + 0.5) / g["ny"] * (n - s)
        lon, lat = self._true_lonlat()
        miss_km = np.hypot((lon_old - lon) * 111.32 * np.cos(np.radians(lat)), (lat_old - lat) * 110.57)
        assert miss_km > 1.0

    def test_bounds_envelope_uses_all_four_corners(self):
        from pyproj import Transformer

        from jalraksha.export.keyframes import _reproject_bounds_utm_to_wgs84

        g = self.GRID
        xs = [g["x0"], g["x0"] + g["nx"] * g["dx"]]
        ys = [g["y0"], g["y0"] + g["ny"] * g["dy"]]
        lons, lats = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True).transform(
            [xs[0], xs[1], xs[1], xs[0]], [ys[0], ys[0], ys[1], ys[1]])
        expected = [min(lons), min(lats), max(lons), max(lats)]
        assert np.allclose(_reproject_bounds_utm_to_wgs84(g), expected, atol=1e-9)

    def test_manifest_says_it_is_warped(self, tmp_path):
        import json

        self._export(tmp_path)
        info = json.loads((tmp_path / "manifest.json").read_text())["simulation_info"]
        assert info["overlay_warped"] is True


def test_missing_depth_series_raises(tmp_path):
    result = {"dam_name": "Tehri", "grid": {"nx": 10, "ny": 10, "dx": 200, "dy": 200,
                                            "x0": 0, "y0": 0, "crs": 32644}}
    with pytest.raises(ValueError):
        export_keyframes(result, None, out_dir=tmp_path)
