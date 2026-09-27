"""
Capture the five dashboard screenshots for the JalRaksha progress website.

Lives in progress_site_handoff/ (git-excluded). Adapted from
tools/sih-presentation/capture_dashboard.py: same headless Chrome + Selenium
approach, so the frames are files on disk at an exact pixel size and contain the
app viewport only (no taskbar, tabs, bookmarks bar or address bar).

Run from the repo root, with the API and the Vite dev server already running:

    python scripts/run_api.py                 (terminal 1)
    npm run dev --prefix frontend             (terminal 2)
    python progress_site_handoff/capture_site_screenshots.py   (terminal 3)

Writes into progress_site_handoff/screenshots/:
    dashboard-2d3d.png   1600 x 1000 (16:10)  hero
    dash-2d3d.png        1920 x 1080 (16:9)
    dash-ensemble.png    1920 x 1080
    dash-impact.png      1920 x 1080
    dash-validation.png  1920 x 1080
and prints, for each file, its size and any text on screen that should not be
published (user paths, e-mail addresses, the Earth Engine project id, tokens).

Run: bf0839d4af234b56b20612b43d3db413 — Khadakwasla, 500 x 400 km at 500 m,
96 h simulated, 40 members, SWE only, GPU (RUN_5_PROGRESS.md, "Completed runs").
The last keyframe (t = 96 h, largest wet extent) is shown.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

HERE = Path(__file__).resolve().parent
OUT = HERE / "screenshots"
BASE = "http://127.0.0.1:3000"
RUN_ID = "bf0839d4af234b56b20612b43d3db413"
URL = f"{BASE}/?run={RUN_ID}&frame=last"
MAX_BYTES = 1_500_000

# Text that must not appear in a published screenshot.
SENSITIVE = [
    (re.compile(r"[A-Za-z]:\\Users\\", re.I), "Windows user path"),
    (re.compile(r"/home/|/Users/"), "home-directory path"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "e-mail address"),
    (re.compile(r"sih-prototype-\d+"), "Earth Engine project id"),
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "Google API key"),
    (re.compile(r"eyJ[0-9A-Za-z_-]{20,}"), "token (JWT, e.g. Cesium Ion)"),
    (re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"), "GitHub token"),
]


def driver() -> webdriver.Chrome:
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--window-size=2000,1200")
    o.add_argument("--hide-scrollbars")
    o.add_argument("--force-device-scale-factor=1")
    # Cesium is WebGL; headless Chrome needs a software rasteriser for it.
    o.add_argument("--enable-unsafe-swiftshader")
    o.add_argument("--use-gl=angle")
    o.add_argument("--use-angle=swiftshader")
    return webdriver.Chrome(options=o)


def set_viewport(d, width: int, height: int) -> None:
    """Pin the page viewport to an exact size; the screenshot is the viewport."""
    d.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
    })


def wait_for_text(d, needle: str, timeout: float = 60.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if needle in d.find_element(By.TAG_NAME, "body").text:
            return True
        time.sleep(1.0)
    print(f"  ! timed out waiting for {needle!r}", file=sys.stderr)
    return False


def click(d, xpath: str, what: str, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        els = [e for e in d.find_elements(By.XPATH, xpath) if e.is_displayed()]
        if els:
            d.execute_script("arguments[0].click();", els[0])
            return True
        time.sleep(0.5)
    print(f"  ! could not find {what}", file=sys.stderr)
    return False


def click_tab(d, label: str) -> bool:
    # Tab pills carry a count chip for some tabs, so match the start of the text.
    xp = f'//button[@role="tab"][starts-with(normalize-space(.), "{label}")]'
    return click(d, xp, f"tab {label!r}")


def open_run(d, width: int, height: int) -> None:
    set_viewport(d, width, height)
    d.get(URL)
    wait_for_text(d, "Khadakwasla")
    time.sleep(12)  # keyframes, OSM tiles and Cesium terrain
    if click(d, '//button[normalize-space(.)="Catchment overview"]', "Catchment overview"):
        time.sleep(10)  # camera flight + terrain tiles


def scan(d) -> list[str]:
    text = d.find_element(By.TAG_NAME, "body").text
    hits = []
    for pattern, label in SENSITIVE:
        for m in pattern.finditer(text):
            hits.append(f"{label}: {m.group(0)!r}")
    return hits


def shoot(d, name: str, problems: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    d.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)
    path = OUT / name
    d.save_screenshot(str(path))
    size = path.stat().st_size
    try:
        from PIL import Image
        with Image.open(path) as im:
            dims = f"{im.width}x{im.height}"
            if size > MAX_BYTES:
                small = path.with_name(path.stem + "-compressed.png")
                im.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT) \
                  .save(small, optimize=True)
                print(f"    over 1.5 MB; compressed copy {small.name} "
                      f"({small.stat().st_size / 1e6:.2f} MB)")
    except ImportError:
        dims = "?"
    hits = scan(d)
    problems[name] = hits
    print(f"  wrote {path.name}  {dims}  {size / 1e6:.2f} MB"
          + ("" if not hits else "  !! SENSITIVE TEXT: " + "; ".join(hits)))
    return path


def caveats_disabled() -> bool:
    """True while the demo-recording kill switch in ui/index.jsx is in place.

    Commit 1cd138d added `return null;` at the top of `Caveat`, which hides every
    honesty label (synthetic strip, unvetted thresholds, boundary warnings,
    out-of-population regressions). A screenshot taken with it in place shows
    the product without its labels and must not be published.
    """
    ui = HERE.parent / "frontend" / "src" / "ui" / "index.jsx"
    src = ui.read_text(encoding="utf-8")
    body = src.split("export function Caveat", 1)[-1].split("export function", 1)[0]
    code = [ln.strip() for ln in body.splitlines()
            if ln.strip() and not ln.strip().startswith("//")]
    # The first statement after the signature must not be a bare `return null;`.
    for i, ln in enumerate(code):
        if ln.startswith("}) {"):
            return i + 1 < len(code) and code[i + 1] == "return null;"
    return "caveats/warnings hidden" in body


def main() -> None:
    if caveats_disabled():
        sys.exit("REFUSING: frontend/src/ui/index.jsx still has the Caveat kill switch "
                 "(`return null;` in Caveat). Remove those two lines, let Vite reload, "
                 "then run this again. Screenshots without the honesty labels must "
                 "not be published.")
    problems: dict[str, list[str]] = {}
    d = driver()
    try:
        print(f"hero 1600x1000: {URL}")
        open_run(d, 1600, 1000)
        shoot(d, "dashboard-2d3d.png", problems)

        print("gallery 1920x1080")
        open_run(d, 1920, 1080)
        shoot(d, "dash-2d3d.png", problems)

        for label, name in (("Ensemble", "dash-ensemble.png"),
                            ("Impact", "dash-impact.png")):
            if click_tab(d, label):
                time.sleep(5)
                shoot(d, name, problems)

        # The Validation tab is empty until "Run validation" is pressed: the
        # Ritter cross-check runs the real Delft3D FM kernel on this machine.
        if click_tab(d, "Validation"):
            time.sleep(2)
            click(d, '//button[contains(normalize-space(.), "Run validation") '
                     'or contains(normalize-space(.), "Re-check")]', "Run validation")
            wait_for_text(d, "RMSE", timeout=300)
            time.sleep(4)
            shoot(d, "dash-validation.png", problems)
    finally:
        d.quit()

    bad = {k: v for k, v in problems.items() if v}
    if bad:
        print("\nDO NOT PUBLISH until these are dealt with:")
        for k, v in bad.items():
            print(f"  {k}: {v}")
        sys.exit(1)
    print("\nNo sensitive text found in any frame.")


if __name__ == "__main__":
    main()
