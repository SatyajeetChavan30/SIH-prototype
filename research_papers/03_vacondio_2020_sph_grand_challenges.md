# Grand Challenges for Smoothed Particle Hydrodynamics Numerical Schemes

**Authors**: Renato Vacondio, Corrado Altomare, Matthieu De Leffe, Xiangyu Hu, David Le Touzé, Steven Lind, Jean-Christophe Marongiu, Salvatore Marrone, Benedict D. Rogers, & Antonio Souto-Iglesias  
**Journal**: *Computational Particle Mechanics*, 8, 575–588  
**Year**: 2021 (Published online 2020)  
**DOI**: [10.1007/s40571-020-00354-1](https://doi.org/10.1007/s40571-020-00354-1)  

---

## 📌 Abstract & Overview

This paper, authored by leading researchers in the international SPHERIC (SPH European Research Interest Community) steering committee, outlines the fundamental unresolved computational and numerical challenges facing Smoothed Particle Hydrodynamics (SPH).

The five grand challenges identified are:
1. Convergence, consistency, and stability
2. Boundary conditions
3. Adaptive spatial and temporal resolution
4. High-performance computing and GPU scaling
5. Multi-physics and fluid-structure interaction (FSI)

---

## 🔑 Key Findings & Relevance to JalRaksha

1. **SPHERIC Grand Challenge 3 (Adaptive Resolution)**:
   - SPH in production is fundamentally a uniform particle resolution method. The spatial resolution (particle spacing) required to resolve a breach opening (e.g. 20 m) must be maintained across the entire computational domain.
   - Extending SPH across an entire 60 km river valley is computationally infeasible and requires active research solutions not yet ready for production industrial screening.

2. **Defending Domain Decomposition**:
   - Provides explicit academic literature backing when asked: *"Why not use 3D SPH for the entire river basin?"*
   - Answer: SPHERIC's own consensus paper explicitly lists full-domain far-field SPH resolution as an open research challenge. JalRaksha's coupling of SPH (near-field) with 2D SWE (far-field) aligns directly with SPH community recommendations.

---

## 📑 Citation

```bibtex
@article{vacondio2021grand,
  title={Grand challenges for Smoothed Particle Hydrodynamics numerical schemes},
  author={Vacondio, Renato and Altomare, Corrado and De Leffe, Matthieu and Hu, Xiangyu and Le Touz{\'e}, David and Lind, Steven and Marongiu, Jean-Christophe and Marrone, Salvatore and Rogers, Benedict D and Souto-Iglesias, Antonio},
  journal={Computational Particle Mechanics},
  volume={8},
  number={3},
  pages={575--588},
  year={2021},
  publisher={Springer}
}
```
