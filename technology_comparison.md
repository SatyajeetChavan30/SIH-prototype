# Technology Comparison: Existing Solutions vs JalRaksha

**Date:** 2026-08-30  
**Project:** JalRaksha — Dam-Break Flood Screening System  
**Purpose:** Smart India Hackathon 2026, PS 26161 (NTRO)

---

## Table of Contents

1. Comprehensive Technology Comparison Matrix
2. Detailed Feature-by-Feature Comparison
3. Physics & Numerical Methods Comparison
4. Data Pipeline Comparison
5. Deployment & Accessibility Comparison
6. Licensing & Cost Comparison
7. What Makes JalRaksha Different (Summary)

---

## 1. Comprehensive Technology Comparison Matrix

### Primary Dam-Break Modeling Tools

| Capability / Feature | **Delft3D FM** | **HEC-RAS 2D** | **DualSPHysics** | **GeoClaw** | **ANUGA** | **JalRaksha** |
|:---|:---|:---|:---|:---|:---|:---|
| **Developer** | Deltares (NL) | USACE (USA) | University of Manchester (UK) | University of Washington (USA) | ANU (Australia) | JalRaksha Team (India) |
| **Physics Model** | 2D/3D Hydrostatic SWE | 2D Shallow Water | 3D Navier-Stokes (Lagrangian SPH) | 2D Shallow Water | 2D Shallow Water | **3D SPH (near-field) + 2D SWE (far-field)** |
| **Spatial Dimension** | 2D or 3D (depth-averaged) | 2D only | Full 3D | 2D only | 2D only | **Hybrid: 3D near dam, 2D downstream** |
| **Near-Field Breach** | Depth-averaged approx. | Simplified weir eq. | Full 3D violent free-surface | Depth-averaged approx. | Depth-averaged approx. | **3D SPH wave & plunging resolution** |
| **Far-Field Range** | 60+ km capable | 60+ km capable | **OOM at scale** | 60+ km capable | 60+ km capable | **60+ km with Numba JIT** |
| **Runtime (60 km)** | ~hours | ~minutes-hours | **days-weeks** | ~hours | ~minutes | **minutes (parallel ensemble)** |
| **Uncertainty Quantification** | Manual scenarios | Single hydrograph | N/A (too slow) | Manual scenarios | Manual scenarios | **Automated 100-member Monte Carlo** |
| **DEM Dependency** | Manual grid/bathymetry | Manual GIS setup | Manual CAD/mesh | Manual DEM prep | Manual DEM prep | **Automated Copernicus GLO-30 fetch** |
| **Offline Capability** | Desktop local | Windows GUI | Desktop local | Varies | Varies | **Strictly offline-first cached** |
| **Automation** | GUI + script | Windows GUI | Script/GPU | Python API | Python API | **Headless Python CLI** |
| **Web Dashboard** | No | No | No | No | No | **Yes (React + Leaflet + Cesium)** |
| **Export Formats** | NetCDF, ASCII | HDF5, GIS | CSV, VTK | HDF5, NetCDF | NetCDF, GIS | **GeoTIFF, Shapefile, KML, XDMF** |
| **License** | AGPL-3.0 | Public Domain (GUI) | LGPL-3.0 | GPL-3.0 | GPL-3.0 | **MIT / BSD (permissive)** |
| **Cost** | Free (open source) | Free | Free | Free | Free | **Free** |
| **Indian Dam Presets** | No | No | No | No | No | **Yes (Tehri, Khadakwasla, etc.)** |
| **Real-Time Satellite Overlay** | No | No | No | No | No | **Yes (GEE Sentinel-1 SAR)** |
| **Impact Assessment** | No | No | No | No | No | **Yes (population, damage, fatalities)** |

---

## 2. Detailed Feature-by-Feature Comparison

### 2.1 Physics & Modeling Approach

| Aspect | Delft3D | HEC-RAS 2D | DualSPHysics | JalRaksha |
|:---|:---|:---|:---|:---|
| **Governing Equations** | Saint-Venant (SWE) | Saint-Vokes (SWE) | Navier-Stokes (Lagrangian) | Saint-Venant + SPH |
| **Breach Representation** | Empirical params | Simplified weir | Full 3D particle resolution | 3D SPH near-field + empirical far-field |
| **Vertical Structure** | Depth-averaged | Depth-averaged | Full 3D | 3D at breach, 2D downstream |
| **Turbulence Modeling** | k-epsilon, k-l, constant | Not included | Implicit (particle viscosity) | Manning friction |
| **Wetting/Drying** | Threshold-based | Threshold-based | Natural (particles) | Threshold + well-balanced |
| **Shock Capturing** | Yes (Riemann solver) | Yes | Yes (inherent in SPH) | Yes (HLLC) |

### 2.2 Computational Performance

| Metric | Delft3D | HEC-RAS 2D | DualSPHysics | JalRaksha |
|:---|:---|:---|:---|:---|
| **60 km Domain Runtime** | 2-6 hours | 30-120 minutes | Days-weeks | 10-60 minutes |
| **GPU Acceleration** | No | No | Yes (CUDA) | No (CPU-optimized) |
| **Parallelization** | MPI (limited) | Limited | GPU threading | Multi-core CPU (multiprocessing) |
| **Memory Footprint** | Medium | Low | Very High (billions of particles) | Medium (1000x1000 grid) |
| **Ensemble Capability** | Manual | Manual | Impractical | Automated (100 members) |

### 2.3 Data Requirements

| Data Type | Delft3D | HEC-RAS 2D | DualSPHysics | JalRaksha |
|:---|:---|:---|:---|:---|
| **DEM Source** | Manual import | Manual import | Manual import | **Automated Copernicus GLO-30** |
| **Bathymetry** | Required | Required | Required | Derived from DEM |
| **Roughness** | Manual field | Manual field | N/A | ESA WorldCover auto |
| **Boundary Conditions** | Manual setup | Manual setup | Manual setup | **Auto-generated** |
| **Mesh Generation** | Manual (RGFGRID) | Manual (RAS Mapper) | Manual (CAD) | **Automatic (Cartesian)** |
| **Internet Required** | No | No | No | **No (offline-first)** |

### 2.4 Output & Visualization

| Output Type | Delft3D | HEC-RAS 2D | DualSPHysics | JalRaksha |
|:---|:---|:---|:---|:---|
| **2D Flood Map** | Yes | Yes | Yes (via conversion) | **Yes (Leaflet)** |
| **3D Visualization** | Limited | No | Yes (ParaView) | **Yes (Cesium globe)** |
| **Time Animation** | Yes | Yes | Yes | **Yes (keyframes)** |
| **GIS Export** | NetCDF → GIS | HDF5 → GIS | CSV → GIS | **Direct SHP/KML/GeoTIFF** |
| **Gauge Time Series** | Yes | Yes | Yes | **Yes (arrival times)** |
| **Web Dashboard** | No | No | No | **Yes (React)** |
| **Damage Estimates** | No | No | No | **Yes** |
| **Population at Risk** | No | No | No | **Yes (GHSL)** |

---

## 3. Physics & Numerical Methods Comparison

### 3.1 Shallow Water Equation Solvers

| Numerical Feature | Delft3D | HEC-RAS 2D | GeoClaw | JalRaksha |
|:---|:---|:---|:---|:---|
| **Flux Scheme** | Delft3D scheme | Upwave | F-wave | **HLLC** |
| **Well-Balancing** | Yes | Yes | Yes | **Audusse hydrostatic reconstruction** |
| **Reconstruction** | First-order | First-order | Second-order TVD | **MUSCL (second-order)** |
| **Time Stepping** | Implicit/Explicit | Implicit | Fractional step | **Explicit (CFL-limited)** |
| **Friction Treatment** | Implicit | Implicit | N/A | **Semi-implicit Manning** |
| **Dry Bed Handling** | Threshold | Threshold | Threshold | **Threshold + well-balanced** |

### 3.2 SPH (Particle) Methods

| Feature | DualSPHysics | GPUSPH | PySPH (JalRaksha) |
|:---|:---|:---|:---|
| **Kernel** | Wendland | Wendland/Cubic spline | **Wendland** |
| **Density Filtering** | Yes | Yes | **Yes** |
| **Viscosity** | Artificial/δ-SPH | Artificial | **Artificial** |
| **Boundary Condition** | Dynamic/dummy particles | Dynamic | **One-way coupled to 2D** |
| **GPU Support** | CUDA | CUDA | **No (CPU only)** |
| **Parallelization** | GPU + MPI | GPU | **Multi-core CPU** |

### 3.3 Uncertainty Quantification

| Method | Delft3D | HEC-RAS 2D | JalRaksha |
|:---|:---|:---|:---|
| **Ensemble Approach** | Manual | Manual | **Automated Monte Carlo** |
| **Breach Regressions** | 1 (user picks) | 1 (user picks) | **4 (Froehlich, MacDonald, Wahl, Xu-Zhang)** |
| **Uncertainty Bounds** | None | None | **Wahl 5th-95th percentile** |
| **Output Statistics** | Single run | Single run | **Median, p05, p95** |
| **Number of Members** | 1 | 1 | **10-1000** |

---

## 4. Data Pipeline Comparison

### 4.1 DEM Acquisition

| Aspect | Traditional Tools | JalRaksha |
|:---|:---|:---|
| **Source** | Manual download | **Automated Copernicus GLO-30 (AWS S3)** |
| **Resolution** | 10-90 m (varies) | **30 m (consistent)** |
| **Coverage** | Regional | **Global** |
| **Authentication** | Often required | **None (public bucket)** |
| **Tile Fetch** | Full download | **Partial (/vsicurl range requests)** |
| **Caching** | Manual | **Automatic local cache** |
| **Reprojection** | Manual | **Automatic (UTM)** |
| **Resampling** | Manual | **Automatic (target resolution)** |

### 4.2 Input Parameter Sources

| Parameter | Traditional Tools | JalRaksha |
|:---|:---|:---|
| **Dam Location** | User types lat/lon | **Preset or lat/lon** |
| **Dam Height** | User researches | **Preset (vetted sources)** |
| **Storage** | User researches | **Preset (vetted sources)** |
| **Breach Parameters** | User guesses | **Auto-sampled from regressions** |
| **Roughness** | User assigns | **Auto from land cover** |
| **Domain Size** | User specifies | **Preset per dam** |

### 4.3 Output Product Comparison

| Product | Delft3D | HEC-RAS 2D | JalRaksha |
|:---|:---|:---|:---|
| **Depth Raster** | NetCDF | HDF5 | **GeoTIFF (COG)** |
| **Velocity Raster** | NetCDF | HDF5 | **GeoTIFF (COG)** |
| **Arrival Time** | Manual calc | Manual calc | **Auto-computed** |
| **Inundation Polygon** | Manual export | Manual export | **Auto Shapefile** |
| **KML Overlay** | No | No | **Yes** |
| **XDMF (ParaView)** | No | No | **Yes** |
| **Keyframe PNGs** | No | No | **Yes** |
| **Comparison Metrics** | No | No | **Yes (JSON)** |

---

## 5. Deployment & Accessibility Comparison

### 5.1 Installation & Setup

| Aspect | Delft3D | HEC-RAS 2D | DualSPHysics | JalRaksha |
|:---|:---|:---|:---|:---|
| **OS Support** | Windows, Linux | Windows only | Windows, Linux | **Windows, Linux** |
| **Installer** | MSI / manual | MSI | ZIP archive | **pip install** |
| **Dependencies** | Many (GDAL, NetCDF) | USACE framework | CUDA toolkit | **pip packages** |
| **Docker Support** | Complex | No | Complex | **Docker Compose** |
| **Cloud Deploy** | Difficult | No | GPU instances | **Any cloud** |
| **Setup Time** | Hours | Hours | Hours | **Minutes** |

### 5.2 User Interface

| Interface | Delft3D | HEC-RAS 2D | DualSPHysics | JalRaksha |
|:---|:---|:---|:---|:---|
| **Desktop GUI** | Yes (DeltaShell) | Yes (RAS Mapper) | Limited | No |
| **Web Dashboard** | No | No | No | **Yes (React)** |
| **CLI** | Limited | No | Script | **Full (jalraksha run)** |
| **REST API** | No | No | No | **Yes (FastAPI)** |
| **Background Jobs** | No | No | No | **Yes (Celery)** |
| **Mobile Friendly** | No | No | No | **Yes (responsive)** |

### 5.3 Offline & Field Use

| Capability | Traditional Tools | JalRaksha |
|:---|:---|:---|
| **Internet Required** | No (but data fetch needs it) | **No (fully offline after first fetch)** |
| **Data Caching** | Manual | **Automatic** |
| **Field Laptop** | Yes (if pre-installed) | **Yes (pre-baked runs)** |
| **Low Bandwidth** | N/A | **Yes (range requests)** |
| **No Login Required** | Yes | **Yes** |

---

## 6. Licensing & Cost Comparison

### 6.1 Software Licenses

| Tool | License | Commercial Use | Modification | Distribution |
|:---|:---|:---|:---|:---|
| **Delft3D** | AGPL-3.0 | Yes (copyleft) | Yes (must share) | Yes (must share) |
| **HEC-RAS** | Public Domain | Yes | Yes | Yes |
| **DualSPHysics** | LGPL-3.0 | Yes (copyleft) | Yes (must share) | Yes (must share) |
| **GeoClaw** | GPL-3.0 | Yes (copyleft) | Yes (must share) | Yes (must share) |
| **ANUGA** | GPL-3.0 | Yes (copyleft) | Yes (must share) | Yes (must share) |
| **JalRaksha** | **MIT / BSD** | **Yes (permissive)** | **Yes (no share)** | **Yes (no share)** |

### 6.2 Cost Breakdown

| Cost Component | Delft3D | HEC-RAS 2D | DualSPHysics | JalRaksha |
|:---|:---|:---|:---|:---|
| **Software License** | Free | Free | Free | **Free** |
| **Data (DEM)** | Free (manual) | Free (manual) | Free (manual) | **Free (automated)** |
| **Compute** | Workstation | Workstation | GPU workstation | **Any CPU** |
| **Training** | Days-weeks | Days-weeks | Weeks | **Hours** |
| **Maintenance** | Manual updates | Manual updates | Manual updates | **pip update** |

---

## 7. What Makes JalRaksha Different (Summary)

### 7.1 Key Differentiators

| # | Differentiator | Why It Matters |
|:---|:---|:---|
| 1 | **Domain Decomposition (3D+2D)** | Captures violent breach physics AND scales to 60+ km |
| 2 | **Automated Ensemble (100 members)** | Reports uncertainty bands, not single guess |
| 3 | **Open Data + Offline-First** | Works during disasters when internet fails |
| 4 | **Web Dashboard + 3D Globe** | Judges/stakeholders see results instantly |
| 5 | **Indian Dam Presets** | Ready for Tehri, Khadakwasla, Bhakra, etc. |
| 6 | **Real-Time Satellite Overlay** | GEE Sentinel-1 SAR for observed flood extent |
| 7 | **Impact Assessment** | Population, damage, fatalities — not just depth |
| 8 | **Permissive License (MIT/BSD)** | Government can adopt without legal friction |
| 9 | **Headless CLI + REST API** | Automatable, containerizable, cloud-ready |
| 10 | **Standard GIS Exports** | Direct .shp, .kml, .tiff — no conversion needed |

### 7.2 Problems JalRaksha Solves (That Others Don't)

| Problem | How Others Fail | How JalRaksha Solves |
|:---|:---|:---|
| **Breach uncertainty** | Single hydrograph guess | 100-member Monte Carlo with Wahl bands |
| **3D breach + 60 km range** | Choose one or the other | Domain decomposition (SPH → SWE) |
| **Offline disaster response** | Need internet for data | Cached DEM, pre-baked runs |
| **Stakeholder communication** | Desktop GUI only | Web dashboard with 2D+3D |
| **Indian-specific needs** | Generic global tools | Indian dam presets, open Indian data |
| **Rapid deployment** | Hours of setup | Minutes with `jalraksha run` |
| **Impact estimation** | Depth only | Population, damage, fatalities |

### 7.3 When to Use Which Tool

| Use Case | Recommended Tool | Why |
|:---|:---|:---|
| **Detailed engineering study** | Delft3D | Validated, regulatory acceptance |
| **US regulatory compliance** | HEC-RAS 2D | USACE standard |
| **Research on breach physics** | DualSPHysics | Full 3D resolution |
| **Mountain flood routing** | GeoClaw | Well-balanced for steep terrain |
| **Rapid emergency screening** | **JalRaksha** | Fast, automated, offline |
| **Evacuation planning** | **JalRaksha** | Arrival times with uncertainty |
| **Stakeholder presentation** | **JalRaksha** | Web dashboard, 3D globe |
| **Indian dam assessment** | **JalRaksha** | Presets, open data, offline |

---

## 8. Technology Stack Comparison

### 8.1 JalRaksha Stack vs Traditional Tools

| Layer | Traditional Tools | JalRaksha |
|:---|:---|:---|
| **Language** | Fortran, C++, C | **Python** |
| **Numerics** | Compiled libraries | **NumPy, SciPy, Numba** |
| **GIS** | GDAL (C++), ArcGIS | **Rasterio, GeoPandas, Shapely** |
| **Web Framework** | None | **FastAPI, React, Vite** |
| **Database** | None, Flat files | **SQLite / Postgres** |
| **Task Queue** | None | **Celery + Redis** |
| **Visualization** | Desktop GUI, ParaView | **Leaflet, Cesium, Matplotlib** |
| **Deployment** | Manual install | **Docker Compose** |
| **Testing** | Limited | **pytest (comprehensive)** |

### 8.2 JalRaksha Dependencies

| Package | Purpose | License |
|:---|:---|:---|
| NumPy | Array numerics | BSD |
| SciPy | Scientific computing | BSD |
| Numba | JIT compilation | BSD |
| Rasterio | GeoTIFF I/O | BSD |
| GeoPandas | Vector GIS | BSD |
| Shapely | Geometry | BSD |
| PyProj | Coordinate transforms | MIT |
| FastAPI | REST API | MIT |
| Celery | Task queue | BSD |
| React | Frontend | MIT |
| Leaflet | 2D map | BSD |
| Cesium | 3D globe | Apache 2.0 |
| PySPH | SPH solver | BSD |
| pytest | Testing | MIT |

---

## 9. Conclusion

JalRaksha is not a replacement for Delft3D or HEC-RAS — it is a **Tier-1 screening tool** designed for rapid emergency response. It trades the detailed engineering accuracy of Delft3D for:

1. **Speed** (minutes vs hours)
2. **Automation** (no manual mesh generation)
3. **Uncertainty quantification** (100-member ensembles)
4. **Accessibility** (web dashboard, CLI, API)
5. **Offline resilience** (cached data, pre-baked runs)
6. **Indian-specific presets** (Tehri, Khadakwasla)

For detailed engineering studies, use Delft3D. For rapid emergency screening, use JalRaksha.

---

*Document generated: 2026-08-30*  
*Project: JalRaksha — Smart India Hackathon 2026*
