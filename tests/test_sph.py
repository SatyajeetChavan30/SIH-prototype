"""
Phase 7 SPH Near-Field Coupling Test Suite.

Tests:
  - TestNearFieldDomain: Particle generation, fluid/boundary particle counts, property arrays
  - TestSPHNearFieldSolver: Tait equation pressure, gravity acceleration, position stepping
  - TestSWESPCHCoupling: 1-way SWE->SPH handoff & free surface raster extraction
"""

import numpy as np
import pytest
from jalraksha.sph.domain import NearFieldDomain, generate_near_field_particles
from jalraksha.sph.core import SPHNearFieldSolver, run_near_field_sph
from jalraksha.sph.coupling import handoff_swe_to_sph, extract_sph_free_surface


class TestNearFieldDomain:
    """Test SPH particle domain generation."""

    def test_domain_particle_generation(self):
        domain = NearFieldDomain(
            center_x=500000.0,
            center_y=3350000.0,
            domain_size_m=100.0,
            particle_spacing_m=10.0,
            water_depth_m=20.0,
            bed_elevation_m=100.0,
        )
        res = domain.generate()

        assert res["num_fluid"] > 0
        assert res["num_boundary"] > 0
        assert len(domain.x) == res["num_fluid"] + res["num_boundary"]
        assert np.all(domain.rho == 1000.0)

    def test_factory_function(self):
        domain = generate_near_field_particles(
            center_x=1000.0, center_y=2000.0, domain_size_m=50.0, particle_spacing_m=10.0
        )
        assert domain.num_fluid > 0
        assert domain.num_boundary > 0


class TestSPHNearFieldSolver:
    """Test SPH solver execution & Tait equation of state."""

    def test_tait_pressure_computation(self):
        domain = generate_near_field_particles(
            center_x=1000.0, center_y=2000.0, domain_size_m=50.0, particle_spacing_m=10.0
        )
        solver = SPHNearFieldSolver(domain)

        rho = np.array([1000.0, 1050.0, 950.0], dtype=np.float32)
        p = solver.compute_tait_pressure(rho)

        assert p[0] == 0.0  # At reference density, p = 0
        assert p[1] > 0.0   # Compressed density, p > 0
        assert p[2] == 0.0   # Expanded density clamped to >= 0

    def test_solver_step_updates_positions(self):
        domain = generate_near_field_particles(
            center_x=1000.0, center_y=2000.0, domain_size_m=50.0, particle_spacing_m=10.0
        )
        solver = SPHNearFieldSolver(domain)

        x_init = domain.x.copy()
        res = solver.step(dt=0.05)

        # Fluid particles should have moved due to gravity
        fluid_mask = domain.pid == 0
        assert not np.allclose(domain.x[fluid_mask], x_init[fluid_mask])


class TestSWESPHCoupling:
    """Test 1-way SWE -> SPH coupling & free surface extraction."""

    def test_handoff_swe_to_sph(self):
        domain = generate_near_field_particles(
            center_x=1000.0, center_y=2000.0, domain_size_m=50.0, particle_spacing_m=10.0
        )
        # Handoff 500 m3/s discharge at 5m depth
        domain = handoff_swe_to_sph(
            q_breach_m3_s=500.0, h_breach_m=5.0, near_field_domain=domain, breach_width_m=50.0
        )

        # Inflow velocity should be Q / (h * width) = 500 / (5 * 50) = 2.0 m/s
        fluid_mask = domain.pid == 0
        assert np.max(domain.u[fluid_mask]) >= 2.0

    def test_extract_sph_free_surface(self):
        domain = generate_near_field_particles(
            center_x=1000.0, center_y=2000.0, domain_size_m=50.0, particle_spacing_m=10.0
        )
        xs, ys, depth_2d = extract_sph_free_surface(domain, grid_res_m=10.0)

        assert len(xs) > 0
        assert len(ys) > 0
        assert depth_2d.shape == (len(ys), len(xs))
        assert np.max(depth_2d) > 0.0
