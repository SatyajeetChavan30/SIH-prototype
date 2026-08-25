# A Fast and Stable Well-Balanced Scheme with Hydrostatic Reconstruction for Shallow Water Flows

**Authors**: Emmanuel Audusse, François Bouchut, Marie-Odile Bristeau, Robert Klein, & Benoît Perthame  
**Journal**: *SIAM Journal on Scientific Computing*, 25(6), 2050–2065  
**Year**: 2004  
**DOI**: [10.1137/S1064827503423018](https://doi.org/10.1137/S1064827503423018)  

---

## 📌 Abstract & Overview

Finite volume schemes for shallow water equations with non-flat topography often suffer from unphysical artificial velocities near dry sloping beds or over complex bathymetry. The standard discrete pressure gradient evaluation does not balance the bed slope source term exactly at rest.

Audusse et al. introduce the **Hydrostatic Reconstruction Method**, a modified spatial reconstruction technique where left and right cell interface depths ($h_i^{L}, h_i^{R}$) are reconstructed based on the local water surface elevation $H = h + z$ and local bed elevation $z$. This guarantees that the hydrostatic pressure flux exactly balances the bed slope term, preserving the **lake-at-rest C-property** to machine precision:
$$u = 0, \quad v = 0, \quad h + z = \text{constant}$$

---

## 🔑 Key Features & Role in JalRaksha

1. **Lake-At-Rest Hydrostatic Balance**:
   - Ensures that stationary water over complex mountain terrain (e.g. Tehri reservoir bathymetry) does not generate unphysical fluid motion or artificial velocities.
   - Prevents numerical instabilities at wet-dry fronts along reservoir shorelines.

2. **Implementation in Solver**:
   - Implemented in `jalraksha/solver/core.py` and `jalraksha/solver/flux.py`.
   - Directly tested by `tests/test_solver.py::TestLakeAtRest`.

---

## 📑 Citation

```bibtex
@article{audusse2004fast,
  title={A fast and stable well-balanced scheme with hydrostatic reconstruction for shallow water flows},
  author={Audusse, Emmanuel and Bouchut, Fran{\c{c}}ois and Bristeau, Marie-Odile and Klein, Robert and Perthame, Beno{\^\i}t},
  journal={SIAM Journal on Scientific Computing},
  volume={25},
  number={6},
  pages={2050--2065},
  year={2004},
  publisher={SIAM}
}
```
