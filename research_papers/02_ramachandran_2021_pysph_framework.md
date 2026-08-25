# PySPH: A Python-based Framework for Smoothed Particle Hydrodynamics

**Authors**: Prabhu Ramachandran, Aditya Bhosale, Kunal Puri, Pankaj Negi, Ananya Muta, Abhinav Dinesh, Deep Menon, Rahul Govind, Suraj Sanka, Abishek S. Sebastian, Arpit Sen, Rishabh Kaushik, Ankit Kumar, Varun Kurapati, M. Deepak, Pratik Patil, Divyaprakash Tavker, Pawan Pandey, Chandrashekhar Kaushik, Anubhav Dutt, & Abhishek Agarwal  
**Institution**: Indian Institute of Technology Bombay (IIT Bombay)  
**Journal**: *ACM Transactions on Mathematical Software*, 47(4), Article 34  
**Year**: 2021  
**DOI**: [10.1145/3460773](https://doi.org/10.1145/3460773)  
**Licence**: BSD 3-Clause License (Permissive)  

---

## 📌 Abstract & Overview

PySPH is an open-source, high-performance, Python-based framework for Smoothed Particle Hydrodynamics (SPH). It allows users to write pure Python code for SPH algorithms while automatically compiling high-performance C/C++ code under the hood via Cython and OpenMP parallelization. PySPH supports weakly compressible SPH (WCSPH), incompressible SPH (ISPH), transport-velocity formulations, and shallow water SPH formulations.

---

## 🔑 Key Features & Relevance to JalRaksha

1. **De-Risking Near-Field 3D SPH**:
   - **BSD License**: Pure permissive open-source license, allowing complete integration without share-alike GPL restrictions (unlike DualSPHysics or GPUSPH).
   - **Pure Python Integration**: Installed via `pip install pysph`. No manual C++/Fortran compilation step required.
   - **Indian National Hackathon Relevance**: Designed and maintained by IIT Bombay, making it a strong asset for SIH 2026.

2. **Built-in Dam-Break Benchmarks**:
   - Includes standard 2D and 3D dam-break benchmark scripts (`dam_break_2d.py`, `dam_break_3d.py`) and experimental validation datasets (Lobovsky, Buchner, Yeh).
   - Includes a specialized shallow water SPH module (`pysph.sph.swe`) for cross-verification.

3. **Role in JalRaksha**:
   - Serves as the near-field 3D solver engine for Phase 7 (3D near-field breach simulation).

---

## 📑 Citation

```bibtex
@article{ramachandran2021pysph,
  title={PySPH: A Python-based framework for smoothed particle hydrodynamics},
  author={Ramachandran, Prabhu and Bhosale, Aditya and Puri, Kunal and Negi, Pankaj and Muta, Ananya and Dinesh, Abhinav and Menon, Deep and Govind, Rahul and Sanka, Suraj and Sebastian, Abishek S and others},
  journal={ACM Transactions on Mathematical Software (TOMS)},
  volume={47},
  number={4},
  pages={1--38},
  year={2021},
  publisher={ACM New York, NY, USA}
}
```
