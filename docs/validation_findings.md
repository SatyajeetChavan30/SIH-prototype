# Validation findings

Measured results, each reproducible by the command given. Anything that was
**not** verified says so. Numbers here are copied from actual command output,
not from expectations.

Machine: Windows 11, Python 3.14. Delft3D FM Suite 2026.01 HM,
dimrset build 2025-10-20, `dflowfm-cli.exe` 1.2.184.

---

## 1. JalRaksha vs Delft3D FM vs Ritter — the validation case

```bash
python scripts/validate_against_delft3d.py --case ritter
```

Ritter (1892) dry-bed dam-break: flat frictionless bed, instantaneous barrier
removal, h₀ = 10 m, t = 40 s, Δx = 10 m, 4 km channel. The exact solution is
known, so both engines are scored against **theory** rather than against each
other.

| | RMSE vs exact | max abs error | depth at dam |
| :--- | ---: | ---: | ---: |
| JalRaksha 2D SWE | **0.0317 m** | 0.2644 m | 4.532 m |
| Delft3D FM | **0.0349 m** | 0.2265 m | 4.515 m |
| exact (4h₀/9) | — | — | **4.444 m** |

Engine-vs-engine agreement: **0.0294 m RMSE**. Both land within ~0.3% of theory
on a 10 m dam-break, and within 3 cm of each other.

Figure: `data/validation/ritter_validation.png`.

### The boundary artifact, and why the first numbers were wrong

The first run scored JalRaksha at 0.0445 m and Delft3D at 0.0897 m — Delft3D
apparently twice as bad. It was an artifact. The **outermost cell** of the
closed D-Flow FM domain accumulates water: 1.06 m on a 2000 m domain, still
0.41 m at 4000 m, while its immediate neighbours sat at 0.001–0.03 m. A genuine
boundary reflection would grow as the domain shortens and spread over many
cells; this did neither.

Boundary cells are not part of the interior solution in any finite-volume
scheme, so three cells are now trimmed from each end before scoring
(`BOUNDARY_MARGIN_CELLS`). The excluded strips are **shaded on the figure** so
the reader can see what was and was not counted. With them included, the
comparison would have read "Delft3D is worse" when the real cause was the
domain edge.

---

## 2. Sentinel-1 SAR water extent — works on plains, not in gorges

```bash
python -m pytest tests/test_gee.py -q     # with JALRAKSHA_GEE_PROJECT set
```

Water mask from VV backscatter, thresholded per scene by a split-based Otsu
method, then **measured against JRC Global Surface Water** (Pekel et al. 2016)
before publication.

| Reach | Terrain | Recall | **Precision** | Outcome |
| :--- | :--- | ---: | ---: | :--- |
| Hirakud (Mahanadi) | flat plain | 0.557 | **0.768** | mask published |
| Tehri (Bhagirathi) | steep gorge | 0.945 | **0.010** | **refused** |

Over Tehri, 99% of what VV thresholding calls water is radar shadow on
hillsides. Whole-scene Otsu classified **45% of a mountain valley** as water and
produced a mask that looked entirely credible. The VV histogram there is
*unimodal* — one land mode near −10 dB with a shadow tail — so Otsu bisected the
land distribution rather than separating water.

JRC-known permanent water in that window is **0.57%** of the scene, and VV over
it has median −23.1 dB. No threshold reached precision above 0.08. Slope
masking (water is horizontal) lifted it only 0.076 → 0.099.

**This is a property of the physics, not a defect to tune away.** Terrain-
corrected local-incidence-angle masking (Small 2011) is the documented fix and
is *not implemented*. The module refuses below 0.5 precision and reports the
measured numbers.

---

## 3. Near-field SPH — hydrostatic convergence

PySPH 1.0b2 WCSPH, Wendland quintic kernel. Still water in a closed tank must
stay still, and pressure must follow ρg·h.

| | dp/d(depth) error vs ρg | max residual speed |
| :--- | ---: | ---: |
| uniform initial density | 28.9% | 0.236 m/s |
| + hydrostatic initial density | 8.8% | 0.236 m/s |
| + `n_damp=50`, t = 4 s | **3.2%** | **0.166 m/s** |

Initialising every particle at uniform ρ₀ starts the column at zero pressure, so
it must compress under its own weight before it can support itself. Inverting
the Tait equation for the hydrostatic pressure removes that transient.

At low resolution the pressure gradient is **not measurable** — the interior
band collapses to about one particle layer and the fit returned 27% and 123% for
the same physics at two run lengths. It now reports `None` with a reason rather
than a number.

Determinism, on real terrain:

| Change | Particle field |
| :--- | :--- |
| RNG seed 1 → 999, same dam and terrain | **identical** |
| Tehri 120 m → 200 m head | different (446 → 513 particles) |
| Tehri → Khadakwasla terrain | different (446 → 573 particles) |

---

## 4. Population at risk — real GHSL

GHSL P2023A epoch 2020, resampled onto the solver grid **by sum** (counts are
extensive; a mean would divide the population by the cell-count ratio — a
sixteen-fold undercount at 400 m over a 100 m source).

Tehri domain, 400 m resolution, 90 min simulated:

| Dam height | Domain population | Flooded cells | **Population at risk** |
| ---: | ---: | ---: | ---: |
| 260 m | 295,025 | 222 | **220** |
| 120 m | 295,025 | 256 | **322** |

The lower head drains the same storage more slowly and spreads further into
populated valley floor — hence more wetted cells and a higher figure.

Per-gauge PAR is deliberately **null**: splitting a domain figure across gauges
needs a catchment radius per gauge that no source defines.

---

## Not verified

- **The Tehri Delft3D comparison does not run.** `compare_tehri` is implemented
  and both engines execute, but the initial condition is wrong: the reservoir is
  seeded from an **axis-aligned dam row**, and a straight line across a winding
  Himalayan valley is a poor stand-in for a dam wall. Successive attempts put
  Koteshwar (13 km *downstream*, but south of the line) inside the reservoir so
  it started wet; correcting the fill to a hydraulically connected impoundment
  then found no connected volume at all. The case now **refuses with that
  reason** rather than comparing two models of still water. Locating the barrier
  along the real impoundment is the fix and is not implemented.
- **Delft3D FM's numerical output beyond Ritter.** Only the Ritter case has been
  scored. Malpasset and Chamoli remain unrun.
- **The SPH near-field is not validated against a published experiment.**
  `ALPHA_VISCOSITY = 0.25` carries a `TODO: UNVETTED`.
- **No screenshot of the dashboard.** The Browser pane was not displayed during
  this work, so UI claims come from page text, DOM inspection and server-side
  renders rather than from looking at pixels.
