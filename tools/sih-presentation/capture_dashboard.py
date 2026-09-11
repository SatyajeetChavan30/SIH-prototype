"""
Capture screenshots of the live JalRaksha dashboard for the SIH idea deck.

    python tools/sih-presentation/capture_dashboard.py

Requires the API (port 8000) and the Vite dev server (port 3000) to be running;
start them from .claude/launch.json. Writes PNGs into
tools/sih-presentation/assets/.

Headless Chrome is driven through Selenium rather than screenshotting the
in-app browser pane, because the deck needs the frames as files on disk at a
resolution that survives being placed on a 13.3 in slide.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

HERE = Path(__file__).resolve().parent
OUT = HERE / "assets"
URL = "http://localhost:3000"

# The Tehri SWE run whose exports the deck's numbers are quoted from. Keeping
# the screenshots and the figures on the same run is the whole point.
RUN_ID = "264734ee6d514589a046db7887847114"

WIDTH, HEIGHT = 1920, 1200


def driver():
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument(f"--window-size={WIDTH},{HEIGHT}")
    o.add_argument("--hide-scrollbars")
    o.add_argument("--force-device-scale-factor=1")
    # Cesium is WebGL; headless Chrome needs a software rasteriser for it.
    o.add_argument("--enable-unsafe-swiftshader")
    o.add_argument("--use-gl=angle")
    o.add_argument("--use-angle=swiftshader")
    return webdriver.Chrome(options=o)


def click_text(d, text, *, tag="button", timeout=10.0):
    """Click the first <tag> whose trimmed text equals `text`."""
    end = time.time() + timeout
    xp = f'//{tag}[normalize-space(text())="{text}"]'
    while time.time() < end:
        els = [e for e in d.find_elements(By.XPATH, xp) if e.is_displayed()]
        if els:
            d.execute_script("arguments[0].click();", els[0])
            return True
        time.sleep(0.4)
    print(f"  ! could not find {tag} {text!r}", file=sys.stderr)
    return False


def load_run(d, run_id):
    """Pick `run_id` in the run selector and press Load."""
    for sel in d.find_elements(By.TAG_NAME, "select"):
        values = [o.get_attribute("value") for o in sel.find_elements(By.TAG_NAME, "option")]
        if run_id in values:
            d.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                sel,
                run_id,
            )
            break
    else:
        print("  ! run selector did not offer the run id", file=sys.stderr)
        return False
    return click_text(d, "Load")


def shoot(d, name):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    d.save_screenshot(str(path))
    print(f"  wrote {path.relative_to(HERE.parent.parent)}")
    return path


def main() -> None:
    d = driver()
    try:
        print(f"loading {URL}")
        d.get(URL)
        time.sleep(6)

        print(f"loading run {RUN_ID}")
        load_run(d, RUN_ID)
        time.sleep(10)

        # Frame the 3D globe on the whole reach, then run the flood animation
        # far enough that the inundation is actually on screen, and pause.
        click_text(d, "Catchment overview")
        time.sleep(8)
        click_text(d, "Play")
        time.sleep(9)
        click_text(d, "Play")  # pause on a mid-flood frame
        time.sleep(3)
        shoot(d, "dash_workspace")

        for tab, name in [
            ("Ensemble", "dash_ensemble"),
            ("Impact", "dash_impact"),
            ("Gauges", "dash_gauges"),
        ]:
            print(f"tab {tab}")
            if click_text(d, tab):
                time.sleep(4)
                shoot(d, name)

        # The Validation tab renders empty until its button is pressed: the
        # Ritter cross-check spawns the real Delft3D FM kernel, so the panel
        # deliberately does not run it on page load.
        print("tab Validation (running the gates)")
        if click_text(d, "Validation"):
            time.sleep(2)
            click_text(d, "Run validation")
            for _ in range(60):
                time.sleep(5)
                body = d.find_element(By.TAG_NAME, "body").text
                if "Ritter" in body and "RMSE" in body:
                    break
            time.sleep(3)
            shoot(d, "dash_validation")
    finally:
        d.quit()


if __name__ == "__main__":
    main()
