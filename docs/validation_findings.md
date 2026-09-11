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

## 5. Hypsometric lake volume — scored against a closed form

```bash
python -m pytest tests/test_blockage.py -q
```

A landslide dam's impounded volume is measured, not published, so the measuring
code needs a known answer to be scored against. A V-valley with a constant
longitudinal slope has one: filled to depth `H`, its capacity is

```
V = H³ / (3 · m · S)          m = cross slope, S = channel gradient
```

Cell-centred fill against that exact capacity, integrated over the same reach
(the deposit occupies channel volume, so the analytic integral starts at the
same place rather than building a tolerance around a known offset):

| cell size | modelled | exact | error |
| ---: | ---: | ---: | ---: |
| 60 m | 6.7083e+07 m³ | 6.6734e+07 m³ | **0.523%** |
| 30 m | 6.9422e+07 m³ | 6.9334e+07 m³ | **0.127%** |
| 15 m | 7.0680e+07 m³ | 7.0658e+07 m³ | **0.031%** |

Roughly a factor of four per halving — second order, which is what a
cell-centred sum over a smooth cross-section should give. A first-order trend
would mean the fill is losing a boundary row. The fitted storage exponent
recovers the prism's cubic capacity at **b = 3.07** (exact 3) with a log10 RMS
residual of 0.011.

At the 100–200 m the dashboard runs, this discretisation is far smaller than
GLO-30's own vertical error over Himalayan terrain.

### Scale sanity on real terrain

Dhauliganga gorge below Tapovan, 1,704 m bed, 1,200 m of cross-valley relief:

| crest | 55 m | 90 m | 120 m | 150 m |
| :--- | ---: | ---: | ---: | ---: |
| lake volume | 0.6 MCM | 6.3 MCM | 26.0 MCM | 60.8 MCM |
| deposit volume | 3.4e6 m³ | 7.9e6 m³ | 1.3e7 m³ | 1.9e7 m³ |

Every deposit volume falls inside the 10⁶–10⁸ m³ range Costa & Schuster (1988)
report for surveyed natural dams, and none of the four leaked or spilled. The
storage exponent on this reach fits **b ≈ 6.3** with a log10 residual of 0.19 —
a steep narrow gorge is emphatically not the cubic prism above, and that
residual is why the curve is reported alongside the fit rather than instead of it.

A 55 m barrier here produces a local surge reaching no gauge within an hour.
That is the honest answer for a deposit that size on a reach that steep, not a
broken run.

---

## 6. New-water detection over the Rishi Ganga — a measured refusal

```bash
curl "http://localhost:8000/gee/blockage?reach=rishi_ganga"
```

The detector differences a Sentinel-1 pre-event median against a single
post-event scene and checks the **pre-event** mask against JRC Global Surface
Water. (Checking the *difference* against permanent water would reject every
true positive: a lake that formed last week is definitionally absent from a
32-year product.)

Over the Raini window it refuses, and the reason is a measurement. JRC
permanent water, occurrence > 80%, as a fraction of a 0.2° window:

| reach | JRC permanent water | verdict |
| :--- | ---: | :--- |
| Rishi Ganga (Raini) | **0.001%** | no usable reference — refuse |
| Tehri (Bhagirathi) | 0.572% | reference exists; fails on precision (0.010) |
| Hirakud (Mahanadi) | 44.520% | passes (precision 0.77) |

0.001% of that window is about **one cell at 60 m**. JRC comes from 30 m
Landsat and its permanent-water band does not resolve a narrow braided
Himalayan headwater, so there is nothing to verify a same-day radar mask
against. An unverifiable mask is not a verified mask.

This is a documented limit of open-data change detection over exactly the
terrain PS-26161 names first. `MIN_JRC_PRECISION` was **not** widened to make it
pass. The manual barrier path runs fully offline and carries the demo.

> **Superseded in part by section 9.** The refusal is real, but "no usable
> reference" is not the whole reason. Section 9 runs the same detector against
> the Baige barrier lakes on the Jinsha River — a wide channel where JRC *does*
> map the river, with the lake optically confirmed — and it refuses there too,
> because the pre-event mask classifies **63% of the gorge as water**. The
> limiting defect is VV thresholding against radar shadow, not the reference.

---

## 7. Delta-add DEM write — bit-identical outside the footprint

```bash
python -m pytest tests/test_dem_update.py -q
```

Only the elevation **change** is reprojected back onto the source raster, with
nearest-neighbour resampling. Every pixel outside the barrier footprint compares
bit-identical to the Copernicus source, asserted directly rather than to a
tolerance.

A bilinear round trip through UTM would fail this on every pixel in the raster
while looking entirely correct in a viewer — the same effect
`load_dem_as_grid`'s own smoothing table measures at tens of metres of
valley-floor error.

Also asserted at the **file** level, because a correct dict inside a process
nobody is running is not a label: every written GeoTIFF carries
`JALRAKSHA_NOT_A_SURVEY`, and an operator-placed barrier never carries a
satellite scene id.

---

## 8. The Khadakwasla drainage plateau — measured, diagnosed, and drained

*Read to the end before quoting anything from this section.* The first three
subsections record a plateau and three mechanism fixes that did not clear it; the
last three record what actually did, and supersede the intermediate "not
resolved" verdict.

> **EVERY HAZARD CLASS COUNT BELOW PREDATES THE FD2320 UNIFICATION (§10) AND IS
> NOT REPRODUCIBLE BY A NEW RUN.** They were produced by a discrete
> depth-window/velocity-ceiling table that has since been replaced by the
> published hazard rating `HR = d(|V| + 0.5) + DF`, and the `severe` class they
> report no longer exists — FD2320 has four wet categories, not five. Nothing
> about the hydraulics changed, so the volume balance, the arrival times, the
> wet-cell counts, the recession SHAPE and every conclusion drawn from them
> stand exactly as written. Do not compare a new run's per-class counts against
> the tables in this section cell for cell; compare wet extent and
> `exited_mcm`. These runs are not retroactively reclassified, following the
> same precedent as the pre-fix population-at-risk figures.

```bash
python -m pytest tests/test_terrain.py -q -k "fill_depressions or notch_breach"
```

A 24 h Khadakwasla run on the 27 km dam-centred domain **never receded**. The
hazard classification rose to a peak at t ~ 17,876 s and then held flat: **46
cells stayed SEVERE for the last 7.5 simulated hours**, with roughly **42% of the
released volume permanently trapped**. Both a 10-member and a 100-member baseline
peaked at the same time, which ruled out the ensemble as the cause.

The diagnosis is that none of it was hydraulics. Three modelling artefacts each
created water with nowhere to go:

1. **The dam ridge was never breached in the terrain.** `inject_breach_hydrograph`
   adds depth at a single cell each timestep — a source term carrying no momentum
   direction — on a bed where the intact crest is still standing. Water spilling
   downstream left easily; water spreading back toward the reservoir landed in a
   genuine closed basin, bounded by valley walls on three sides and the unbreached
   crest on the fourth, and stayed there because the domain starts dry and nothing
   removes it.
2. **Bilinear downsampling manufactures pits.** Averaging a narrow channel onto a
   coarse grid blends the bed with its banks, producing local minima that exist
   only in the resampled raster. The solver's own flood water pools in them
   permanently — the artifact class CLAUDE.md warns about, observed doing exactly
   what it warns of.
3. **The domain was too small to drain into.** A 54 x 54 km box centred on the dam
   spends half its cells on the Western Ghats and the Arabian Sea while the flood
   runs east down the Mutha to the Mula-Mutha and the Bhima.

The fixes are `run.py::_notch_breach_into_bed` (`notch_breach`, default `True`),
`terrain/conditioning.py::fill_depressions` (`fill_max_depth_m`, default `3.0`),
and `load_dem_as_grid(margins_km=...)` exposed as `RunRequest.domain_margins_km`.

Two properties are asserted rather than assumed, because both fixes could
otherwise hide the defect instead of removing it:

- **The notch cannot invent terrain.** The invert is clamped never to fall below
  the lowest bed already present just outside the notch footprint, so it can only
  open a path to terrain that exists — never dig a new pit deeper than the
  surrounding channel.
- **The fill preserves real basins.** It computes the full hydrological fill, then
  caps the raise applied per cell. Shallow resampling noise fills completely; a
  reservoir bowl or lake keeps standing at very nearly its original depth. The
  unrestricted variant, which does remove every local minimum, is tested
  separately so the difference between the two is explicit.

### The confirmation run — measured 2026-09-04, and the plateau SURVIVES

```bash
python scripts/run_khadakwasla_drainage_check.py --resolution 500 --duration-h 24 --members 4 --snapshots 60
```

240 x 188 km east-biased domain, **500 m**, 24 h, 4 members, all three fixes on.
64 min wall clock on 16 cores. Series:
`data/keyframes/khadakwasla_drainage_check/hazard_series.json`.

| t (h) | wet cells | low | mod | sig | severe | extreme | wet severity |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.6 | 29 | 1 | 6 | 5 | 7 | 10 | 0.690 |
| 3.3 | 66 | 6 | 9 | 19 | 20 | 12 | 0.618 |
| 4.9 | 89 | 5 | 28 | 27 | 29 | 0 | 0.512 |
| 8.1 | 99 | 12 | 21 | 42 | 24 | 0 | 0.482 |
| 13.0 | 101 | 15 | 20 | 39 | 27 | 0 | 0.481 |
| 17.9 | 96 | 9 | 21 | 39 | 27 | 0 | 0.503 |
| 24.0 | 93 | 6 | 21 | 39 | 26 | 1 | 0.518 |

**It does not recede.** Wet extent peaks at 104 cells at t = 8.5 h; SEVERE holds
between 23 and 27 from t = 4.9 h to the 24 h cutoff — flat for **19 simulated
hours** — and wet-cell severity flattens at ~0.48-0.52. Neither threshold is
ever crossed: `safe_at_s` (SEVERE and EXTREME both zero) and `fully_green_at_s`
(nothing above LOW) are both **null**. The fixes did not close the plateau.

Cell counts are **not** comparable to the pre-fix baseline quoted above: that
run used a different resolution, so a cell is a different area. Do not read
46 → 26 SEVERE as an improvement.

**The volume balance is new, and it says the water never got the chance to
leave.** Median across 4 members: **85.276 MCM released, 0.000 MCM exited,
85.276 MCM retained**, closing to 0.000%. That is *not* the 42%-trapped failure
repeating. The nearest domain edge is 40 km west and the outlet edge 200 km
east, while the flood reached only **25 km** downstream — so no water could have
exited, and 100% retained is arithmetic, not pathology. The east-biased domain
did its job of removing the boundary as a confound; it also means boundary
outflow tells us nothing on this run.

**Where the water actually went.** From the exported `h_max_median_cog.tif`:
138 wet cells spanning **24.5 km E-W by 15.0 km N-S**, mean distance from the
dam 13.3 km, only 28 cells within 5 km of it. So the flood *did* route east down
the Mutha as intended — it is not ponded at the breach — and then stalled as a
~25 km standing pool, mean h_max 4.51 m, peak 11.87 m.

### Resolution was suspected and is RULED OUT — the 300 m run, 2026-09-04

```bash
python scripts/run_khadakwasla_drainage_check.py --resolution 300 --duration-h 24 --members 4 --snapshots 60 --tag khadakwasla_drainage_300m
```

The obvious objection to the 500 m run was the grid. That resolution was chosen
to buy a faster first look, and the Mutha is 50–100 m wide, so a cell averages
the channel with its banks and leaves no thalweg to convey water — defect (2)
above, *made worse* rather than tested. The objection was itself testable, so it
was tested: the identical run at **300 m** (180,480 → 501,600 cells, 5 h 1 min
wall clock on 16 cores). Series:
`data/keyframes/khadakwasla_drainage_300m/hazard_series.json`.

**It plateaus the same way.** Wet extent peaks at 238 cells at t = 8.54 h — the
500 m run peaked at **the same 8.54 h** — and severe+extreme settles at 73–77
cells from t = 12 h to the cutoff, with wet-cell severity flat at 0.535–0.553
across the final 16 hours. `safe_at_s` and `fully_green_at_s` are both null
again.

Compared on AREA rather than cell counts, which is the only valid comparison
across resolutions:

| | wet area | severe+extreme | wet severity | max reach | E–W span |
| :--- | ---: | ---: | ---: | ---: | ---: |
| 500 m | 23.25 km² | 6.75 km² | 0.518 | 25.2 km | 24.5 km |
| 300 m | 20.43 km² | 6.57 km² | 0.551 | 25.6 km | 24.6 km |

Within ~12% on wet area, ~3% on severe area, and the flood halts at the **same
place** with the same timing. Refining the grid by 1.7× in each direction
changes nothing that matters. **The plateau is not a discretisation artefact**,
and the confound raised against the 500 m run does not survive the measurement.
The volume balance is unchanged in character: 85.309 MCM released, 0.000 exited,
100% retained, closing to 0.000%, for the same reason as before — the flood
never approaches a boundary.

### What is now excluded, and what is not

Excluded by measurement:

- **The domain boundary.** The flood reaches 25 km; the nearest edge is 40 km.
- **Ponding at the breach.** Only 28 of 138 wet cells (500 m) lie within 5 km of
  the dam; the flood routes east down the Mutha as intended.
- **Grid resolution.** 500 m and 300 m agree on extent, timing and severity.
- **The ensemble.** Four members here; the pre-fix baseline plateaued
  identically at 10 and 100 members.

**Was not resolved at the time of writing:** whether the residual standing water
is genuine slow drainage of a flat floodplain — 85 MCM over ~20 km² of the Mutha
corridor is ~4 m mean depth, and after the reservoir empties at 2.88 h no further
inflow drives it out, so a multi-day recession would be physically unremarkable —
or whether depressions survive `fill_max_depth_m = 3.0` and still trap it.

**That fork is now closed. It is neither, exactly: no water could leave the
domain at all.** See the next two subsections, which supersede this paragraph.

**The honest statement, as of the 300 m run:** the three fixes are implemented
and unit-tested; the hazard does not recede to green within 24 h at either
resolution; and the cause is no longer attributable to any of the four mechanisms
listed above.

### The plateau is VOLUME-limited, not domain-limited — measured 2026-09-06

The measurement that resolves §8 is one field, and it was not being read:
`volume_balance.exited_mcm`. Read from
`data/keyframes/<run_id>/hazard_series.json`:

| run id | tag | domain (km) | Δx | duration | members | wall clock | final low/mod/sig/sev/ext | wet severity | `exited_mcm` | `retained_fraction` |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | :--- | ---: | ---: | ---: |
| `48f7ac59fbb4497f86f5c455cf4bcf13` | `khadakwasla_drainage_check` | full 40/200/94/94 | 500 m | 24 h | 4 | 3,866.5 s | 6/21/39/26/1 | 0.51828 | −8.50e−14 | 0.99999996 |
| `1d3d3c45571242dfbeedfc991cae87cb` | `khadakwasla_drainage_300m` | full 40/200/94/94 | 300 m | 24 h | 4 | 18,046.7 s | 11/45/98/58/15 | 0.550661 | −4.45e−13 | 0.99999994 |
| `e5485691b5264a468de81f549c1f221d` | `pilot_48h` | mid 12/105/45/45 | 500 m | 48 h | 2 | 826.5 s | 62/21/39/25/1 | 0.358108 | +2.66e−13 | 0.99999992 |

`safe_at_s` and `fully_green_at_s` are **null in all three**. `exited_mcm` is
zero to within float noise in all three, and the sign flips between runs because
these are cancellation residuals, not outflow.

**No water ever left the domain, so none of these runs tested drainage.** The
transmissive boundary is the model's only exit: there is no infiltration, no
evaporation and no seepage sink anywhere in the solver, and `flux.py` zeroes
velocity below `H_DRY_DEFAULT` while **leaving depth in place**. Water that
reaches a closed basin cannot leave it at any duration.

The front is volume-limited. 85.3 MCM fills the reachable channel to roughly
2.7 m mean depth and stops: wet cells end at **east 23.5 km / north 15 km** in
all three `h_max` rasters, against a nearest boundary 40 km away. Supporting
counts from run `0e78feac`: only **2 of 621 wet cells** touch the domain edge,
and **93.2% of flood volume** sits in depressions the conditioning refuses to
fill (5,075 surviving pits, mean 16.5 m deep). Adding runway therefore cannot
help, which is exactly why the 240 × 188 km domain and the 300 m grid both
changed nothing.

### Moving the boundary inside the front — the flood drains, 2026-09-06

```bash
python scripts/run_khadakwasla_drainage_check.py --domain exit --resolution 200 \
    --duration-h 30 --members 6 --solver both --condition-corridor 10 \
    --tag khadakwasla_drain_to_green
```

`DOMAINS["exit"]` is 8/20/8/18 km — a 28 × 26 km box, 140 × 130 = 18,200 cells —
whose east edge sits **3.5 km inside** the measured 23.5 km front. Run
`e2e09ea3201d4d42b7a7dbcd5fac4b81`, 2,739.7 s wall clock, log at
`data/runs/drain_to_green.log`:

| | released | exited | retained | closure |
| :--- | ---: | ---: | ---: | ---: |
| median of 6 members | 85.314 MCM | **82.219 MCM (96.4%)** | 3.090 MCM (3.6%) | 0.007% |

against a pre-fix baseline of roughly 42% retained. `safe_at_s = 33,977.7 s`
(9.44 h) — **zero SEVERE and zero EXTREME cells anywhere from that moment on**,
final counts 154 low / 46 moderate / 1 significant. `fully_green_at_s` is still
null: 201 cells are still wet at 30 h.

Arrival bands (p05–p95): Deccan Gymkhana 4,274–6,495 s, Shivajinagar
4,672–7,088 s. Swargate, Hadapsar and Magarpatta City record no arrival in 30 h.

**Three qualifications, none of them optional when quoting this run.**

1. **It clips the study area deliberately.** The question it answers is "when
   does the flood clear a 28 × 26 km area around Pune", **not** "the water ceased
   to exist". 82 MCM crossed the eastern edge and is downstream, unmodelled.
2. **Four variables changed at once** against the plateaued runs — domain,
   corridor conditioning, resolution (200 m) and duration (30 h). Only the volume
   balance is cleanly attributable, and it is decisive: 96.4% exited against
   0.0%. The domain is the cause; the other three are not separated here.
3. **Two gauges are boundary-contaminated.** Hadapsar and Magarpatta City are
   both 17.0 km east, 3.0 km from the outflow edge, and `_boundary_proximity`
   flags them at `BOUNDARY_CONTAMINATION_KM = 5.0` (UNVETTED — a few times the
   coarsest grid spacing, not a published figure; verification row 33). Their
   depths are shaped by the outflow condition. Loni Kalbhor (−6.5 km) and
   Baramati (−65.4 km) are outside the box altogether and report no arrival for
   that reason rather than a hydraulic one.

### Corridor conditioning — a real improvement that is NOT drainage

`condition_corridor_m` gives cells within *n* metres of the local valley floor an
infinite depression-fill cap while every upland basin keeps the ordinary
`fill_max_depth_m = 3.0`. The mask comes from `height_above_valley_floor`, a
6 km minimum filter (`window_m = 6000.0`, UNVETTED — verification row 34).

`pilot_48h` (`e5485691`) is the only conditioned run on a wide domain: wet
severity **0.358 against 0.518 and 0.551**, and low-hazard cells 62 against 6.
That is a genuine improvement in recession. **It is not drainage** — `exited_mcm`
is still zero and `safe_at_s` is still null. Only moving the boundary produced
outflow.

`pilot_48h` is **not a clean A/B**: it differs from `khadakwasla_drainage_check`
in domain (mid vs full), duration (48 h vs 24 h) and ensemble size (2 vs 4) as
well as in conditioning. The severity drop is suggestive, not attributed.

**One corridor measurement has a surviving log, and it is the only one to
quote.** From `data/runs/drain_to_green.log`, on the exit domain at 200 m:

> 465 of 1,012 corridor cells raised, max 7.5 m, **44 MCM of closed capacity
> removed**, 58 pits OUTSIDE the corridor left untouched.

Three larger figures circulate in source docstrings — 1,392 MCM (0.84% of cells),
1,686 MCM (1.03%), and 1,659 MCM across 5,075 pits — all measured on the
117 × 90 km or wider domains, none with a surviving artifact. They are **not**
interchangeable with the 44 MCM figure above. Quote a corridor figure together
with its domain and resolution, or not at all.

---

## 9. Does auto-detection work anywhere? — Baige 2018, and the answer is no

```bash
python scripts/detect_blockage_experiment.py --stage preflight   # imagery + scene table
python scripts/detect_blockage_experiment.py --stage detect      # the real detector
python scripts/detect_blockage_experiment.py --stage diagnostic  # GATE 1 BYPASSED, not a detection
```

Section 6 measured a refusal over the Rishi Ganga and attributed it to an absent
reference: JRC permanent water covers 0.001% of that window, so the pre-event
mask cannot be verified against anything. That reading was incomplete, because
the refusal happens at Gate 1 before any new-water logic runs — it could not
tell us whether the rest of the detector works.

So the detector was run against a landslide dam on a **major channel**: the
**Baige (白格) barrier lakes on the Jinsha River**, Tibet, 10 October and 3
November 2018. Rishi Ganga was kept as the control.

### The lake is real, and it is in the window

The second Baige lake is unambiguous in cloud-free Sentinel-2, one week apart:

| 2018-11-02, before | 2018-11-09, lake standing |
| :--- | :--- |
| ![before](images/blockage_detection/baige_2018_11_s2_pre.png) | ![after](images/blockage_detection/baige_2018_11_s2_post.png) |

A thin river becomes a wide impoundment terminating exactly at the landslide
scar. Three Sentinel-1 IW/VV acquisitions fall inside that lake's ten-day life
(3 Nov descending, 8 Nov ascending and descending). Nothing about the input is
marginal — this is as favourable a case as open data offers.

### Every case refuses, including that one

| case | window | JRC reference | pre-mask **water fraction** | precision | recall | verdict |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| Baige, Oct 2018 | ±0.10° | 0.5181% | **63.4%** | 0.0075 | 0.922 | refused |
| Baige, Oct 2018 | ±0.20° | 0.2603% | **68.1%** | 0.0033 | 0.872 | refused |
| Baige, Nov 2018 | ±0.10° | 0.5181% | **63.4%** | 0.0075 | 0.922 | refused |
| Baige, Nov 2018 | ±0.20° | 0.2603% | **68.1%** | 0.0033 | 0.872 | refused |
| Rishi Ganga (control) | ±0.10° | 0.0008% | 57.9% | 0.0000 | 0.000 | refused |
| Rishi Ganga (control) | ±0.20° | 0.0134% | 45.8% | 0.0002 | 0.592 | refused |

`MIN_JRC_PRECISION` is 0.5. Nothing came within two orders of magnitude of it.

**The two Baige rows per window are identical by construction** — both events
share one pre-window ending 2018-10-09, before the first barrier formed, so the
November case is not differenced against a pre-state already containing the
October lake. Identical numbers are the harness confirming itself, not a copy.

### The real defect is the threshold, not the reference

Section 6 named the Rishi Ganga's problem as a missing reference. Baige has a
reference — 0.52% of the window, comparable to Tehri's 0.572% — and still fails,
by a **different** branch of the same gate (`gate1_mask_missed_real_reference`
against the control's `gate1_no_usable_reference`).

Read the water fraction column. The split-based Otsu threshold, at −8.29 dB,
classifies **63% of a Himalayan gorge as water**, while recall against JRC is
0.92. The mask finds the river and then also finds two-thirds of the mountain:
in VV backscatter, slopes facing away from the sensor are radar shadow and are
dark for the same reason water is dark.

`derive_threshold_from_tiles` accepted 17 of 64 sub-tiles at median separability
0.732 — it is confident. Its own docstring says it exists to beat "the confident
45%-water mask whole-scene Otsu produced over Tehri". Per-tile splitting made
that worse here, not better: 63%. The bimodality it detects is land against
shadow.

`sar.MAX_PLAUSIBLE_WATER_FRACTION = 0.80` would not catch this either — 63% is
under it — and `blockage_detect` never applies that guard at all.

So Gate 1 is not the limit. It is the symptom, and it is doing its job: it
refuses because the mask beneath it is wrong. **Widening it would publish a
63%-water mask as a lake.**

### What the downstream gates would have done — Gate 1 bypassed

Because Gate 1 refuses everywhere, Gates 2 and 3 have never executed on real
data. The `--stage diagnostic` mode rebuilds the candidate with Gate 1 skipped.
**This is not a detection**; it writes no `blockage_manifest.json`, so nothing it
produces can be read back as an observation.

Baige, November 2018, ±0.10°:

| stage | measured | limit | would it pass? |
| :--- | ---: | ---: | :--- |
| post-event water mask | 65.1% of window | 80% (`MAX_PLAUSIBLE_WATER_FRACTION`, never applied here) | passes |
| candidate "new water" | **33.0% of window** | — | — |
| near drainage | **12.6%** | ≥ 80% | **refuses** |
| area floor | 18,099,828 m² | ≥ 20,000 m² | passes, by 900× |
| flatness spread | **932.9 m** | ≤ 5 m | **refuses** |
| flatness mean slope | **31.70°** | ≤ 2° | **refuses** |

Consistent across all six cases (candidate 6.2–33.3% of window, 10–16% near
drainage, spread 933–3,258 m, slope 31.3–35.8°).

Three things follow:

1. **Gate 3 (drainage proximity) is a genuine backstop.** A 33%-of-the-window
   candidate is only 13% near a watercourse, so it would be refused even without
   Gate 1. Two independent gates catch this.
2. **The flatness gate is the strongest, refusing by 186× on spread and 16× on
   slope — and it is never invoked.** `score_candidate_flatness` is called "the
   strongest filter and it is free" in the module docstring, and `_fetch_live`
   does not call it. This measurement is the first evidence of how well it works.
3. **The area floor is worthless as written.** `MIN_NEW_WATER_AREA_M2 = 20,000`
   is exceeded by 900× on pure garbage — and it is never referenced in
   `_fetch_live` anyway, so there is no area floor in the shipped code.

### The window-size sensitivity resolves nothing

Doubling the box changes the reference fraction (Rishi Ganga 0.0008% → 0.0134%,
Baige 0.518% → 0.260%) but flips no verdict. The Rishi Ganga stays under
`MIN_JRC_REFERENCE_FRACTION` at both sizes, so section 6's classification of it
stands. The refusal is not an artefact of how much river the box caught.

### The remedy was built, and it does not work — measured 2026-09-04

`jalraksha/gee/terrain_correction.py` now implements the local-incidence-angle
masking this section named as the fix: shadow and layover classified from the
signed range-plane slope against Copernicus GLO-30 and the scene's own geometry,
excluded before any histogram is derived. It is applied in both
`sar._fetch_live` and `blockage_detect._fetch_live`. **It does not rescue the
detector, and the measurement is worth more than the fix would have been.**

Geometry actually excluded, at 60 m over the detect windows:

| window | valid | shadow | layover |
| :--- | ---: | ---: | ---: |
| Baige ±0.10° | 83.45% | **0.09%** | 16.47% |
| Rishi Ganga ±0.20° | 85.34% | 2.41% | 12.25% |

And the effect on the gate that was failing:

| case | precision, uncorrected | precision, geometry-masked | recall |
| :--- | ---: | ---: | ---: |
| Baige 2018-10 ±0.10° | 0.0075 | 0.007 | 0.92 → 0.85 |
| Baige 2018-10 ±0.20° | 0.0033 | 0.003 | 0.87 → 0.79 |
| Baige 2018-11 ±0.10° | 0.0075 | 0.007 | 0.92 → 0.85 |
| Baige 2018-11 ±0.20° | 0.0033 | 0.003 | 0.87 → 0.79 |
| Rishi Ganga ±0.10° | 0.0000 | 0.000 | 0.00 → 0.00 |
| Rishi Ganga ±0.20° | 0.0002 | 0.000 | 0.59 → 0.49 |

Precision has to reach 0.5. It moved from 0.0075 to 0.007 — a **70× shortfall,
closed by nothing** — while recall fell, because some genuine water sat in the
excluded layover band. Every case still refuses, at the same gate, for the same
class of reason.

**The diagnosis in the row above was wrong in its emphasis, and the geometry
says so: radar shadow is 0.09% of the Baige window.** There was never enough
shadow there for shadow to be the explanation. The mis-classified pixels are on
slopes that are geometrically perfectly imageable and merely *dark* — dry, smooth
or unfavourably oriented ground whose backscatter overlaps open water's. That is
a radiometric problem, not a geometric one, and the half of Small (2011) that
addresses it is the flattening to gamma-nought that normalises each pixel by its
local illuminated area. **That half is not built, and this measurement is the
reason to doubt that building it would be enough either**: at 0.007 precision the
false positives outnumber the true ones 140 to 1.

The masking is kept regardless. Excluding layover is correct on its own terms —
a layover pixel is a superposition of several places and means nothing wherever
it appears — and any radiometric correction would need the same geometry
underneath it. It is a prerequisite that turned out not to be sufficient, which
is a different thing from a fix.

**A caution about how this was nearly reported.** The first run after the
correction landed showed the numbers barely moving, which was taken at face
value until the geometry fractions were checked directly: `valid_fraction` came
back as exactly **1.0000** over a Himalayan gorge. `ImageCollection.mosaic()`
returns an image whose projection is EPSG:4326 with the identity transform — one
degree per pixel, nominal scale 111,319 m — and `ee.Algorithms.Terrain` computes
slope in its input's own projection, so slope was 0.000° everywhere and the
module excluded nothing while reporting that it had terrain-corrected the scene.
Declaring GLO-30's native 30 m posting gives 30.8° mean and 66.0° max over the
same window. **A no-op and a real correction produced almost the same detector
output**, so the near-identical precision figures were not evidence either way
until the mask itself was measured. `tests/test_terrain_correction.py` now
asserts the projection is declared.

### Conclusion

**The Sentinel-1 auto-detection path does not work over mountain terrain, and
Baige rules out the explanation section 6 offered.** It is not that the
Himalayan headwater is too narrow for JRC to map — a wide channel with an
optically confirmed lake and three usable acquisitions fails too. Nor, as
measured above, is geometric radar shadow the cause: it is 0.09% of that window,
and masking it changes nothing. What remains is that VV backscatter alone does
not separate water from dark land in this terrain at the precision the gate
requires.

Nothing was widened to make a case pass, before or after the correction. **The
manual barrier path runs fully offline, needs no scene, and remains the demo's
guaranteed floor.**

Caveats on this measurement:

- The Baige coordinates (31.08 N, 98.71 E) are working values confirmed
  *visually* against Sentinel-2, not transcribed from a surveyed source.
- The October 2018 event's optical after-image is fully clouded, so that lake's
  presence is not independently confirmed; only one Sentinel-1 scene (10 Oct,
  the day the barrier formed) fell inside its ~3-day life. Its gate numbers are
  identical to November's by construction and carry no separate weight.
- The flatness figures come from a nearest-neighbour resample of an EPSG:4326
  mask onto a 60 m UTM grid — adequate for a gate refusing by 186×, not a
  precise measurement.

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
- **The Rishi Ganga blockage has no quantitative benchmark.** The published
  HEC-RAS study of the 7 Feb 2021 flow reports peak discharge and depth at two
  named points (Rishiganga 7,908–7,975 m³/s at 19.85 m; Tapovan 5,780–5,957 m³/s
  at 18.15 m — literature.md §11.2). Comparing against them needs **channel**
  coordinates for those points, which this repository has not sourced: the
  gazetteer town coordinates sat 1,319 m and 79 m above the nearest channel and
  were removed. Until they are sourced, the corridor publishes three
  DEM-traced thalweg points that name no town, and the scenario carries no
  quantitative validation.
- **The Rishi Ganga barrier's own dimensions are not measured.** No crest height
  or width is published for the 2021 blockage. Both are *measurable* — difference
  Zenodo 4554647 (pre-event, 2 m) against 4558692 (post-event) — which is
  verification queue row 26. The preset publishes both as `None` and the operator
  supplies them.
- **The Khadakwasla drainage recovery is measured only on a clipped domain.**
  §8 now carries a post-fix curve — run `e2e09ea3`, 96.4% of volume exported,
  zero SEVERE cells from 9.44 h — but it was obtained by shrinking the study area
  to 28 × 26 km so the flood crosses a boundary. **On any domain wide enough to
  contain the flood, nothing has ever drained**: `exited_mcm` is zero in every
  wide-domain run. Whether the remaining water would leave a real floodplain, and
  by what mechanism, is untested; the solver has no infiltration, evaporation or
  seepage sink.
- **Corridor conditioning is not isolated.** Its one wide-domain run (`e5485691`)
  differs from its comparator in domain, duration and ensemble size as well as in
  conditioning, so the severity improvement (0.358 vs 0.518) is suggestive and not
  attributed. Only one corridor measurement (44 MCM, exit domain at 200 m) has a
  surviving log; the larger figures in source docstrings do not.
- **`mutha_temghar` produced no arrival at any gauge**, and that is the expected
  attenuation for a 39.1 MCM release into an 85.31 MCM reservoir 26 km
  downstream — but it is an expectation, not a validated result. The site is
  HYPOTHETICAL: nothing published from it may describe the barrier as observed.
- **The Tehri `solver="both"` path fails at the initial condition.** Run
  `37e1e713` (`data/runs/flashflood.log`): *"Impounding 3540.0 MCM over 9.72 km2
  requires a mean depth of 364.2 m, which exceeds the dam height of 260.0 m."*
  The far-field SWE run completed and exported 18 products; the comparison is
  recorded as not written. Same root cause as the `compare_tehri` entry above —
  the detected pool is too small for the published storage figure.
- **Walder & O'Connor (1997) and Peng & Zhang (2012) are not transcribed.** Both
  are implemented in shape and quarantined behind `*_VERIFIED = False`; calling
  either raises. Costa (1985) is the only active natural-dam regression, so a
  blockage ensemble has no inter-method spread and takes its range from a
  prediction band whose width is itself an unvetted placeholder (rows 19–22).
- **A real GPU out-of-memory has never happened.** Ensemble chunks are sized
  from free VRAM, and the fall-back from a failing GPU ensemble to the CPU is
  tested, but only with a simulated failure (`TestBackendFallback`). No run has
  actually exhausted the 6 GB card (two concurrent API runs on large grids
  would be the way to do it). The code is written to fall back; that it does so
  under real memory pressure is untested.
- **GPU SPH has never produced a result.** The OpenCL path is wired and
  requests float64, but on Python 3.14 PySPH's code generator (compyle 0.9.1)
  cannot build its kernels, so every SPH run so far is a CPU run. Whether a
  compyle release without `ast.Str`, or Python 3.13, would run it is untested.
- **The GPU speed-ups are from one machine.** Every figure in §11 is from this
  laptop's RTX 4050 (FP32/FP64 = 64). A GPU with more float64 throughput would
  change the speed-up, not the physics; nothing else has been measured.


---

## 10. FD2320 hazard classification had five definitions, and two live ones disagreed

Found by `/code-quality-deep-dive` on a clean tree; the solver core passed every
item on that skill's checklist and none of this touched it.

`jalraksha/impact/hazard.py` declares itself "the SINGLE source of truth for
hazard classification". It was neither single nor self-consistent.

| # | Location | Form | Live? |
| :-- | :--- | :--- | :--- |
| 1 | `hazard.py` module docstring | depth bands, Low ≤0.1 … Extreme >5.0 | doc only |
| 2 | `hazard.py` `self.thresholds` | depth+velocity band table, Low 0.1–0.5 … Extreme ≥10.0 | **yes** — dashboard |
| 3 | `hazard.py` `categorize_hazard_zones` | `HR = d(|V|+0.5)+0.5`, classed 0.75/1.25/2.5 | tests only |
| 4 | `export/shapefile.py`, inline | 0.1/0.5/1.2/2.0 m against v of 1/2/4 m/s | **yes** — shapefiles |
| 5 | `frontend/.../GaugesPanel.jsx` | depth only, 5 m / 10 m edges | **yes** — gauge badges |

Table 2 is one full class COARSER than table 1, in the same file: a 3 m depth is
"severe" by the docstring and "significant" by the code, and 0 < h < 0.1 m
matched no band at all and reported DRY. Tables 2 and 4 disagreed with each
other on live output — a cell 1.5 m deep was *moderate* on the dashboard and
*high* in the exported shapefile, both labelled FD2320.

**Velocity could only ever REDUCE hazard.** Table 2 tested
`velocity <= max_velocity` as one term of an AND with the depth window, so a
cell exceeding a band's velocity ceiling fell out of that band without being
promoted into a higher one. Traced by hand and now pinned by a test: depth
3.0 m at 8 m/s failed LOW (depth), MODERATE (depth), SIGNIFICANT (velocity),
SEVERE (depth) and EXTREME (depth), and kept the DRY initialisation. That is a
lethal flow reported as dry ground. `classify()` had no non-test caller, so it
was latent — but it is the method the velocity-aware path would have used.

**Resolution.** Table 3 — the published Defra form, already implemented and
tested — is now the only definition. `HazardClassifier` computes it, tables 2
and 4 are deleted, and table 5 mirrors the depth-only reduction of table 3
(`HR = 0.5d + DF`, edges at 0.5 / 1.5 / 4.0 m) rather than inventing its own.
Two consequences worth stating plainly:

- **`severe` is gone.** FD2320 publishes four wet categories and no boundary
  that would split extreme. Retiring the level was preferred to inventing a
  threshold, which is what `natural_dam.py`'s own policy forbids elsewhere.
- **The debris factor is a categorical input.** The trailing `+ 0.5` was a
  hardcoded literal; DF is published as 0 / 0.5 / 1.0 by land use. It is now a
  named parameter defaulting to 0.5 and echoed in every summary payload. This
  module deliberately does not infer it from land cover — that mapping belongs
  beside the WorldCover legend and does not exist yet.

`hazard_weights`, which drives `weighted_hazard_index`, remains **UNVETTED**:
FD2320 publishes classes, not a weighting between them, and no source has been
identified for those numbers.

## 11. GPU backend: float64 on a laptop RTX 4050, measured 2026-09-12

The project declined a GPU port twice (`solver/parallel.py`, Technical Reference
PERF-6) on an estimate. Consumer Ada GPUs run float64 at 1/64 of float32 (the
driver reports an FP32/FP64 ratio of 64 for this card), so "a float64 CUDA port
would likely be slower than these CPU kernels". The estimate was never
measured, and on this machine it could not have been: the NVIDIA driver was
present but NVVM was not, so `numba.cuda` could not compile anything.
`pip install "numba-cuda[cu12]"` now supplies NVVM and NVRTC as pip wheels.

**Performance.** Same float64 physics, same machine (16 logical cores),
measured with nothing else running. JIT compilation is excluded on both sides.

| Case | CPU (numba) | GPU (CUDA) | Speed-up |
| :--- | ---: | ---: | ---: |
| One member, 376 × 480 cells, 600 s simulated, 1,765 steps | 72.4 s (41.0 ms/step) | 5.74 s (3.25 ms/step) | **12.6×** |
| One member, 600 × 600 cells, 600 s simulated, 1,865 steps | 136.4 s (73.1 ms/step) | 6.72 s (3.60 ms/step) | **20.3×** |
| 30-member ensemble, 376 × 480, 900 s each (CPU: its own pool of 8 workers) | 455.6 s | 39.7 s | **11.5×** |

Step counts are identical on both backends in every row (the ensemble's mean is
1,132.3 steps per member on each). The single-member speed-up GROWS with the
grid, because 376 × 480 does not fill the GPU: going from 180 k to 360 k cells
costs it only 3.25 ms to 3.60 ms per step. The ensemble speed-up is lower than
the single-member one because the CPU side is no longer one process: it spreads
members over worker processes, which is the CPU's best case.

Why the estimate was wrong: it compared peak float64 FLOP rates, but the CPU
kernels never come near the CPU's peak. They are scalar loops, and the 2.37×
scaling from 1 to 16 threads recorded in `parallel.py` shows they are held back
by memory and synchronisation, not arithmetic. The ratio that decides the
question is achieved throughput: 4.4–4.9 million cell-updates per second on the
CPU against 55.5 million (376 × 480) and 100 million (600 × 600) on the GPU.
Nobody had measured it.

**Correctness. The GPU is held to the gates, not merely to the CPU.**

- Every test in `tests/test_solver.py` (the blocking gates plus Ritter, Stoker
  and Thacker) is parametrized over both backends: 42 passed, 21 on each.
- Lake at rest over random bathymetry: |V| = 5.1e-14 m/s on the GPU against
  6.0e-14 on the CPU (gate: 1e-8). Closed-box mass drift: 4.3e-16 (gate: 1e-3).
- The Delft3D Ritter cross-check (`scripts/validate_against_delft3d.py --case
  ritter`), run on the GPU: JalRaksha RMSE 0.0317 m and depth at the dam
  4.532 m. These are the same figures to four decimals as the CPU result in §1.
- Same inputs on both backends: step counts are identical, h_max agrees to
  ≤5e-15 relative, arrival times agree to 3.6e-15 s, and volume balances agree
  to 1e-15. The batched ensemble's snapshot frames are bit-identical (they are
  float32).
- The full pipeline on real terrain: Khadakwasla, 8 members, 2 h at 200 m
  (270 × 270), run through `run_dam_break_ensemble` on each backend. Gauge
  arrivals agree to 9e-13 s, the h_max statistics are identical, and the
  released volume of 67.206 MCM agrees to 5e-15. The first attempt at this
  comparison disagreed by up to 310 s, and that was not the solver:
  `run.py` does not seed the breach ensemble, so the two runs drew different
  hydrographs. The rerun pins the seed.
- Whole-pipeline wall-clock for that configuration, including the DEM
  preparation and exports that do not run on the GPU: 369.7 s on the CPU
  process pool against 52.8 s on the GPU (7.0×). This was measured on the
  unseeded pair, so the two drew different hydrographs and the figure is
  indicative, not exact.

**Not bit-identical, and deliberately not tested as if it were.** NVVM fuses
`a*b + c` into a single-rounding FMA, and numba-cuda has no switch to stop it.
libdevice's `pow` can also differ from the C runtime's by an ulp. Measured on
a probe kernel, 89% of results are bit-identical and the maximum difference is
8.9e-16. The equivalence tests (`tests/test_solver_cuda.py`,
`tests/test_parallel.py::TestGpuEnsemble`) therefore bound the difference about
six orders of magnitude above round-off, and far below anything physical.

**What did not move to the GPU, and why:**

- **Near-field SPH.** PySPH's OpenCL backend is wired in (`--opencl
  --use-double`, NVIDIA preferred over the AMD iGPU). But PySPH generates its
  GPU kernels through compyle 0.9.1, which still uses `ast.Str`, and Python
  3.14 removed it. The first GPU kernel dies with `module 'ast' has no
  attribute 'Str'`. `resolve_sph_backend` detects this from compyle's own
  source and falls back to the CPU, recording the reason. The CPU still-water
  gate was re-run at 8,000 particles over 2 s: residual speed 0.27 m/s,
  hydrostatic slope error 4.7%, density error 0.60%, 148 s wall-clock.
- **Serial algorithms and I/O**: the breach-routing ODE (sequential in time),
  priority-flood depression filling (a heap), DEM fetch and exports.

### Ensemble members use the per-cell Manning field (fixed 2026-09-12)

Every ensemble member used to be solved with a UNIFORM Manning's n equal to the
mean of the field it was handed. On the CPU that was
`SWESolver(manning_n=float(np.mean(field)))`; the GPU built the same uniform
field, on purpose, so the two backends could be compared. That silently undid
`terrain/roughness.py`, whose whole point is that friction follows land cover.
Both backends now solve with the field itself. The GPU builds and validates it
with the same `SWESolver` code as the CPU, so a field the CPU refuses (a
negative n, a wrong shape) fails every member on both backends with the same
message.

**What it changes, measured.** The test case is a 200 × 160 valley at 100 m,
30 minutes, with a peak of 8,000 m³/s. It uses a WorldCover-style class map:
tree cover (n = 0.100) on the slopes, cropland (0.040) on the floodplain, a
permanent-water channel (0.030), and a built-up block (0.080) downstream. The
field's mean is 0.091, because tree cover dominates the area, so averaging
makes the channel three times rougher than it is. With the per-cell field:

- the flood reaches 308 cells, against 170 with the mean;
- it reaches channel reaches that the averaged run never wets;
- it floods part of the built-up block (mean h_max 2.6 m), which the averaged
  run never reaches.

Where both runs wet a cell, the per-cell field brings arrival earlier by a
median of 209 s (699 s earlier at the 5th percentile). h_max differs by 70%
in relative L2.

**What it does NOT change today.** `terrain/domain.py::build_domain` hands
every run a UNIFORM field (dam_config "manning_n", default 0.03), because
nothing in the pipeline fetches WorldCover yet, and the mean of a uniform field
is that field. Every run made through `run_dam_break_ensemble` so far is
therefore unaffected; the fix takes effect as soon as a non-uniform field is
supplied. Runs written before it are NOT reclassified. The run summary now
records the field the members were actually solved with (`roughness`: min,
max and mean n, distinct values, fraction at the default, `is_uniform`, and a
one-line note), so a uniform field can no longer pass for a land-cover one.

### The member-loop timestep: one dt per step (fixed 2026-09-12)

The member loop used three different timesteps per iteration. It injected the
breach hydrograph with the CFL timestep computed BEFORE injection. The solver
step then recomputed its own timestep on the post-injection state. And the
member clock advanced by the first of the two. Measured on a 200 × 160 valley
over 30 simulated minutes, for peak outflows of 2,000, 8,000 and 20,000 m³/s,
the member clock ran 2.6%, 1.9% and 1.8% ahead of the physics time actually
integrated. Arrival times are stamped with that clock, so they read late by the
same fraction of elapsed time. The released volume exceeded what the hydrograph
delivers over the integrated time by 1.2%, 0.8% and 0.7%. In the worst single
step, the injection used a timestep 14–28× longer than the step the solver then
took.

**The fix.** `parallel.inject_with_one_timestep`, and its GPU mirror
`ensemble_cuda.choose_injection_step`, pick ONE timestep. They start from the
pre-injection CFL limit and inject. If the post-injection limit is lower, they
shrink to it and re-inject. The step and the clock then use that same dt.
`tests/test_parallel.py::TestMemberTimestep` asserts the three properties this
buys:

- the member clock equals the integrated physics time, to round-off;
- every step is CFL-valid for the state it actually integrates;
- the released volume equals Σ Q(tₙ)·Δtₙ exactly, and equals the hydrograph
  integral to within the left-Riemann bound.

**Why this rule, measured.** Four ways to use a single timestep were run on the
dry valley (200 × 160 at 100 m, 30 minutes), with and without a 25 m notch at
the breach cell (as `notch_breach` cuts one), for peaks of 2,000 and
20,000 m³/s. Each was scored against the chosen rule run at a tenth of the
timestep (CFL 0.03). Ranges are across the four cases:

| Scheme | Clock vs physics | Released vs hydrograph | Worst step, × its CFL limit | Arrival error vs reference: median / p99 / max |
| :--- | :--- | :--- | :--- | :--- |
| old: three timesteps | +1.5% to +2.6% | +0.6% to +1.2% | ≤ 1 | 1.0–7.5 s / 9.3–15.8 s / 20.7–28.9 s |
| inject and step with the pre-injection dt | exact | −0.14% to −0.16% | **13.7× to 43.4×** | 1.1–1.8 s / 3.5–21.2 s / 20.9–32.3 s |
| step first, then inject | exact | −0.14% to −0.16% | ≤ 1 | 1.3–2.5 s / 3.7–15.0 s / 20.9–28.9 s |
| **pre-injection dt, shrunk to the post-injection limit (chosen)** | exact | −0.07% to −0.09% | ≤ 1 | **0.13–0.55 s / 0.24–1.82 s / 0.38–2.99 s** |

"Released vs hydrograph" is measured against the trapezoid integral. The
exact-clock schemes sit just below it by the left-Riemann error of holding Q at
its value at the start of each step.

- **Using the pre-injection dt as it stands is rejected.** It runs the step up
  to 43× over its CFL limit. It happened not to blow up here, because only one
  cell is affected, but nothing guarantees that.
- **Stepping first and injecting afterwards is stable but 5–10× less
  accurate.** The source lags the transport by one step, and the first
  injection lands as a single slug of up to `dt_max` (30 s) of outflow.
- **The chosen rule costs 3–13% more CPU wall-clock**, from the extra CFL
  evaluation on steps that need the shrink. A notched breach cell needs it on
  almost every step. It costs nothing on the GPU, where each trial is O(1).
- **How many trials it takes, and how close to the limit it steps.** Almost
  every step settles in one or two trial injections. The most any step needed
  was 6, on the 20,000 m³/s un-notched case, so the cap of 8
  (`MAX_INJECTION_PASSES`) was never reached. Where adding water RAISES the
  breach cell's limit (the wet-fraction term), the shrink converges on the
  limit from above without ever crossing it. The first version therefore spent
  all 8 trials on 4 steps and ended within 5e-7 of the limit. Acceptance now
  has an explicit relative slack of one part in a million
  (`INJECTION_CFL_RTOL`): a Courant number of 0.3000003 against the 0.3
  ceiling, where the positivity proof holds to 0.5. The worst step measured is
  1.0000009× its limit, and `injection_step_overruns`, which counts steps that
  ran out of trials above the limit, is 0 in every case.

**What it changes.**

- On the dry valley above, arrival times move EARLIER by up to 2.6% of elapsed
  time, and the ~1% over-injection is gone.
- On Khadakwasla (8 members from a fixed seed, 2 h at 200 m), nothing
  measurable changed, on either backend: gauge arrivals moved by less than
  0.5 s, and released volume by less than 0.001 MCM. The shrink fired in 1 of
  about 75,000 member-steps. On that domain the breach cell almost never sets
  the CFL limit, so the old and new loops pick the same dt.
- Runs written before the fix are NOT reclassified. Their arrival times carry
  whatever bias the old loop had on their terrain: up to about 2.6% late where
  the breach cell set the timestep, and nothing measurable on the Khadakwasla
  configuration.
