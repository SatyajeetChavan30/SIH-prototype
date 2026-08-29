"""
Overflow and bounds check for a generated deck.

    python tools/sih-presentation/check_deck.py [deck.pptx]

Defaults to JalRaksha_SIH2026_Idea.pptx.

This is check_ppt.py's measurement engine pointed at an arbitrary file: it
measures every text frame with the real Windows font metrics via PIL, re-does
PowerPoint's word wrap, and reports any frame whose text is taller than its
shape. Anything reported as OVERFLOW will be visibly clipped in the PDF export.

There is no LibreOffice on this machine, so this is the cheap gate; the PDF
render from export_pdf.ps1 is the visual one.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import check_ppt  # noqa: E402  (needs the sys.path line above)


def main() -> None:
    deck = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "JalRaksha_SIH2026_Idea.pptx"
    if not deck.is_absolute():
        deck = (Path.cwd() / deck).resolve()
    if not deck.exists():
        raise SystemExit(f"no such deck: {deck}")
    print(f"checking {deck.name}")
    check_ppt.DECK = deck
    check_ppt.main()


if __name__ == "__main__":
    main()
