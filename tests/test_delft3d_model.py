"""
Delft3D FM model generation and validation harness (Phase 19).

Everything here except the marked kernel tests runs offline: the UGRID mesh,
the model input set and the Ritter analytical solution need no Delft3D install.
The kernel tests skip with a reason when none is present, so the suite stays
green on a machine without Deltares software.

The assertions are about the things that were actually WRONG before the kernel
was ever run — a mesh D-Flow FM cannot read, a bed-level type that contradicts
the mesh, and an initial condition that is a lake at rest rather than a dam
break.
"""

import os

import numpy as np
import pytest

from jalraksha.delft3d.dfm_model import (
    BEDLEVTYPE_NODES, build_dfm_model, dam_break_fields,
)
from jalraksha.delft3d.runner import kernel_environment, resolve_dflowfm
from jalraksha.delft3d.ugrid import (
    UgridError, quad_mesh_topology, write_ugrid_net,
)
from jalraksha.validation.delft3d_benchmark import ritter_exact

# Honour the same setting the application does, so a machine with Delft3D can
# still exercise the no-kernel path by pointing this at nothing.
KERNEL = resolve_dflowfm(os.environ.get("JALRAKSHA_DFLOWFM_EXE") or None)
requires_kernel = pytest.mark.skipif(
    KERNEL is None,
    reason="No Delft3D FM kernel installed (set JALRAKSHA_DFLOWFM_EXE)")

GRID = {"nx": 6, "ny": 4, "dx": 100.0, "dy": 100.0, "x0": 600000.0, "y0": 3350000.0}


def _bed(ny=4, nx=6):
    """A bed sloping down toward +x, so there is somewhere for water to go."""
    return np.tile(np.linspace(10.0, 0.0, nx), (ny, 1))


# ─── TestQuadMeshTopology ─────────────────────────────────────────────────────

class TestQuadMeshTopology:
    """Node/edge/face counts and connectivity for a structured quad mesh."""

    def test_counts_match_the_grid(self):
        nx, ny = 3, 2
        edges, faces = quad_mesh_topology(nx, ny)
        assert faces.shape == (nx * ny, 4)
        # Horizontal edges on ny+1 node rows, vertical on nx+1 node columns.
        assert edges.shape == (nx * (ny + 1) + (nx + 1) * ny, 2)

    def test_indices_stay_inside_the_node_set(self):
        nx, ny = 5, 4
        edges, faces = quad_mesh_topology(nx, ny)
        n_nodes = (nx + 1) * (ny + 1)
        assert edges.min() >= 0 and edges.max() < n_nodes
        assert faces.min() >= 0 and faces.max() < n_nodes

    def test_every_face_has_four_distinct_corners(self):
        _edges, faces = quad_mesh_topology(4, 3)
        assert all(len(set(row)) == 4 for row in faces)

    def test_no_duplicate_edges(self):
        """Interior edges are shared, and must be listed once."""
        edges, _faces = quad_mesh_topology(4, 3)
        as_pairs = {tuple(sorted(pair)) for pair in edges}
        assert len(as_pairs) == edges.shape[0]

    def test_degenerate_grid_raises(self):
        with pytest.raises(UgridError):
            quad_mesh_topology(0, 3)


# ─── TestUgridNetFile ─────────────────────────────────────────────────────────

class TestUgridNetFile:
    """
    The mesh file D-Flow FM actually reads.

    What used to be written here was an INI stub (`[Grid] GridType =
    rectangular`) named as the .mdu's NetFile — unreadable by FM, and never
    noticed because the kernel had never been run.
    """

    def test_written_file_is_ugrid(self, tmp_path):
        import netCDF4 as nc

        path = write_ugrid_net(tmp_path / "t_net.nc", GRID,
                               bed_elevation=_bed(), crs_epsg=32644)
        ds = nc.Dataset(path)
        try:
            assert "UGRID-1.0" in ds.Conventions
            assert ds.variables["mesh2d"].cf_role == "mesh_topology"
            assert ds.variables["mesh2d"].topology_dimension == 2
            for name in ("mesh2d_node_x", "mesh2d_node_y", "mesh2d_node_z",
                         "mesh2d_face_x", "mesh2d_face_y",
                         "mesh2d_edge_nodes", "mesh2d_face_nodes"):
                assert name in ds.variables, f"missing {name}"
        finally:
            ds.close()

    def test_node_coordinates_span_the_domain(self, tmp_path):
        import netCDF4 as nc

        path = write_ugrid_net(tmp_path / "t_net.nc", GRID, bed_elevation=_bed())
        ds = nc.Dataset(path)
        try:
            x = ds.variables["mesh2d_node_x"][:]
            y = ds.variables["mesh2d_node_y"][:]
            # x0/y0 is the lower-left CORNER, so nodes run corner to corner.
            assert x.min() == pytest.approx(GRID["x0"])
            assert x.max() == pytest.approx(GRID["x0"] + GRID["nx"] * GRID["dx"])
            assert y.min() == pytest.approx(GRID["y0"])
            assert y.max() == pytest.approx(GRID["y0"] + GRID["ny"] * GRID["dy"])
        finally:
            ds.close()

    def test_connectivity_is_one_based(self, tmp_path):
        """D-Flow FM expects start_index = 1; zero-based indices shift the mesh."""
        import netCDF4 as nc

        path = write_ugrid_net(tmp_path / "t_net.nc", GRID, bed_elevation=_bed())
        ds = nc.Dataset(path)
        try:
            for name in ("mesh2d_edge_nodes", "mesh2d_face_nodes"):
                assert ds.variables[name].start_index == 1
                assert ds.variables[name][:].min() == 1
        finally:
            ds.close()

    def test_bed_level_shape_mismatch_raises(self, tmp_path):
        with pytest.raises(UgridError, match="does not match"):
            write_ugrid_net(tmp_path / "t_net.nc", GRID,
                            bed_elevation=np.zeros((9, 9)))

    def test_node_bed_levels_bracket_the_cell_values(self, tmp_path):
        """Node z is an average of neighbouring cells, so it cannot exceed them."""
        import netCDF4 as nc

        bed = _bed()
        path = write_ugrid_net(tmp_path / "t_net.nc", GRID, bed_elevation=bed)
        ds = nc.Dataset(path)
        try:
            node_z = ds.variables["mesh2d_node_z"][:]
            assert node_z.min() >= bed.min() - 1e-9
            assert node_z.max() <= bed.max() + 1e-9
        finally:
            ds.close()


# ─── TestDfmModel ─────────────────────────────────────────────────────────────

class TestDfmModel:
    """The complete input set, and the couplings the kernel enforces."""

    def _build(self, tmp_path, **kwargs):
        bed = _bed()
        water = dam_break_fields(GRID, bed, reservoir_level_m=8.0, dam_index=2)
        params = dict(output_dir=tmp_path / "model", grid_dict=GRID,
                      bed_elevation=bed, initial_water_level=water,
                      duration_s=60.0, name="case", crs_epsg=32644)
        params.update(kwargs)
        return build_dfm_model(**params)

    def test_writes_every_required_input(self, tmp_path):
        model = self._build(tmp_path)
        for key in ("mdu_path", "net_path", "sample_path", "inifield_path",
                    "dimr_path"):
            assert model[key].exists(), f"{key} was not written"

    def test_mdu_declares_node_bed_levels(self, tmp_path):
        """
        BedlevType must match the mesh.

        The mesh carries mesh2d_node_z, so the .mdu has to say BedlevType = 3.
        Declaring 1 (cell centres) makes the kernel abort with "bed-level type
        and conveyance type do not match" — verified against the real kernel.
        """
        model = self._build(tmp_path)
        mdu = model["mdu_path"].read_text(encoding="utf-8")
        assert f"BedlevType            = {BEDLEVTYPE_NODES}" in mdu
        assert model["net_path"].name in mdu

    def test_mdu_points_at_the_initial_field(self, tmp_path):
        """A uniform WaterLevIni is a lake at rest, not a dam break."""
        model = self._build(tmp_path)
        mdu = model["mdu_path"].read_text(encoding="utf-8")
        assert "IniFieldFile          = initial.ini" in mdu

    def test_sample_file_has_one_row_per_cell(self, tmp_path):
        model = self._build(tmp_path)
        rows = model["sample_path"].read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == GRID["nx"] * GRID["ny"]

    def test_observation_points_produce_an_obs_file(self, tmp_path):
        model = self._build(tmp_path, observation_points=[
            {"name": "Koteshwar", "x": 600250.0, "y": 3350150.0}])
        assert model["obs_path"] is not None and model["obs_path"].exists()
        text = model["obs_path"].read_text(encoding="utf-8")
        assert "Koteshwar" in text
        assert "ObsFile" in model["mdu_path"].read_text(encoding="utf-8")

    def test_dimr_config_names_the_model(self, tmp_path):
        model = self._build(tmp_path)
        xml = model["dimr_path"].read_text(encoding="utf-8")
        assert "<library>dflowfm</library>" in xml
        assert model["mdu_path"].name in xml

    def test_field_shape_mismatch_raises(self, tmp_path):
        with pytest.raises(ValueError, match="different ground"):
            build_dfm_model(output_dir=tmp_path / "bad", grid_dict=GRID,
                            bed_elevation=np.zeros((2, 2)),
                            initial_water_level=np.zeros((2, 2)),
                            duration_s=10.0)

    def test_dam_break_fields_are_a_step_not_a_flat_lake(self, tmp_path):
        """The discontinuity IS the dam break; without it nothing moves."""
        bed = _bed()
        water = dam_break_fields(GRID, bed, reservoir_level_m=8.0, dam_index=2)
        depth = water - bed
        assert depth[:2, :].max() > 0.0, "no water upstream of the dam"
        assert np.allclose(depth[2:, :], 0.0), "downstream must start dry"

    def test_dam_break_never_puts_water_below_the_bed(self):
        bed = _bed()
        water = dam_break_fields(GRID, bed, reservoir_level_m=3.0, dam_index=3)
        assert np.all(water >= bed - 1e-9)


# ─── TestRitterExact ──────────────────────────────────────────────────────────

class TestRitterExact:
    """The analytical solution both engines are scored against."""

    def test_depth_at_the_dam_is_four_ninths(self):
        h_exact, _ = ritter_exact(np.array([0.0]), t=10.0, h_left=10.0)
        assert h_exact[0] == pytest.approx(4.0 * 10.0 / 9.0, rel=1e-12)

    def test_front_advances_at_twice_the_celerity(self):
        h_left, t = 10.0, 20.0
        c0 = np.sqrt(9.81 * h_left)
        just_inside, just_outside = 2.0 * c0 * t - 1.0, 2.0 * c0 * t + 1.0
        h_exact, _ = ritter_exact(np.array([just_inside, just_outside]), t, h_left)
        assert h_exact[0] > 0.0
        assert h_exact[1] == 0.0

    def test_reservoir_stays_undisturbed_behind_the_rarefaction(self):
        h_left, t = 10.0, 20.0
        c0 = np.sqrt(9.81 * h_left)
        h_exact, _ = ritter_exact(np.array([-c0 * t - 50.0]), t, h_left)
        assert h_exact[0] == pytest.approx(h_left)

    def test_zero_time_raises(self):
        with pytest.raises(ValueError):
            ritter_exact(np.array([0.0]), t=0.0)


# ─── TestKernelDiscovery ──────────────────────────────────────────────────────

class TestKernelDiscovery:
    """Finding and launching the kernel — where the adapter used to fail."""

    def test_bad_explicit_path_does_not_fall_back_to_path(self):
        """
        A wrong JALRAKSHA_DFLOWFM_EXE is a configuration error, not a licence
        to silently run some other binary.
        """
        assert resolve_dflowfm(r"C:\definitely\not\here\dflowfm-cli.exe") is None

    @requires_kernel
    def test_discovers_an_installed_kernel(self):
        assert KERNEL is not None and KERNEL.lower().endswith(".exe")

    @requires_kernel
    def test_kernel_environment_exposes_share_and_lib(self):
        """
        run_dflowfm.bat sets PATH = <root>\\share;<root>\\lib. Without it the
        process dies on missing DLLs with no output at all.
        """
        env = kernel_environment(KERNEL)
        assert "share" in env["PATH"] and "lib" in env["PATH"]


# ─── TestAgainstRealKernel ────────────────────────────────────────────────────

@requires_kernel
@pytest.mark.slow
class TestAgainstRealKernel:
    """End-to-end against the installed Deltares kernel."""

    def test_kernel_runs_a_generated_model_and_writes_netcdf(self, tmp_path):
        import netCDF4 as nc

        from jalraksha.delft3d.runner import _run_dflowfm_binary

        nx, ny = 40, 3
        grid = {"nx": nx, "ny": ny, "dx": 25.0, "dy": 25.0, "x0": 0.0, "y0": 0.0}
        bed = np.zeros((ny, nx))
        water = bed.copy()
        water[:, : nx // 2] = 5.0

        model = build_dfm_model(
            output_dir=tmp_path / "smoke", grid_dict=grid, bed_elevation=bed,
            initial_water_level=water, duration_s=20.0, name="smoke",
            manning_n=0.0, map_interval_s=10.0)

        run = _run_dflowfm_binary(model["mdu_path"], executable=KERNEL,
                                  timeout_s=900)
        assert run["success"], run.get("error") or (run.get("stdout") or "")[-800:]

        map_file = model["output_dir"] / "DFM_OUTPUT_smoke" / "smoke_map.nc"
        assert map_file.exists(), "kernel exited 0 but wrote no map output"

        ds = nc.Dataset(map_file)
        try:
            depth = np.asarray(ds.variables["mesh2d_waterdepth"][:])
        finally:
            ds.close()

        # Opened and inspected, not merely present: the water must have moved
        # downstream, which a lake at rest would not do.
        assert depth.shape[0] > 1
        assert np.isfinite(depth).all()
        downstream = depth[:, depth.shape[1] // 2:]
        assert downstream[-1].max() > 0.01, "no water reached the dry half"
