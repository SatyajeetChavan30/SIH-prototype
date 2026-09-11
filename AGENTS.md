# AGENTS.md

Guidance for Codex and other coding agents working in this repository.

**`CLAUDE.md` is the authoritative project guide — read it in full before
changing code.** It holds the repository layout, the architecture rules, and the
record of every defect found and fixed, including why each guard exists. This
file only repeats the rules that must never be broken, so that an agent which
reads nothing else still cannot break them. It deliberately does not copy the
rest of CLAUDE.md: an earlier full copy drifted out of date within two weeks.

## Hard rules

- **Mullaperiyar is forbidden** (active Supreme Court litigation). **Tehri** is
  the demo case (260 m, 3,540 MCM).
- **Metric CRS only** for every solver operation — UTM metres, never degrees.
  Cell-centred finite volume on uniform Cartesian grids.
- **Delft3D naming follows the evidence.** Say "Delft3D FM (dflowfm-cli,
  dimrset 2026.01)" only when `delft3d_binary_used` is True; otherwise
  "FloodView built-in 2D SWE — Delft3D-class, NOT Delft3D FM", plus the reason
  it fell back.
- **SPH ↔ SWE coupling is one-way** (SWE → SPH handoff). Never claim two-way.
- **Every coefficient needs a primary-literature citation**, or a
  `# TODO: UNVETTED` marker naming the source still needed. Check
  `docs/VERIFICATION_LOG.md` before hardcoding any breach, fatality or
  depth-damage value. Quarantined models stay behind their `*_VERIFIED = False`
  flags.
- **Open data only.** Copernicus GLO-30 and Google Open Buildings (CC BY 4.0) are
  approved. Keep FABDEM, MERIT and OSM out of redistributed outputs.
- **Offline-first.** Everything must run from cache after the first fetch.
- **Lead with arrival times and inundation envelopes**, not point depths — a
  30 m DEM makes point depths indicative only.
- **Never fabricate a result.** Synthetic assets are labelled wherever they can
  be seen, and an observation that fails its quality gate is refused, never
  replaced with a synthetic one.

## Working here

- Tests: `python -m pytest tests/ -q`. The lake-at-rest and mass-conservation
  gates in `tests/test_solver.py` must pass before any merge.
- Codex settings live in `.codex/` (`config.toml`, `hooks.json`).
