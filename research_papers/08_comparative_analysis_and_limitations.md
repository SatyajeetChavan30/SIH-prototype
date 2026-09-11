# Comparative Analysis: Limitations of Existing Projects & How JalRaksha Improves Upon Them

**Author**: JalRaksha Team  
**Date**: August 24, 2026  
**Scope**: Technical comparison of existing dam-break & hydrodynamic modeling software vs. JalRaksha architecture.

---

## 🎯 The Main Problem JalRaksha Solves

**Existing dam-break tools forced disaster managers into a false choice between computational impossibility and physics oversimplification:**

1. **Pure 3D SPH tools** (DualSPHysics, GPUSPH) capture violent 3D dam collapse physics, but **crash or take days/weeks** when run across a 60 km river valley (*SPHERIC Grand Challenge 3, Vacondio et al. 2020*).
2. **Traditional 2D tools** (Delft3D, HEC-RAS 2D) run quickly down long river channels, but **completely flatten the 3D dam collapse**, ignoring vertical accelerations, plunging wave momentum, and overtopping dynamics during early breach.
3. **Single Deterministic Inputs**: Most software relies on a single guessed hydrograph. If that single breach scenario prediction is off by 30 minutes, emergency evacuation warnings fail.
4. **Desktop GUI & Geo-Fenced Data Dependencies**: Tools like HEC-RAS require manual Windows desktop GUI steps, while regional models depend on geo-fenced portals (India-WRIS, Bhuvan) that break or require logins during crisis situations.

### How JalRaksha Solves This:
* **Domain Decomposition**: 3D SPH (near-field breach) $\rightarrow$ 2D Finite-Volume SWE (far-field 60+ km). Achieves **3D breach physics near the dam** and **high-speed routing down the valley**.
* **100-Member Monte Carlo Risk Bands**: Automated ensemble running 4 breach regression models with Wahl (2004) uncertainty bounds, providing **best-case, median, and worst-case arrival times** (5th–95th percentiles) for downstream towns.
* **100% Offline-First Open Data Engine**: Automated fetch of Copernicus GLO-30 DEMs cached locally, running from a headless Python CLI (`jalraksha run`) without requiring internet access during live disaster events.

---

## 📊 Summary Comparison Matrix

| Feature / Capability | Delft3D-FLOW | HEC-RAS 2D | Full 3D SPH (DualSPHysics) | ANUGA / GeoClaw | **JalRaksha (This Project)** |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Physics Model** | 2D/3D Hydrostatic (SWE) | 2D Shallow Water | 3D Navier-Stokes (Lagrangian) | 2D Shallow Water | **Domain Decomposition (3D SPH + 2D SWE)** |
| **Near-Field Breach Mechanics** | Depth-averaged approximation | Simplified weir equation | Full 3D violent free-surface | Depth-averaged approximation | **3D SPH near-field wave & plunging resolution** |
| **Far-Field Scalability (60+ km)** | High | High | Exceedingly Low (Memory OOM) | High | **High (2D FV with Numba JIT acceleration)** |
| **Uncertainty Quantification** | Manual scenario setup | Single hydrograph input | N/A (Too slow for ensembles) | Manual scenario setup | **Automated 100-member Monte Carlo (Wahl bands)** |
| **Data Dependencies** | Manual grid/bathymetry | Manual GIS setup | Manual CAD/mesh input | Manual DEM preparation | **Automated Copernicus GLO-30 DEM fetch & cache** |
| **Offline Resilience** | Varies | Desktop local | Desktop local | Varies | **Strictly Offline-First local caching** |
| **Automation & CLI** | GUI / Complex script | Windows GUI / RAS-Mapper | Script / GPU execution | Python API | **Headless Python CLI (`jalraksha run`)** |
| **Software License** | AGPL-3.0 / Mixed | Public Domain (Windows GUI) | LGPL-3.0 (Copyleft) | GPL-3.0 | **MIT / BSD (Permissive Open Source)** |

---

## 🚨 Limitations of Existing Systems

### 1. Delft3D / D-Flow Flexible Mesh (Deltares)
* **Kernel Compilation Complexity**: The computational solver is compiled Fortran/C++ code. Python tools (`hydromt`, `hydrolib-core`) only manage input text files and grid configuration—they do **not** include an executable solver binary. This creates heavy compilation and containerization friction during emergency field deployments.
* **Lack of 3D Breach Mechanics**: Delft3D relies on depth-averaged hydrostatic shallow water equations. It cannot capture non-hydrostatic vertical accelerations, dam overtopping momentum, or 3D plunging wave structures during early failure.
* **Complex Grid Generation**: Requires curvilinear or flexible mesh construction that demands significant manual operator tuning.

### 2. HEC-RAS 2D (USACE)
* **Windows GUI Lock-In**: Heavily reliant on a desktop user interface (RAS-Mapper). It cannot easily be deployed as a headless, containerized cloud service or driven via automated headless Python pipelines.
* **Deterministic Single-Hydrograph Output**: Breach parameters are specified deterministically without automated Monte Carlo sampling across regression uncertainty bands (e.g. Wahl 5th–95th bounds).
* **Pure 2D Assumption**: Neglects 3D fluid-structure breach effects.

### 3. Pure 3D SPH (DualSPHysics, GPUSPH, Pure PySPH)
* **Computational Explosion over River Basins**: As highlighted in SPHERIC Grand Challenge 3 (*Vacondio et al., 2020*), uniform particle spacing over 60 km valleys requires billions of particles, leading to out-of-memory crashes or multi-day runtime.
* **Licensing Barriers**: DualSPHysics (LGPL) and GPUSPH (GPLv3) carry copyleft restrictions that complicate integration into proprietary or government platforms.

### 4. GeoClaw / LISFLOOD-FP / ANUGA
* **Mountainous Bathymetry Instabilities**: Suffer from wet/dry instabilities or spurious artificial velocities on steep mountain slopes unless specifically equipped with well-balanced hydrostatic reconstruction.
* **Geo-Fenced Data Gateways**: Often rely on regional data portals (such as India-WRIS or CartoDEM) that suffer from downtime, broken APIs, or geo-fencing.

---

## 🚀 How JalRaksha Does It Better

### 1. Domain Decomposition (3D SPH $\rightarrow$ 2D Finite-Volume SWE)
* **Best of Both Worlds**: Uses 3D SPH (via IIT Bombay's BSD-licensed PySPH) to capture violent near-field breach mechanics at the dam site (first few hundred meters), then passes boundary conditions to a 2D Finite-Volume Shallow Water solver for far-field propagation across 60+ km.
* **Literature-Backed Architecture**: Aligns directly with the state-of-the-art recommendations of *Maranzoni & Tomirotti (2023)* and *Vacondio et al. (2020)*.

### 2. Automated 100-Member Monte Carlo Uncertainty Ensembles
* Combines **4 empirical regression families** (Froehlich 1995b, Von Thun & Gillette 1990, MacDonald 1984, Xu & Zhang 2009) with **Wahl (2004) error bands** ($5^{\text{th}}$ to $95^{\text{th}}$ percentiles).
* Automatically runs level-pool ODE reservoir depletion to output **median, 5th, and 95th percentile flood arrival times and maximum depth envelopes**, rather than a single deterministic guess.

### 3. Open Data & 100% Offline-First Architecture
* Automatically fetches public **Copernicus GLO-30 DEM** data via public AWS COGs and caches it locally.
* Zero dependence on geo-fenced or login-gated portals (strictly avoids India-WRIS, Bhuvan, or CartoDEM), ensuring guaranteed execution on offline field hardware during disaster events.

### 4. Well-Balanced Hydrostatic Reconstruction & High Performance
* Implements **Audusse et al. (2004)** hydrostatic reconstruction and **HLLC Riemann fluxes with Numba `@njit` JIT acceleration**, guaranteeing zero spurious velocities over steep Himalayan terrain (e.g. Tehri valley).

### 5. Permissive Open-Source Licensing
* Built using **MIT and BSD licensed components** (NumPy, SciPy, Numba, PySPH, Rasterio), allowing unrestricted distribution and adoption by government and emergency agencies.
