# Progress-site update — 14 September 2026

Supersedes `Progress_Update_2026-09-13.md`. Filled from `docs/progress.md` (checkpoint 2026-09-12), `README.md` and `desktop/README.md` (validation record 2026-09-13). Paste everything between the rules into the tool that built the site.

---

Update the (PROJECT NAME) progress website with the changes below. Two things happened since the site was written: the flood solver now runs on a GPU, and the whole system now ships as a Windows installer.

**Scope.** Edit the content file (`src/content.js` / `content.json`) for everything except item 3, which adds one new section using the existing card component. Do not change the palette, typography or section order otherwise. Apply each change everywhere the value appears. Set the "Last updated" date in the hero pill and the footer to **14 September 2026**.

**1 — Hero stats.** Two changes, other two cards unchanged:
- First card: **821** — automated tests passing (7 skipped). This replaces the old "600 / 4".
- Fourth card: replace "8 — dashboard tabs running on real simulation data" with **11.5×** — faster flood ensemble on an NVIDIA GPU, in full double precision (30 members: 455.6 s → 39.7 s). The "8 tabs" fact stays in the progress table row D9.

**2 — Hero buttons.** Add a new primary button, first in the row: **"Download for Windows"** → `(WINDOWS INSTALLER LINK)`. Demote "Read the detailed document" to secondary. Under the button row, one line of small muted text: *"Windows 10/11, 64-bit. The installer is not code-signed yet, so Windows will show a SmartScreen warning the first time you run it."*

**3 — New section, placed straight after "How it works".** Title: **"Three ways to run it"**. Three cards, same component as elsewhere:

- **Windows installer** — *"One installer carries the dashboard, the simulation service and the solver. No Python, no setup. Choose the CPU build, or the GPU build if the machine has an NVIDIA driver."*
- **Browser dashboard** — *"Run the service and the dashboard from a checkout, the way we develop it."*
- **Docker Compose** — *"The full stack in containers, for a server deployment."*

Then one paragraph under the cards: *"The installer carries no data and no credentials. A fresh install shows no runs until you import a data pack — a zip that lists every file with its checksum and its licence, and refuses anything that fails validation or would overwrite an existing file. Our Khadakwasla pack is 86.2 MB and holds the flagship run plus the elevation and population data it needs, so the app works with no internet."*

**4 — New results block, after the existing runs table.** Title: **"Compute performance"**.

| Case | CPU | GPU | Speed-up |
| --- | --- | --- | --- |
| One ensemble member, 376 × 480 cells | 72.4 s | 5.74 s | 12.6× |
| One ensemble member, 600 × 600 cells | 136.4 s | 6.72 s | 20.3× |
| 30-member ensemble benchmark | 455.6 s | 39.7 s | 11.5× |

Caption: *"Both backends run in full double precision, so the GPU result is not a lower-precision approximation — the two agree to about 1 part in 10¹⁵. The speed-up grows with grid size, because the smaller grid does not fill the GPU. The GPU needs only the NVIDIA driver, not the CUDA toolkit."*

Paragraph under it: *"If a GPU is requested on a machine that cannot provide one, the run is refused before it starts rather than quietly falling back to the processor — otherwise every timing and every label the run carries would be false. The dashboard's Compute selector reads what the machine can actually offer."*

**5 — Second new results block: "Measured on the packaged app".** Sub-caption: *"Windows 11, RTX 4050 laptop GPU, 13 September 2026."* Four small stat cards:
- **2.4 s** — from launching the app to a working simulation service
- **~25 s** — a 2-member, 15-minute Khadakwasla flood run, producing 20 export files (about 14 s on the GPU build)
- **2 s** — to import the 86.2 MB Khadakwasla data pack (228 files, every one checksummed)
- **320 MB / 429 MB** — installer size, CPU build and GPU build

**6 — Label the existing runs table as CPU.** Those three Khadakwasla runs were measured on 16 processor cores before the GPU backend existed. Say so in the sub-heading, and delete the phrase "with no GPU" wherever it appears, so it no longer reads as a limitation.

**7 — Progress table.** No deliverable changes status; leave the "10 of 12 · 2 in progress" bar alone. Extend the D9 row's "What exists today" to end with: *"…plus a Compute selector for choosing the processor or the GPU, and the same dashboard inside a Windows app."*

**8 — How it works, step 4.** Append: *"Runs on the processor or, in full double precision, on an NVIDIA GPU."*

**9 — Timeline, three new entries at the top:**
- **13 Sep 2026** — (PROJECT NAME) now installs as a Windows application: dashboard, simulation service and solver in one installer, in a processor build and a GPU build. Nothing is written into the install folder, and uninstalling keeps your runs.
- **12 Sep 2026** — Double-precision GPU backend for the flood solver: a 30-member ensemble drops from 455.6 s to 39.7 s. Selectable from the dashboard, and refused up front on machines that cannot run it.
- **12 Sep 2026** — Two ensemble defects, both found by writing the GPU version and comparing it against the processor version: the simulation clock was running 1.8–2.6 % ahead of the physics on a dry test valley, and members were being solved with the average ground roughness instead of the value for each cell.

**10 — Next steps.** Add these, keep the existing ones:
- Re-run the drainage case one change at a time — affordable now that the GPU has cut the cost of a run.
- Sign the Windows installers, so first-run warnings go away.
- Publish a finished run from the app to a phone-viewable page, so judges can see results without touching the laptop *(designed, not yet built)*.

**11 — Resources section.** Add a card, first in the grid: **"Download for Windows"** — *"Installer for Windows 10/11, 64-bit, in a processor build and a GPU build."* → `(WINDOWS INSTALLER LINK)`. Keep the existing source-code, document and presentation cards. Under the grid, add two small muted lines: *"The installers are not code-signed yet — Windows will warn on first run."* and *"Flood maps and 3D terrain use online basemaps. Simulations themselves run with no internet once a data pack is imported."*

**Content rules — unchanged.** Use only the figures above; do not invent, round or extrapolate. Every speed-up keeps its grid size and member count; every run time keeps its member count and simulated duration. Never write "real-time". Do not call the system GPU-accelerated without saying it also runs on an ordinary processor. Simulated time and computing time stay separate. The 2D-to-SPH link is a one-way handoff, never "coupled". The project is validated against the Delft3D FM kernel; it is not Delft3D, and the Delft3D kernel is never bundled. Keep every CAPS placeholder exactly as written.

**When you are done,** list every value you changed as "section — old → new".

---

## Before you publish

- **`(WINDOWS INSTALLER LINK)`** has nowhere to point yet. Your CI builds both installers on every push to `main`, but they expire as artifacts after 30 days and there is no release automation. Push a `vX.Y.Z` tag, then attach both installers to a GitHub Release by hand — that gives you a permanent link for the site and answers the "judges can download it" requirement in one move.
- **The 14 s GPU figure.** The validation record does not restate the configuration for that run, so the prompt presents it beside the 2-member, 15-minute CPU run. Confirm they match before publishing, or drop the GPU number.
- **`DualSPHysics_v5.4/`** is in the repo and still appears in no document. If it is wired in, tell me what it does and I will write the entry — a named open-source SPH engine is worth showing, since the problem statement asks for SPH by name.
