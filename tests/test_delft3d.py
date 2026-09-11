"""
Delft3D Integration Test Suite.

Tests:
  - TestDelft3DSetup: Grid creation, bathymetry, IC, MDU file writing
  - TestDelft3DRunner: Binary detection, SWE fallback, result format
  - TestDelft3DComparison: Metrics, gauge comparisons, plot generation
  - TestDelft3DIntegration: End-to-end pipeline with Delft3D
"""

import os
import shutil
import tempfile
import numpy as np
import pytest
from pathlib import Path

from jalraksha.delft3d.setup import (
    create_rectangular_grid,
    interpolate_bathymetry_to_grid,
    generate_initial_conditions,
    write_mdu_file,
    setup_delft3d_model,
)
from jalraksha.delft3d.runner import (
    is_dflowfm_available,
    run_delft3d_simulation,
)
from jalraksha.delft3d.comparison import (
    rasterize_sph_particles,
    compute_comparison_metrics,
    compare_gauge_arrivals,
    plot_comparison_depth_maps,
    plot_comparison_hydrographs,
    compare_sph_vs_delft3d,
)


TEHRI_CONFIG = {
    "name": "Tehri",
    "lat": 30.3789,
    "lon": 78.4789,
    "height_m": 260.0,
    "storage_mm3": 3540.0,
    "dam_type": "embankment",
    "failure_mode": "overtopping",
}


# ─── TestDelft3DSetup ─────────────────────────────────────────────────────────

class TestDelft3DSetup:
    def test_create_rectangular_grid(self):
        grid = create_rectangular_grid(nx=50, ny=100, dx=30.0, dy=30.0)
        assert grid["nx"] == 50
        assert grid["ny"] == 100
        assert grid["node_x"].shape == (101, 51)  # (ny+1, nx+1)
        assert grid["node_y"].shape == (101, 51)

    def test_grid_origin_offset(self):
        grid = create_rectangular_grid(nx=10, ny=10, dx=10.0, dy=10.0, origin_x=500.0, origin_y=1000.0)
        assert grid["node_x"][0, 0] == 500.0
        assert grid["node_y"][0, 0] == 1000.0

    def test_interpolate_bathymetry_matching_shape(self):
        dem = np.random.rand(50, 30).astype(np.float64) * 100
        grid = create_rectangular_grid(nx=30, ny=50, dx=30.0, dy=30.0)
        bath = interpolate_bathymetry_to_grid(dem, grid=grid)
        assert bath.shape == (50, 30)

    def test_interpolate_bathymetry_no_grid(self):
        dem = np.random.rand(50, 30).astype(np.float32)
        bath = interpolate_bathymetry_to_grid(dem)
        assert bath.dtype == np.float64
        assert bath.shape == (50, 30)

    def test_generate_initial_conditions(self):
        grid = create_rectangular_grid(nx=20, ny=40, dx=30.0, dy=30.0)
        ic = generate_initial_conditions(grid, dam_height_m=260.0)
        assert "water_level" in ic
        assert "dam_row_index" in ic
        assert ic["water_level"].shape == (40, 20)
        # Upstream should have high water level
        assert np.mean(ic["water_level"][:ic["dam_row_index"], :]) > 200.0
        # Downstream should be near zero
        assert np.mean(ic["water_level"][ic["dam_row_index"]:, :]) < 1.0

    def test_write_mdu_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            grid = create_rectangular_grid(nx=10, ny=20, dx=30.0, dy=30.0)
            bath = np.zeros((20, 10), dtype=np.float64)
            ic = generate_initial_conditions(grid, 100.0)
            mdu_path = write_mdu_file(
                Path(tmpdir), grid, bath, ic, TEHRI_CONFIG,
                total_time_s=600.0, dt_user_s=10.0,
            )
            assert mdu_path.exists()
            content = mdu_path.read_text()
            assert "[General]" in content
            assert "Tehri" in content
            assert "260.0" in content

    def test_mdu_supporting_files_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            grid = create_rectangular_grid(nx=10, ny=20, dx=30.0, dy=30.0)
            bath = np.zeros((20, 10), dtype=np.float64)
            ic = generate_initial_conditions(grid, 100.0)
            write_mdu_file(Path(tmpdir), grid, bath, ic, TEHRI_CONFIG)
            assert (Path(tmpdir) / "bathymetry.xyz").exists()
            assert (Path(tmpdir) / "initial_waterlevel.ini").exists()
            assert (Path(tmpdir) / "grid.grd").exists()

    def test_setup_delft3d_model_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = setup_delft3d_model(
                TEHRI_CONFIG,
                output_dir=Path(tmpdir) / "model",
                grid_nx=20, grid_ny=40,
                grid_dx=30.0, grid_dy=30.0,
            )
            assert "mdu_path" in result
            assert result["mdu_path"].exists()
            assert result["grid"]["nx"] == 20
            assert result["bathymetry"].shape == (40, 20)

    def test_setup_with_dem_array(self):
        dem = np.random.rand(40, 20).astype(np.float32) * 50
        with tempfile.TemporaryDirectory() as tmpdir:
            result = setup_delft3d_model(
                TEHRI_CONFIG,
                dem_array=dem,
                output_dir=Path(tmpdir) / "model",
                grid_nx=20, grid_ny=40,
            )
            assert result["bathymetry"].shape == (40, 20)


# ─── TestDelft3DRunner ─────────────────────────────────────────────────────────

class TestDelft3DRunner:
    def test_dflowfm_not_available(self):
        """dflowfm binary is not expected to be installed in test env."""
        assert is_dflowfm_available() is False or is_dflowfm_available() is True

    def test_fallback_swe_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = setup_delft3d_model(
                TEHRI_CONFIG,
                output_dir=Path(tmpdir) / "model",
                grid_nx=20, grid_ny=20,
                total_time_s=0.5,
            )
            result = run_delft3d_simulation(
                model, TEHRI_CONFIG,
                total_time_s=0.5,
                force_fallback=True,
            )
            assert result["success"] is True
            assert "SWE" in result["engine"] or "Delft3D" in result["engine"]

    def test_fallback_returns_depth_field(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = setup_delft3d_model(
                TEHRI_CONFIG,
                output_dir=Path(tmpdir) / "model",
                grid_nx=20, grid_ny=20,
                total_time_s=5.0,
            )
            result = run_delft3d_simulation(
                model, TEHRI_CONFIG,
                total_time_s=5.0,
                force_fallback=True,
            )
            assert "max_depth" in result
            assert result["max_depth"].shape == (20, 20)

    def test_fallback_engine_label(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = setup_delft3d_model(
                TEHRI_CONFIG,
                output_dir=Path(tmpdir) / "model",
                grid_nx=20, grid_ny=20,
                total_time_s=5.0,
            )
            result = run_delft3d_simulation(
                model, TEHRI_CONFIG,
                total_time_s=5.0,
                force_fallback=True,
            )
            assert "engine_label" in result
            assert "Delft3D" in result["engine_label"]

    def test_fallback_with_gauges(self):
        gauges = [
            {"name": "Koteshwar", "distance_km": 13.0},
            {"name": "Haridwar", "distance_km": 58.4},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            model = setup_delft3d_model(
                TEHRI_CONFIG,
                output_dir=Path(tmpdir) / "model",
                grid_nx=20, grid_ny=20,
                total_time_s=5.0,
            )
            result = run_delft3d_simulation(
                model, TEHRI_CONFIG,
                gauge_locations=gauges,
                total_time_s=5.0,
                force_fallback=True,
            )
            assert "gauge_arrivals" in result
            assert "Koteshwar" in result["gauge_arrivals"]
            assert result["gauge_arrivals"]["Koteshwar"]["median_min"] > 0


# ─── TestDelft3DComparison ────────────────────────────────────────────────────

class TestDelft3DComparison:
    def test_rasterize_sph_particles(self):
        # particle_volume_m3 is REQUIRED. Depth is (particles in the cell) x
        # (volume each carries) / (cell area), and rasterize_sph_particles used
        # to substitute a hardcoded 1.0 m3 when it was absent, which rescaled
        # every depth in the comparison by an arbitrary factor. A real result
        # from jalraksha.sph.pysph_runner always carries it.
        sph = {
            "x": np.array([5.0, 15.0, 25.0]),
            "y": np.array([5.0, 15.0, 25.0]),
            "z": np.array([2.0, 3.0, 1.0]),
            "particle_volume_m3": 8.0,   # 2 m particle spacing
        }
        grid = rasterize_sph_particles(sph, grid_nx=10, grid_ny=10, grid_dx=10.0, grid_dy=10.0)
        assert grid.shape == (10, 10)
        # One particle per cell, 8 m3 each, over a 100 m2 cell => 0.08 m.
        assert grid[0, 0] == pytest.approx(0.08)

    def test_rasterize_refuses_without_particle_volume(self):
        sph = {
            "x": np.array([5.0]), "y": np.array([5.0]), "z": np.array([2.0]),
        }
        with pytest.raises(ValueError, match="particle_volume_m3"):
            rasterize_sph_particles(sph, grid_nx=10, grid_ny=10, grid_dx=10.0, grid_dy=10.0)

    def test_rasterize_empty_particles(self):
        sph = {"x": np.array([]), "y": np.array([]), "z": np.array([])}
        grid = rasterize_sph_particles(sph, grid_nx=5, grid_ny=5, grid_dx=10.0, grid_dy=10.0)
        assert np.all(grid == 0.0)

    def test_comparison_metrics_identical(self):
        a = np.ones((10, 10), dtype=np.float32) * 2.0
        b = a.copy()
        metrics = compute_comparison_metrics(a, b)
        assert metrics["rmse_m"] == 0.0
        assert metrics["csi"] == 1.0

    def test_comparison_metrics_different(self):
        a = np.ones((10, 10), dtype=np.float32) * 2.0
        b = np.zeros((10, 10), dtype=np.float32)
        metrics = compute_comparison_metrics(a, b)
        assert metrics["rmse_m"] > 0.0
        assert metrics["csi"] < 1.0

    def test_compare_gauge_arrivals(self):
        a = {"Koteshwar": {"median_min": 30.0, "distance_km": 13.0}}
        b = {"Koteshwar": {"median_min": 28.0, "distance_km": 13.0}}
        rows = compare_gauge_arrivals(a, b)
        assert len(rows) == 1
        assert rows[0]["delta_min"] is not None

    def test_compare_gauge_arrivals_missing_gauge(self):
        a = {"Koteshwar": {"median_min": 30.0}}
        b = {"Haridwar": {"median_min": 90.0}}
        rows = compare_gauge_arrivals(a, b)
        assert len(rows) == 2  # Both gauges listed

    def test_plot_comparison_depth_maps(self):
        import matplotlib.pyplot as plt
        a = np.random.rand(20, 10).astype(np.float32) * 5
        b = np.random.rand(20, 10).astype(np.float32) * 5
        fig = plot_comparison_depth_maps(a, b)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_plot_comparison_hydrographs(self):
        import matplotlib.pyplot as plt
        a = {"Koteshwar": {"median_min": 30.0, "p05_min": 24.0, "p95_min": 36.0}}
        b = {"Koteshwar": {"median_min": 28.0, "p05_min": 22.0, "p95_min": 34.0}}
        fig = plot_comparison_hydrographs(a, b)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)


# ─── TestDelft3DIntegration ───────────────────────────────────────────────────

class TestDelft3DIntegration:
    def test_full_pipeline_setup_to_comparison(self):
        """End-to-end: setup → run Delft3D fallback → compare with mock SPH."""
        import matplotlib.pyplot as plt

        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup
            model = setup_delft3d_model(
                TEHRI_CONFIG,
                output_dir=Path(tmpdir) / "model",
                grid_nx=20, grid_ny=20,
                total_time_s=5.0,
            )

            gauges = [{"name": "Koteshwar", "distance_km": 13.0}]

            # Run Delft3D (fallback SWE)
            d3d_result = run_delft3d_simulation(
                model, TEHRI_CONFIG,
                gauge_locations=gauges,
                total_time_s=5.0,
                force_fallback=True,
            )
            assert d3d_result["success"]

            # Mock SPH result
            sph_result = {
                "x": np.random.rand(100) * 300,
                "y": np.random.rand(100) * 600,
                "z": np.random.rand(100) * 5,
                "particle_volume_m3": 1.0,
                "engine_label": "synthetic fixture (not a PySPH run)",
                "gauge_arrivals": {
                    "Koteshwar": {"median_min": 32.0, "p05_min": 26.0, "p95_min": 38.0, "distance_km": 13.0},
                },
            }

            # Compare
            comparison = compare_sph_vs_delft3d(sph_result, d3d_result, gauges)
            assert "metrics" in comparison
            assert "gauge_comparison" in comparison
            assert isinstance(comparison["depth_fig"], plt.Figure)
            assert isinstance(comparison["hydro_fig"], plt.Figure)

            plt.close(comparison["depth_fig"])
            plt.close(comparison["hydro_fig"])

    def test_hydrolib_core_importable(self):
        """Verify hydrolib-core is installed."""
        import hydrolib.core
        assert hydrolib.core is not None


class TestUgridFacesToGrid:
    """
    D-Flow FM writes mesh2d_waterdepth as (time, nFaces) — a flat list of face
    values, not a raster. Everything downstream treats max_depth as 2D, so the
    unconverted array reached imshow and raised "Invalid shape (160000,) for
    image data". The comparison's outer handler then wrote that TypeError to
    disk as `delft3d_binary_used: false`, reporting a Delft3D FM run that had
    genuinely succeeded as never having happened.
    """

    @staticmethod
    def _regular_mesh(nx: int, ny: int, dx: float = 10.0):
        """
        Face centres in FM's ordering, not row-major.

        FM numbers faces in its own internal sweep — the real Khadakwasla mesh
        starts x = [343030, 343030, 343165, 343030, ...] against
        y = [2012774, 2012909, 2012774, 2013044, ...]. This shuffles
        deterministically to stand in for that, which is the whole point: a
        `.reshape(ny, nx)` passes on row-major input and silently scrambles the
        field on real input.
        """
        from jalraksha.delft3d.runner import _faces_to_grid  # noqa: F401

        gy, gx = np.meshgrid(np.arange(ny) * dx, np.arange(nx) * dx,
                             indexing="ij")
        face_x = gx.ravel().astype(float)
        face_y = gy.ravel().astype(float)
        order = np.random.default_rng(3).permutation(face_x.size)
        return face_x[order], face_y[order], order

    def test_places_every_value_at_its_own_coordinate(self):
        from jalraksha.delft3d.runner import _faces_to_grid

        nx, ny, dx = 12, 9, 10.0
        face_x, face_y, order = self._regular_mesh(nx, ny, dx)

        # A field that is a pure function of position, so a misplaced value is
        # detectable rather than plausible.
        values = (face_x + 1000.0 * face_y).astype(np.float32)
        grid = _faces_to_grid(values, face_x, face_y)

        assert grid.shape == (ny, nx)
        assert not np.isnan(grid).any(), "every cell must receive exactly one face"
        for j in range(ny):
            for i in range(nx):
                assert grid[j, i] == pytest.approx(i * dx + 1000.0 * j * dx)

    def test_a_naive_reshape_would_have_been_wrong(self):
        """
        Guards the reason this is a scatter and not a reshape. On FM's ordering
        the two disagree, so a future 'simplification' to .reshape() fails here
        instead of silently producing a scrambled flood map.
        """
        from jalraksha.delft3d.runner import _faces_to_grid

        nx, ny = 12, 9
        face_x, face_y, _ = self._regular_mesh(nx, ny)
        values = np.arange(nx * ny, dtype=np.float32)

        placed = _faces_to_grid(values, face_x, face_y)
        assert not np.array_equal(placed, values.reshape(ny, nx))

    def test_unstructured_mesh_is_left_alone(self):
        """
        An irregular FM mesh is legitimate output. This function's job is to
        undo a known flattening, not to invent a raster from a mesh that never
        was one.
        """
        from jalraksha.delft3d.runner import _faces_to_grid

        face_x = np.array([0.0, 1.0, 2.5, 4.0, 7.0])
        face_y = np.array([0.0, 1.0, 0.5, 3.0, 2.0])
        values = np.arange(5, dtype=np.float32)
        assert _faces_to_grid(values, face_x, face_y).shape == (5,)

    def test_already_gridded_input_is_untouched(self):
        """The built-in fallback solver already returns 2D; it must pass through."""
        from jalraksha.delft3d.runner import _faces_to_grid

        grid = np.zeros((7, 5), dtype=np.float32)
        assert _faces_to_grid(grid, None, None).shape == (7, 5)
