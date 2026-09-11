# SIH Presentation Tooling

Scripts for generating and validating the Smart India Hackathon 2026 submission decks for JalRaksha (PS-26161).

Every script resolves its `.pptx` inputs and outputs from the **repo root**, where the SIH template and the submitted decks live, so they can be run from any working directory.

## Scripts

- **build_ppt.py** — Generate `JalRaksha_SIH2026_PS26161.pptx` from the official SIH template
  ```bash
  python tools/sih-presentation/build_ppt.py
  ```
  Reads: `<repo root>/SIH2026-IDEA-Presentation-Format.pptx` (official template, unmodified)
  Writes: `<repo root>/JalRaksha_SIH2026_PS26161.pptx`

- **check_ppt.py** — Validate that deck for text overflow, font metrics and bounds
  ```bash
  python tools/sih-presentation/check_ppt.py
  ```
  Reports any text frames that are clipped or tight for PDF export.

- **build_deck.py** — Generate the idea-submission deck `JalRaksha_SIH2026_Idea.pptx` from the same template, using the prepared images in `assets/prepared/` and the logos in `assets/logos/`.

- **check_deck.py** — The overflow check for the idea deck.

- **export_pdf.ps1** — Render a deck to PDF (output under `render/`, which is git-ignored).

Supporting files: `assets_prep.py` (prepares images), `capture_dashboard.py` (dashboard screenshots), `logos.js` + `package.json` (regenerate the technology-stack logos with node; the generated PNGs are committed, so building a deck never needs node).

## Constraints

- Maximum 6 slides (including title)
- Points and diagrams, not paragraphs
- Must export to PDF before uploading to SIH portal
- All factual claims traced to docs/research/

## Separation

These scripts are isolated in `tools/` because they are **not load-bearing** for the core JalRaksha system. The presentation tooling serves documentation/submission purposes only; the solver lives in `jalraksha/`.

Until 2026-09-11 a second copy of `build_ppt.py` and `check_ppt.py` sat at the repo root. Those were the only copies whose folder-relative paths could find the template, and they were removed in `94a994e`; the scripts here now resolve paths from the root instead.
