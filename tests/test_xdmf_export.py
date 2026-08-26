"""
Smoke checks for the XDMF+HDF5 contract (spec section 6).

The point of these is narrow but important: prove the file we write is actually
readable by ParaView's own reader family, with the arrays, timesteps and
orientation we claim. Two real defects were found this way and would otherwise
have surfaced only as a wrong-looking 3D scene:

  * a 2DCoRectMesh declaration put easting/northing on VTK's Y/Z axes, leaving X
    degenerate, so the terrain stood vertically;
  * the 3-component velocity array failed to load entirely because the DataItem
    dimensions did not match the HDF5 dataspace.

Tests that need VTK skip cleanly when it is absent — it is a verification
dependency, not a runtime one.
"""

import numpy as np
import pytest

from jalraksha.export.xdmf_export import (
    XdmfExportError,
    frames_from_result,
    write_xdmf_series,
)

vtk = pytest.importorskip("vtk", reason="vtk is a verification-only dependency")


NY, NX, NT = 7, 5, 4
GRID = {"nx": NX, "ny": NY, "dx": 400.0, "dy": 400.0,
        "x0": 200000.0, "y0": 3300000.0, "crs": "EPSG:32644"}


def _terrain():
    """Ramps with row AND column so a transpose or flip is detectable."""
    return (np.arange(NY)[:, None] * 100.0 + np.arange(NX)[None, :]).astype(np.float32)


def _frames(n=NT):
    return [{
        "time_s": float(k * 60),
        "depth": np.full((NY, NX), float(k), dtype=np.float32),
        "velocity_x": np.full((NY, NX), float(k) * 0.5, dtype=np.float32),
        "velocity_y": np.zeros((NY, NX), dtype=np.float32),
    } for k in range(n)]


def _write(tmp_path, frames=None, is_synthetic=False):
    return write_xdmf_series(tmp_path / "sim", GRID, _terrain(), frames,
                             is_synthetic=is_synthetic)


def _read(path):
    reader = vtk.vtkXdmfReader()
    reader.SetFileName(str(path))
    reader.UpdateInformation()
    info = reader.GetOutputInformation(0)
    key = vtk.vtkStreamingDemandDrivenPipeline.TIME_STEPS()
    times = [info.Get(key, i) for i in range(info.Length(key))] if info.Has(key) else []
    reader.Update()
    out = reader.GetOutputDataObject(0)
    if hasattr(out, "NewIterator"):
        it = out.NewIterator()
        it.InitTraversal()
        out = it.GetCurrentDataObject()
    return out, times


class TestContract:
    def test_hdf5_round_trip(self, tmp_path):
        import h5py

        path = _write(tmp_path, _frames())
        with h5py.File(path.with_suffix(".h5")) as h5:
            # Terrain stored exactly ONCE, not per timestep — the reason for XDMF.
            assert h5["terrain_elevation"].shape == (1, NY, NX)
            assert h5["terrain_elevation"].dtype == np.float32
            assert len(h5["water_depth"]) == NT
            assert h5["velocity"]["0000"].shape == (1, NY, NX, 3)
            assert h5.attrs["crs"] == "EPSG:32644"

    def test_rejects_non_epsg_crs(self, tmp_path):
        bad = dict(GRID, crs="some-local-grid")
        with pytest.raises(XdmfExportError, match="EPSG"):
            write_xdmf_series(tmp_path / "s", bad, _terrain(), _frames())

    def test_rejects_shape_mismatch(self, tmp_path):
        frames = _frames(1)
        frames[0]["depth"] = np.zeros((NY + 1, NX), dtype=np.float32)
        with pytest.raises(XdmfExportError, match="shape"):
            write_xdmf_series(tmp_path / "s", GRID, _terrain(), frames)

    def test_rejects_non_increasing_times(self, tmp_path):
        frames = _frames(3)
        frames[2]["time_s"] = 0.0
        with pytest.raises(XdmfExportError, match="increasing"):
            write_xdmf_series(tmp_path / "s", GRID, _terrain(), frames)

    def test_missing_velocity_is_reported_not_zero_filled(self):
        """A pre-velocity run must fail loudly, not export still water."""
        result = {"depth_series": [{"time_s": 0.0, "depth": np.zeros((NY, NX))}]}
        with pytest.raises(XdmfExportError, match="velocity"):
            frames_from_result(result)


class TestParaViewReader:
    """Everything here goes through the reader family ParaView itself uses."""

    def test_timesteps_are_reported(self, tmp_path):
        path = _write(tmp_path, _frames())
        _, times = _read(path)
        assert times == [0.0, 60.0, 120.0, 180.0]

    def test_grid_lands_in_the_xy_plane(self, tmp_path):
        """Regression: 2DCoRectMesh put easting/northing on Y/Z with X degenerate."""
        path = _write(tmp_path, _frames())
        ds, _ = _read(path)
        assert ds.GetDimensions() == (NX, NY, 1)
        xmin, xmax, ymin, ymax, zmin, zmax = ds.GetBounds()
        assert xmin == pytest.approx(GRID["x0"] + GRID["dx"] / 2)
        assert xmax > xmin, "X must span easting, not be degenerate"
        assert ymax > ymin, "Y must span northing"
        assert zmin == zmax == 0.0, "single-layer slab must be flat in Z"

    def test_all_arrays_present_and_velocity_is_a_vector(self, tmp_path):
        """Regression: the 3-component velocity array failed to load at all."""
        path = _write(tmp_path, _frames())
        ds, _ = _read(path)
        pd = ds.GetPointData()
        names = {pd.GetArrayName(i) for i in range(pd.GetNumberOfArrays())}
        assert {"terrain_elevation", "water_depth",
                "velocity", "velocity_magnitude"} <= names
        assert pd.GetArray("velocity").GetNumberOfComponents() == 3

    def test_row_zero_is_south_and_x_varies_fastest(self, tmp_path):
        path = _write(tmp_path, _frames())
        ds, _ = _read(path)
        terr = _terrain()
        arr = ds.GetPointData().GetArray("terrain_elevation")
        assert arr.GetTuple1(0) == terr[0, 0]
        assert arr.GetTuple1(1) == terr[0, 1], "x must vary fastest"
        assert arr.GetTuple1(NX) == terr[1, 0], "row 0 must be southernmost"

    @pytest.mark.parametrize("flag", [True, False])
    def test_is_synthetic_survives_the_reader(self, tmp_path, flag):
        """A banner flag that does not reach ParaView fails toward looking correct."""
        path = _write(tmp_path, _frames(), is_synthetic=flag)
        ds, _ = _read(path)
        fd = ds.GetFieldData()
        arr = fd.GetArray("is_synthetic")
        assert arr is not None, "is_synthetic must arrive as field data"
        assert arr.GetTuple1(0) == float(flag)


def test_terrain_only_dataset_is_valid(tmp_path):
    """Phase 1 renders terrain before any solver exists."""
    path = _write(tmp_path, None)
    ds, times = _read(path)
    assert len(times) <= 1
    depth = ds.GetPointData().GetArray("water_depth")
    assert depth is not None
    assert all(depth.GetTuple1(i) == 0.0 for i in range(depth.GetNumberOfTuples()))
