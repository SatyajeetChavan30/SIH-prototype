# Delft3D-FLOW: Functional Specifications & Technical Reference Manual

**Author**: Deltares  
**Institution**: Deltares, Delft, The Netherlands  
**Year**: 2014  
**Licence**: Mixed Open-Source (AGPL-3.0 / GPL-3.0 / LGPL-2.1)  
**Repository**: [github.com/Deltares/Delft3D](https://github.com/Deltares/Delft3D)  

---

## 📌 Abstract & Overview

Delft3D-FLOW is a 2D/3D hydrodynamic simulation program for coastal, river, and estuarine environments. It solves the unsteady 2D (depth-averaged) or 3D shallow water equations on a structured curvilinear or spherical grid using an Alternating Direction Implicit (ADI) time integration scheme.

---

## 🔑 Technical Comparison & Role in JalRaksha

1. **Problem Statement Context**:
   - Problem Statement 26161 specifically requests comparison against "Delf3D" (Delft3D).
   - Python pre/post-processing wrappers exist (`hydromt`, `hydrolib-core`, `dfm_tools`), but the computational kernel is compiled Fortran/C++.

2. **Honest Framing Standard**:
   - **Delft3D-Class Positioning**: JalRaksha's far-field 2D SWE solver solves the exact same depth-averaged Saint-Venant governing equations as Delft3D-FLOW, but uses an explicit finite-volume HLLC Riemann scheme with Audusse hydrostatic reconstruction rather than Delft3D's ADI finite-difference scheme.
   - JalRaksha explicitly presents itself as a **"Delft3D-class shallow water solver"** without overclaiming identity with the compiled Deltares Fortran binary.

---

## 📑 Citation

```bibtex
@manual{deltares2014delft3d,
  title={Delft3D-FLOW: User Manual / Technical Reference},
  author={{Deltares}},
  year={2014},
  organization={Deltares},
  address={Delft, The Netherlands}
}
```
