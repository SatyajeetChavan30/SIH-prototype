# SIH Presentation Tooling

Scripts for generating and validating the Smart India Hackathon 2026 submission deck for FloodView (PS-26161).

## Scripts

- **build_ppt.py** — Generate FloodView_SIH2026_PS26161.pptx from the official SIH template
  ```bash
  python build_ppt.py
  ```
  Reads from: SIH2026-IDEA-Presentation-Format.pptx (official template)
  Writes to: FloodView_SIH2026_PS26161.pptx

- **check_ppt.py** — Validate deck for text overflow, font metrics, and bounds
  ```bash
  python check_ppt.py
  ```
  Reports any text frames that are clipped or tight for PDF export.

## Constraints

- Maximum 6 slides (including title)
- Points and diagrams, not paragraphs
- Must export to PDF before uploading to SIH portal
- All factual claims traced to docs/research/

## Separation

These scripts are isolated in `tools/` because they are **not load-bearing** for the core FloodView system. The presentation tooling serves documentation/submission purposes only; the solver lives in `floodview/`.
