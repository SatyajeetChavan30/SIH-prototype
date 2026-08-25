#!/usr/bin/env python3
"""
Export module tests (Phase 5).

Tests for COG, Shapefile, and KML export functionality.
"""

import os
import tempfile
import numpy as np
import pytest
from pathlib import Path

# Import export functions
from jalraksha.export.geotiff import (
    export_raster_to_cog,
    export_ensemble_to_cogs,
    validate_cog,
)
from jalraksha.export.shapefile import (
    raster_to_inundation_polygon,
    export_inundation_polygon,
    export_hazard_classification_polygons,
    export_arrival_time_contours,
)
from jalraksha.export.kml import (
    export_inundation_kml,
    export_time_animated_kml,
    export_depth_ground_overlay,
    export_kmz,
)


class TestCOGExport:
    """Cloud-Optimized GeoTIFF export tests."""

    def setup_method(self):
        """Create temporary directory and test data."""
        self.temp_dir = tempfile.mkdtemp()

        # Create synthetic grid
        self.grid_dict = {
            "nx": 100,
            "ny": 80,
            "dx": 30.0,
            "dy": 30.0,
            "x0": 78.0 * 1000.0,  # UTM coordinates
            "y0": 30.0 * 1000.0,
        }

        # Create synthetic raster data
        self.raster_data = np.zeros((self.grid_dict["ny"], self.grid_dict["nx"]), dtype=np.float32)

        # Add some features
        y, x = np.ogrid[:self.grid_dict["ny"], :self.grid_dict["nx"]]
        center_y, center_x = self.grid_dict["ny"] // 2, self.grid_dict["nx"] // 2
        radius = min(self.grid_dict["ny"], self.grid_dict["nx"]) // 4

        # Circular flood pattern
        mask = (x - center_x)**2 + (y - center_y)**2 <= radius**2
        self.raster_data[mask] = np.linspace(0.1, 5.0, np.sum(mask), dtype=np.float32)

    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cog_export_basic(self):
        """Test basic COG export functionality."""
        output_path = os.path.join(self.temp_dir, "test_cog.tif")

        result = export_raster_to_cog(
            self.raster_data,
            output_path,
            self.grid_dict,
            crs_epsg=32643,
            data_name="test_depth",
        )

        assert result == output_path
        assert os.path.exists(output_path)
        assert Path(output_path).stat().st_size > 1000  # Should be >1KB

    def test_cog_validation(self):
        """Test COG file validation."""
        output_path = os.path.join(self.temp_dir, "test_validate.tif")

        export_raster_to_cog(
            self.raster_data,
            output_path,
            self.grid_dict,
            crs_epsg=32643,
        )

        is_valid = validate_cog(output_path)
        assert is_valid is True

    def test_cog_metadata(self):
        """Test COG metadata embedding."""
        output_path = os.path.join(self.temp_dir, "test_metadata.tif")

        metadata = {
            "DAM": "Tehri",
            "SCENARIO": "test",
            "RESOLUTION": "30m",
        }

        export_raster_to_cog(
            self.raster_data,
            output_path,
            self.grid_dict,
            crs_epsg=32643,
            data_name="h_max",
            metadata_tags=metadata,
        )

        # Verify file exists and is valid
        assert os.path.exists(output_path)
        assert validate_cog(output_path)

    def test_ensemble_export(self):
        """Test ensemble COG export (median, p05, p95)."""
        # Create synthetic ensemble
        ensemble = []
        for i in range(10):
            # Vary the flood pattern slightly
            data = self.raster_data * (1.0 + 0.1 * np.random.randn(*self.raster_data.shape))
            data = np.maximum(data, 0.0)  # Ensure non-negative
            ensemble.append({
                "h_max": data,
                "v_max": data * 0.5,  # Simplified velocity
                "t_arrival": np.where(data > 0.1, 3600.0 * np.random.rand(*data.shape), np.inf),
                "metadata": {"member": i},
            })

        output_dir = os.path.join(self.temp_dir, "ensemble")
        result = export_ensemble_to_cogs(
            ensemble,
            self.grid_dict,
            output_dir,
            dam_name="TestDam",
        )

        # Should create 9 files (3 variables × 3 percentiles)
        expected_files = [
            "h_max_median_cog.tif",
            "h_max_p05_cog.tif",
            "h_max_p95_cog.tif",
            "v_max_median_cog.tif",
            "v_max_p05_cog.tif",
            "v_max_p95_cog.tif",
            "t_arrival_median_cog.tif",
            "t_arrival_p05_cog.tif",
            "t_arrival_p95_cog.tif",
        ]

        for fname in expected_files:
            full_path = os.path.join(output_dir, fname)
            assert os.path.exists(full_path), f"Missing file: {full_path}"
            assert validate_cog(full_path), f"Invalid COG: {full_path}"

        assert len(result) == 9


class TestShapefileExport:
    """Shapefile export tests."""

    def setup_method(self):
        """Create temporary directory and test data."""
        self.temp_dir = tempfile.mkdtemp()

        # Create synthetic grid
        self.grid_dict = {
            "nx": 50,
            "ny": 40,
            "dx": 30.0,
            "dy": 30.0,
            "x0": 78.0 * 1000.0,
            "y0": 30.0 * 1000.0,
        }

        # Create synthetic flood depth
        self.h_max = np.zeros((self.grid_dict["ny"], self.grid_dict["nx"]), dtype=np.float32)

        # Add flood pattern
        y, x = np.ogrid[:self.grid_dict["ny"], :self.grid_dict["nx"]]
        center_y, center_x = self.grid_dict["ny"] // 2, self.grid_dict["nx"] // 2

        # Circular flood
        radius = 15
        mask = (x - center_x)**2 + (y - center_y)**2 <= radius**2
        self.h_max[mask] = 2.5  # 2.5m depth

    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_inundation_polygon_generation(self):
        """Test raster to inundation polygon conversion."""
        polygon = raster_to_inundation_polygon(
            self.h_max,
            self.grid_dict,
            depth_threshold=0.1,
        )

        assert polygon is not None
        assert polygon["type"] == "Polygon"
        assert len(polygon["coordinates"]) == 1
        assert len(polygon["coordinates"][0]) > 10  # Should have multiple points
        assert polygon["properties"]["area_m2"] > 0
        assert polygon["properties"]["max_depth_m"] > 0

    def test_inundation_shapefile_export(self):
        """Test inundation polygon Shapefile export."""
        output_path = os.path.join(self.temp_dir, "inundation.shp")

        result = export_inundation_polygon(
            self.h_max,
            self.grid_dict,
            output_path,
            depth_threshold=0.1,
            dam_name="TestDam",
        )

        assert result == output_path
        assert os.path.exists(output_path)

        # Check for accompanying files
        base_path = os.path.splitext(output_path)[0]
        for ext in [".shp", ".shx", ".dbf", ".prj"]:
            assert os.path.exists(base_path + ext), f"Missing Shapefile component: {base_path + ext}"

    def test_hazard_classification(self):
        """Test hazard classification polygon export."""
        # Create velocity data
        v_max = np.zeros_like(self.h_max)
        v_max[self.h_max > 0] = 1.5  # 1.5 m/s velocity

        output_path = os.path.join(self.temp_dir, "hazard.shp")

        result = export_hazard_classification_polygons(
            self.h_max,
            v_max,
            self.grid_dict,
            output_path,
            dam_name="TestDam",
        )

        assert result is not None
        # Should have at least one hazard class
        assert len(result) > 0

        # Check that files were created
        for cls, path in result.items():
            assert os.path.exists(path)

    def test_arrival_time_contours(self):
        """Test arrival time contour export."""
        # Create synthetic arrival times with radial distance gradient
        y, x = np.ogrid[:self.grid_dict["ny"], :self.grid_dict["nx"]]
        center_y, center_x = self.grid_dict["ny"] // 2, self.grid_dict["nx"] // 2
        dist = np.sqrt((x - center_x)**2 + (y - center_y)**2) * 100.0
        t_arrival = np.where(self.h_max > 0, dist, np.inf).astype(np.float32)

        output_path = os.path.join(self.temp_dir, "contours.shp")

        result = export_arrival_time_contours(
            t_arrival,
            self.grid_dict,
            output_path,
            iso_times_s=[50, 100, 150],
        )

        assert result is not None
        assert os.path.exists(result)


class TestKMLExport:
    """KML/KMZ export tests."""

    def setup_method(self):
        """Create temporary directory and test data."""
        self.temp_dir = tempfile.mkdtemp()

        # Create synthetic grid
        self.grid_dict = {
            "nx": 30,
            "ny": 25,
            "dx": 30.0,
            "dy": 30.0,
            "x0": 78.0 * 1000.0,
            "y0": 30.0 * 1000.0,
        }

        # Create synthetic flood depth
        self.h_max = np.zeros((self.grid_dict["ny"], self.grid_dict["nx"]), dtype=np.float32)

        # Add flood pattern
        y, x = np.ogrid[:self.grid_dict["ny"], :self.grid_dict["nx"]]
        center_y, center_x = self.grid_dict["ny"] // 2, self.grid_dict["nx"] // 2

        # Circular flood
        radius = 10
        mask = (x - center_x)**2 + (y - center_y)**2 <= radius**2
        self.h_max[mask] = 3.0  # 3.0m depth

    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_inundation_kml_export(self):
        """Test inundation KML export."""
        output_path = os.path.join(self.temp_dir, "inundation.kml")

        result = export_inundation_kml(
            self.h_max,
            self.grid_dict,
            output_path,
            depth_threshold=0.1,
            dam_name="TestDam",
        )

        assert result == output_path
        assert os.path.exists(output_path)

        # Check KML content
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert '<kml' in content
            assert 'TestDam' in content
            assert 'Inundation Envelope' in content

    def test_time_animated_kml(self):
        """Test time-animated KML export."""
        # Create time series
        time_steps = [0.0, 300.0, 600.0, 900.0]  # 0, 5, 10, 15 minutes

        h_series = []
        for t in time_steps:
            # Expanding flood wave
            h = np.zeros_like(self.h_max)
            radius = 5 + int(t / 100)
            y, x = np.ogrid[:self.grid_dict["ny"], :self.grid_dict["nx"]]
            center_y, center_x = self.grid_dict["ny"] // 2, self.grid_dict["nx"] // 2
            mask = (x - center_x)**2 + (y - center_y)**2 <= radius**2
            h[mask] = 2.0
            h_series.append(h)

        output_path = os.path.join(self.temp_dir, "animation.kml")

        result = export_time_animated_kml(
            time_steps,
            h_series,
            self.grid_dict,
            output_path,
            depth_threshold=0.1,
            dam_name="TestDam",
        )

        assert result == output_path
        assert os.path.exists(output_path)

        # Check for time elements
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert '<TimeSpan>' in content
            assert 'TestDam' in content

    def test_kmz_bundling(self):
        """Test KMZ file bundling."""
        # Create a KML file first
        kml_path = os.path.join(self.temp_dir, "test.kml")
        with open(kml_path, 'w', encoding='utf-8') as f:
            f.write('''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Test</name>
      <Point><coordinates>0,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>''')

        # Create an asset file
        asset_path = os.path.join(self.temp_dir, "test.png")
        with open(asset_path, 'wb') as f:
            f.write(b'PNG')  # Minimal fake PNG

        kmz_path = os.path.join(self.temp_dir, "test.kmz")

        result = export_kmz(
            kml_path,
            asset_paths=[asset_path],
            output_path=kmz_path,
        )

        assert result == kmz_path
        assert os.path.exists(kmz_path)
        assert Path(kmz_path).stat().st_size > 100  # Should be >100 bytes


class TestExportIntegration:
    """Integration tests with Phase 4 pipeline."""

    def test_phase4_export_integration(self):
        """Test that export works with Phase 4 results structure."""
        # This would be a more comprehensive test that integrates with
        # the actual Phase 4 pipeline results
        pass  # Placeholder for future integration test


if __name__ == "__main__":
    pytest.main([__file__, "-v"])