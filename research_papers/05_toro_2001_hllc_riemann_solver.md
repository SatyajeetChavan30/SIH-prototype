# Shock-Capturing Methods for Free-Surface Shallow Flows

**Author**: Eleuterio F. Toro  
**Publisher**: John Wiley & Sons, Ltd.  
**Year**: 2001  
**ISBN**: 978-0-471-98766-6  

---

## 📌 Abstract & Overview

This foundational monograph details finite-volume shock-capturing methods for free-surface hydrodynamics governed by the 2D Shallow Water Equations (SWE). 

It presents the formulation of the **HLLC (Harten-Lax-van Leer-Contact) Riemann Solver**, which restores the contact wave structure missing from the standard HLL solver. In 2D shallow water flow, HLLC accurately tracks shear waves and transverse momentum jump conditions across steep wet/dry fronts and dam-break shock waves.

---

## 🔑 Key Equations & Role in JalRaksha

1. **HLLC Numerical Flux Formulation**:
   - Computes inter-cell numerical fluxes $\mathbf{F}_{i+1/2}$ using estimated wave speeds $S_L, S^*, S_R$:
   $$\mathbf{F}^{\text{HLLC}} = \begin{cases} \mathbf{F}_L & \text{if } S_L \ge 0 \\ \mathbf{F}_{*L} & \text{if } S_L \le 0 \le S^* \\ \mathbf{F}_{*R} & \text{if } S^* \le 0 \le S_R \\ \mathbf{F}_R & \text{if } S_R \le 0 \end{cases}$$
   - Includes transverse velocity update in the intermediate state $\mathbf{F}_{*L}, \mathbf{F}_{*R}$.

2. **Role in JalRaksha**:
   - Implemented in `jalraksha/solver/flux.py` with Numba JIT acceleration (`@njit`).
   - Validated against 1D Ritter dry-bed and 1D Stoker wet-bed dam-break analytical solutions.

---

## 📑 Citation

```bibtex
@book{toro2001shock,
  title={Shock-capturing methods for free-surface shallow flows},
  author={Toro, Eleuterio F},
  year={2001},
  publisher={John Wiley \& Sons}
}
```
