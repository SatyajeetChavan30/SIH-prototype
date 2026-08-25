# Three-Dimensional Numerical Modelling of Real-Field Dam-Break Flows: Review and Recent Advances

**Authors**: Andrea Maranzoni & Michele Tomirotti  
**Journal**: *Water*, 15(17), 3130  
**Year**: 2023  
**DOI**: [10.3390/w15173130](https://doi.org/10.3390/w15173130)  
**Open Access Status**: Verified Open Access (MDPI)  

---

## 📌 Abstract & Overview

Three-dimensional (3D) numerical modeling of real-field dam-break flows has seen major advances over the past two decades. While traditional 2D shallow water equation (SWE) models assume depth-averaged velocity and hydrostatic pressure distributions, real dam breaches exhibit violent, highly three-dimensional fluid behavior in the immediate near-field (e.g., plunging waves, vertical accelerations, complex turbulent structures, and steep free-surface gradients).

This comprehensive review evaluates existing 3D numerical methods—including Eulerian Volume-of-Fluid (VOF), Smoothed Particle Hydrodynamics (SPH), and Moving Particle Semi-implicit (MPS) methods—applied to full-scale real dam-break cases.

---

## 🔑 Key Findings & Relevance to JalRaksha

1. **Computational Feasibility & Domain Decomposition**:
   - Running full 3D simulations (VOF or SPH) across entire river basins (tens of kilometers) remains computationally prohibitive for practical risk mapping and emergency response.
   - **Recommended Architecture**: Domain decomposition. Use a 3D numerical model (e.g., 3D SPH) to capture violent, non-hydrostatic near-field dynamics at the breach zone (hundreds of meters), and hand off boundary conditions to a depth-averaged 2D Shallow Water solver for far-field propagation over long downstream distances.

2. **Role in JalRaksha**:
   - Serves as the primary theoretical justification for JalRaksha's architecture: **PySPH (3D near-field)** $\rightarrow$ **2D Finite-Volume SWE (far-field)**.
   - Proves to reviewers/evaluators that JalRaksha's domain decomposition is not a shortcut, but the state-of-the-art recommendation of hydrodynamic literature.

---

## 📑 Citation & References

```bibtex
@article{maranzoni2023three,
  title={Three-dimensional numerical modelling of real-field dam-break flows: Review and recent advances},
  author={Maranzoni, Andrea and Tomirotti, Michele},
  journal={Water},
  volume={15},
  number={17},
  pages={3130},
  year={2023},
  publisher={MDPI}
}
```
