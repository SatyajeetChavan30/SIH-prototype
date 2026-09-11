# Archive — historical status snapshots

These files recorded where the build stood at a moment in time. They are kept
unedited below their banner, because a snapshot that is quietly corrected stops
being one. **None of them describes the current system** — for that, read
`CLAUDE.md` (project guide and repository layout) and
`docs/validation_findings.md` (measured results).

The Technical Reference Manual cites several of these as sources; its citations
refer to the files here.

| File | Recorded | Date | Superseded by |
| :--- | :--- | :--- | :--- |
| `ARCHITECTURE_IMPROVEMENTS.md` | The `/improve-architecture` pass that created the `floodview/` package and moved presentation tooling to `tools/` | 2026-08-23 | CLAUDE.md "Repository layout" |
| `architecture-review-phase0.html` | The Phase 0 architecture review, written before any solver code existed | 2026-08-23 | CLAUDE.md "Repository layout" |
| `SUMMARY.txt` | Project overview while Phase 1 was in progress | 2026-08-23 | README.md, CLAUDE.md |
| `BUILD_STATUS.md` | Phases 0–3 complete, 235/239 tests, the since-removed Streamlit dashboard | 2026-08-24 | `docs/progress.md`, CLAUDE.md |
| `PHASE_3_4_SUMMARY.txt` | The first end-to-end breach → solver pipeline | 2026-08-24 | CLAUDE.md, `docs/validation_findings.md` |
| `PHASE1_STATUS.md` | Solver scaffolding with the lake-at-rest gate still failing (moved from `floodview/solver/`) | 2026-08-24 | `tests/test_solver.py` — the gate passes at machine precision |
| `PROGRESS_SUMMARY.md` | The real-terrain integration pass that voided every earlier result | late Aug 2026 | `docs/progress.md`, `docs/dashboard_integration.md` |
| `report.md`, `report.html` | A technical reference written while SPH, GEE and the Impact tab were still unwired | 2026-08-30 | `docs/FloodView_Technical_Reference_Manual.md`, `docs/dashboard_integration.md` |
