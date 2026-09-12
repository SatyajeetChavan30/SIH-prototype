# Updating the (PROJECT NAME) progress website

Two prompts. Use **Part 1** to collect what changed, then paste the filled block into **Part 2** to apply it to the site. If you already know what changed, skip straight to Part 2.

---

## Part 1 — Collect what changed

*Paste this into Claude (or any assistant with access to the project folder).*

> Read `docs/progress.md`, `docs/validation_findings.md`, `README.md` and the current test-suite count, and fill in the update block below for our progress website.
>
> Rules for filling it in:
> - Only include a figure if you can point to the line in a project file that states it. If something is claimed in one file and contradicted in another, say so instead of picking one.
> - Every simulation run figure must carry its study area, grid size, simulated duration and ensemble member count. Computing time is wall-clock time; never report it as simulated time.
> - Leave out design targets, planned features and anything not yet measured.
> - Output only the filled block, nothing else.
>
> ```
> LAST UPDATED DATE:
>
> HEADLINE STATS (exactly 4 — value + short label):
> 1.
> 2.
> 3.
> 4.
>
> DELIVERABLE STATUS CHANGES (only the ones that moved):
> D_ : old status -> new status — what exists today, one line
>
> NEW OR CHANGED MEASURED RESULTS:
> - scenario | study area | grid | simulated time | members | computing time | outcome
>
> NUMBERS TO CORRECT OR REMOVE (old value -> new value, or "remove, no longer supported"):
>
> NEW TIMELINE ENTRIES (newest first):
> - DD Mon YYYY — one line
>
> NEXT STEPS — now done:
> NEXT STEPS — newly added:
>
> NEW SCREENSHOTS (filename — caption):
>
> LINK CHANGES (GITHUB REPO URL / GITHUB RELEASE DOWNLOAD URL / DOCUMENT LINK / PPT LINK / DEMO VIDEO LINK):
> ```

---

## Part 2 — Apply the update to the site

*Paste this into the tool that built the site, with your filled block pasted at the bottom.*

> Update the (PROJECT NAME) progress website with the changes below.
>
> **Scope — what to touch**
> - Edit only the content file (`src/content.js` / `content.json`). Do not change the layout, palette, typography, components or section order. If a change genuinely needs a layout edit, tell me first instead of doing it.
> - Apply each change everywhere that value appears — a figure in the hero stat cards usually also appears in the results section, a caption or a footnote.
> - Update the "Last updated" date in the hero pill and the footer.
>
> **Section by section**
> - **Hero stats:** replace with the four headline stats given below, keeping the same wording style (value, then a short plain-language label).
> - **Progress table:** apply the deliverable status changes and rewrite the "What exists today" cell for each one that moved. Then recount the segmented progress bar and its label so "N of 12 deliverables working · M in progress" matches the table exactly.
> - **Measured results:** add new runs to the runs table, and update or remove the highlight cards. Keep study area, grid, simulated time, members and computing time together in every row.
> - **Timeline:** add the new entries at the top, newest first. Keep the existing entries unless I have said to remove one.
> - **Next steps:** move completed items out of the list (add them to the timeline with their date if one is given), and add the new ones.
> - **Screenshots:** add any new image slots with the given filename and caption; keep the light-blue placeholder box behaviour until the file exists.
> - **Links and placeholders:** update only the links listed. Every other CAPS placeholder in parentheses stays exactly as it is.
>
> **Content rules — unchanged from the original build**
> - Use only the facts and numbers in the block below. Do not invent, estimate, round up, extrapolate or "improve" any figure, and do not add statistics, testimonials, awards or logos.
> - Simulated time and computing time are different things; never mix them and never write "real-time forecast".
> - The link from the 2D solver to SPH is a one-way handoff — never "coupled" or "two-way".
> - Never say the project is Delft3D; it is validated against the Delft3D FM kernel.
> - No claims of validation against observed satellite flood maps, and no mention of InSAR or photogrammetry.
> - Plain, precise tone. No hype words.
>
> **When you are done**, list every value you changed as "section — old → new", and flag anything in my block that you could not place.
>
> Here is what changed:
>
> ```
> [paste the filled update block here]
> ```

---

## Before you publish

- The progress-bar count matches the number of "Done" rows in the table.
- Timeline dates run newest first, and the newest one matches the "Last updated" date.
- Every run figure still shows its study area, grid, simulated time and member count.
- No number appears on the page that is not in your source files.
- All four resource links still open (repo, release download, document, deck).
- Commit and push — GitHub Pages, Netlify and Vercel all rebuild from the push, so the live link updates on its own.
