"""
JalRaksha architecture diagrams -- draw.io edition, SIH 2026 PS 26161 (NTRO).

    python tools/build_architecture_drawio.py

Writes JalRaksha_Architecture_Diagrams.drawio at the repository root: the same
ten slides as tools/build_architecture_deck.py (the PowerPoint version), each
as its own editable page in one draw.io file. Open it at app.diagrams.net or
in the draw.io desktop app / VS Code extension.

Content, numbers and copy are ported straight from build_architecture_deck.py
and, transitively, from CLAUDE.md and tools/generate_architecture_diagrams.py
-- nothing here is invented. Same "no engineering syntax on a slide" rule
applies: this is a judge-facing artefact, not a technical schematic.
"""

from __future__ import annotations

import re
import xml.sax.saxutils as saxutils
from pathlib import Path

_FONT_TAG = re.compile(r'<font color="#([0-9A-Fa-f]{6})">')


def _xmlsafe_html(val: str) -> str:
    """The mxCell `value` is an XML attribute, so literal HTML tags built by the
    helpers below (raw <b>, <br>, <i>, <font>) must be entity-escaped even though
    they are meant to render as HTML once draw.io reads style=html=1 and
    un-escapes the value. Plain text inside those tags is already escaped via
    esc(), so this only needs to touch the tag delimiters themselves."""
    val = _FONT_TAG.sub(r'&lt;font color=&quot;#\1&quot;&gt;', val)
    for raw, safe in (("<br>", "&lt;br&gt;"), ("<b>", "&lt;b&gt;"), ("</b>", "&lt;/b&gt;"),
                      ("<i>", "&lt;i&gt;"), ("</i>", "&lt;/i&gt;"), ("</font>", "&lt;/font&gt;")):
        val = val.replace(raw, safe)
    return val

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "JalRaksha_Architecture_Diagrams.drawio"

SC = 100  # px per inch -- matches the 13.333in x 7.5in pptx canvas at 1333x750px

# --------------------------------------------------------------------------- #
# Palette -- identical hex values to tools/build_architecture_deck.py
# --------------------------------------------------------------------------- #

INK = "1F2937"
MUTED = "6B7280"
FAINT = "9CA3AF"
WHITE = "FFFFFF"
RULE = "D8DEE7"

SIH_BLUE = "0070C0"
NAVY = "14305A"

TEAL = "0D9488"
BLUE = "1E40AF"
SKY = "0284C7"
GREEN = "059669"
AMBER = "D97706"
ORANGE = "EA580C"
RED = "DC2626"
PURPLE = "7C3AED"
INDIGO = "4F46E5"
SLATE = "475569"


def _c(h: str) -> tuple[int, int, int]:
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def tint(h: str, amount: float) -> str:
    r, g, b = _c(h)
    m = lambda v: int(round(v + (255 - v) * amount))
    return f"{m(r):02X}{m(g):02X}{m(b):02X}"


def shade(h: str, amount: float) -> str:
    r, g, b = _c(h)
    m = lambda v: int(round(v * (1 - amount)))
    return f"{m(r):02X}{m(g):02X}{m(b):02X}"


def esc(s: str) -> str:
    return saxutils.escape(str(s))


def html_lines(*lines: str) -> str:
    return "<br>".join(esc(l) for l in lines if l != "")


# --------------------------------------------------------------------------- #
# Page: accumulates mxCell XML for one draw.io tab
# --------------------------------------------------------------------------- #


class Page:
    def __init__(self, name: str):
        self.name = name
        self.cells: list[str] = []
        self.n = 2

    def _id(self) -> str:
        i = self.n
        self.n += 1
        return f"p{abs(hash(self.name)) % 9973}_{i}"

    def rect(self, x, y, w, h, value="", *, fill=WHITE, stroke=None, font=INK, fs=8,
             bold=True, italic=False, align="center", valign="middle", rounded=True,
             arc=6, dashed=False, no_fill=False, shape=None):
        stroke = stroke if stroke is not None else fill
        fstyle = (1 if bold else 0) | (2 if italic else 0)
        style = (
            f"rounded={1 if rounded else 0};whiteSpace=wrap;html=1;"
            f"fillColor={'none' if no_fill else '#' + fill};strokeColor=#{stroke};"
            f"fontColor=#{font};fontSize={fs};fontStyle={fstyle};align={align};"
            f"verticalAlign={valign};arcSize={arc};spacing=4;"
        )
        if dashed:
            style += "dashed=1;"
        if shape:
            style += shape + ";"
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="{_xmlsafe_html(value)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry"/></mxCell>'
        )
        return cid

    def ellipse(self, x, y, w, h, value="", *, fill=WHITE, stroke=None, font=WHITE, fs=8, bold=True):
        stroke = stroke or fill
        style = (f"ellipse;whiteSpace=wrap;html=1;fillColor=#{fill};strokeColor=#{stroke};"
                 f"fontColor=#{font};fontSize={fs};fontStyle={1 if bold else 0};align=center;verticalAlign=middle;")
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="{_xmlsafe_html(value)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry"/></mxCell>'
        )
        return cid

    def diamond(self, cx, cy, w, h, value="", *, fill=AMBER, fs=6.5):
        style = (f"rhombus;whiteSpace=wrap;html=1;fillColor=#{fill};strokeColor=#{WHITE};"
                 f"fontColor=#{WHITE};fontSize={fs};fontStyle=1;align=center;verticalAlign=middle;")
        value = html_lines(*value.split("\n"))
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="{_xmlsafe_html(value)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{cx - w / 2:.0f}" y="{cy - h / 2:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry"/></mxCell>'
        )
        return cid

    def actor(self, cx, y, name, role, *, accent=SKY):
        style = f"shape=actor;whiteSpace=wrap;html=1;fillColor=#{accent};strokeColor=none;"
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{cx - 30:.0f}" y="{y:.0f}" width="60" height="60" as="geometry"/></mxCell>'
        )
        self.rect(cx - 72, y + 64, 144, 46, html_lines(f"<b>{esc(name)}</b>", role),
                   fill=WHITE, stroke=WHITE, font=INK, fs=6.6, align="center", rounded=False)

    def edge(self, x1, y1, x2, y2, *, color=SLATE, w=1.2, dashed=False, head=True):
        style = f"html=1;strokeColor=#{color};strokeWidth={w};endArrow={'block' if head else 'none'};startArrow=none;rounded=0;"
        if dashed:
            style += "dashed=1;"
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" style="{style}" edge="1" parent="1">'
            f'<mxGeometry relative="1" as="geometry">'
            f'<mxPoint x="{x1:.0f}" y="{y1:.0f}" as="sourcePoint"/>'
            f'<mxPoint x="{x2:.0f}" y="{y2:.0f}" as="targetPoint"/>'
            f'</mxGeometry></mxCell>'
        )
        return cid

    def zone(self, x, y, w, h, label, accent, *, wash=0.93):
        self.rect(x, y, w, h, "", fill=tint(accent, wash), stroke=accent, rounded=True, arc=3)
        tag_w = min(w - 30, 7 * len(label) + 24)
        self.rect(x + 14, y - 12, tag_w, 24, esc(label), fill=accent, stroke=accent,
                   font=WHITE, fs=7.6, rounded=True, arc=30)

    def node(self, x, y, w, h, title, desc, accent, *, tsize=8.6, dsize=6.3):
        lines = [f"<b>{esc(title)}</b>"]
        if desc:
            lines.append("<br>".join(esc(l) for l in desc.split("\n")))
        self.rect(x, y, w, h, "<br>".join(lines), fill=accent, stroke=accent, font=WHITE,
                   fs=tsize, align="center", valign="middle")

    def panel(self, x, y, w, h, title, lines, accent, *, tsize=9.0, lsize=6.4, bullet="▪ "):
        body = "<br>".join(esc((bullet + l) if bullet else l) for l in lines)
        val = f'<b><font color="#{shade(accent, 0.25)}">{esc(title)}</font></b><br>{body}'
        self.rect(x, y, w, h, val, fill=tint(accent, 0.93), stroke=accent, font=INK, fs=lsize,
                   align="left", valign="top", rounded=True, arc=5)

    def note(self, x, y, w, h, text, *, accent=AMBER, size=6.4, align="center"):
        self.rect(x, y, w, h, esc(text), fill=tint(accent, 0.90), stroke=accent,
                   font=shade(accent, 0.40), fs=size, italic=True, align=align, valign="middle",
                   rounded=True, arc=10)

    def chip(self, x, y, w, h, title, desc, accent, *, tsize=6.8, dsize=5.6):
        self.rect(x, y, w, h, esc(title), fill=accent, stroke=accent, font=WHITE, fs=tsize, rounded=True, arc=16)
        self.rect(x, y + h + 4, w, 60, "<br>".join(esc(l) for l in desc.split("\n")),
                   fill=WHITE, stroke=WHITE, font=MUTED, fs=dsize, align="center", valign="top", rounded=False)

    def table(self, x, y, col_w, row_h, headers, rows, accent, *, hsize=6.8, csize=6.2):
        cx = x
        for hdr, w in zip(headers, col_w):
            self.rect(cx, y, w, row_h, html_lines(hdr), fill=accent, stroke=accent, font=WHITE, fs=hsize, rounded=False)
            cx += w + 4
        for ri, row in enumerate(rows):
            cx = x
            yy = y + (ri + 1) * (row_h + 4)
            for ci, (cell, w) in enumerate(zip(row, col_w)):
                wash = 0.96 if ri % 2 == 0 else 0.90
                fill = tint(accent, wash) if ci else tint(accent, 0.86)
                self.rect(cx, yy, w, row_h, esc(cell), fill=fill, stroke=tint(accent, 0.55), font=INK,
                          fs=csize, bold=(ci == 0), align="left" if ci == 0 else "center", rounded=False)
                cx += w + 4

    def chevron(self, x, y, w, h, text, *, fill=SIH_BLUE, size=8.0):
        cid = self._id()
        style = (f"shape=step;perimeter=stepPerimeter;whiteSpace=wrap;html=1;fillColor=#{fill};"
                 f"strokeColor=#{fill};fontColor=#{WHITE};fontSize={size};fontStyle=1;")
        self.cells.append(
            f'<mxCell id="{cid}" value="{esc(text)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry"/></mxCell>'
        )

    def textbox(self, x, y, w, h, text, *, size=8.0, color=INK, bold=False, italic=False, align="left"):
        self.rect(x, y, w, h, html_lines(text) if "\n" not in text else "<br>".join(esc(l) for l in text.split("\n")),
                   fill=WHITE, stroke=WHITE, font=color, fs=size, bold=bold, italic=italic, align=align, valign="top", rounded=False)

    def frame(self, prs_title, prs_subtitle, prs_footer, number):
        """Slide chrome: wordmark, title, SIH tag, footer bar -- matches new_slide() in the pptx script."""
        self.rect(0, 0, int(13.333 * SC), int(7.5 * SC), "", fill=WHITE, stroke=WHITE, rounded=False)
        self.rect(22, 14, 130, 34, html_lines("JalRaksha"), fill=NAVY, stroke=NAVY, font=WHITE, fs=11, rounded=True, arc=40)
        self.textbox(22, 50, 160, 20, "PS 26161 · NTRO", size=6.2, color=MUTED)
        self.textbox(170, 8, 955, 44, prs_title, size=20, color=INK, bold=True, align="left")
        self.textbox(170, 50, 955, 22, prs_subtitle, size=8.2, color=MUTED, italic=True)
        self.rect(1135, 12, 176, 44,
                   html_lines("SMART INDIA", "HACKATHON 2026"), fill=WHITE, stroke=WHITE,
                   font=SIH_BLUE, fs=8, align="right", valign="top", rounded=False)
        self.rect(0, 716, int(13.333 * SC), 34, esc(prs_footer), fill=SIH_BLUE, stroke=SIH_BLUE,
                   font=WHITE, fs=8, align="left", rounded=False)
        self.rect(1260, 716, 50, 34, str(number), fill=SIH_BLUE, stroke=SIH_BLUE, font=WHITE, fs=8.5,
                   align="right", rounded=False)

    def xml(self, page_id: str) -> str:
        body = "\n".join(self.cells)
        return (
            f'<diagram id="{page_id}" name="{esc(self.name)}">'
            f'<mxGraphModel dx="1400" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
            f'arrows="1" fold="1" page="1" pageScale="1" pageWidth="{int(13.333 * SC)}" pageHeight="{int(7.5 * SC)}" '
            f'math="0" shadow="0">'
            f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
            f"{body}"
            f'</root></mxGraphModel></diagram>'
        )


def IN(v: float) -> float:
    return v * SC


# =========================================================================== #
# 1 -- HOW THE SYSTEM IS BUILT
# =========================================================================== #

def slide_architecture() -> Page:
    s = Page("1. System Architecture")
    s.frame("HOW THE SYSTEM IS BUILT",
            "JalRaksha is a layered system -- each layer does one job and hands its result to the next",
            "Anyone can run it from a browser. Everything underneath is free, open and cached for offline use.", 1)

    s.zone(IN(0.22), IN(0.98), IN(5.55), IN(1.12), "LAYER 1 · WHAT USERS SEE", TEAL)
    s.node(IN(0.38), IN(1.16), IN(2.55), IN(0.78), "Interactive Dashboard",
           "Opens in any browser. Maps, charts,\n3D globe, download buttons.", TEAL, tsize=8.2)
    s.node(IN(3.06), IN(1.16), IN(2.55), IN(0.78), "Command Line",
           "For batch runs and automation.\nOne instruction, full report.", SLATE, tsize=8.2)

    s.zone(IN(6.02), IN(0.98), IN(7.09), IN(1.12), "LAYER 2 · THE BRAIN THAT COORDINATES EVERYTHING", BLUE)
    s.node(IN(6.18), IN(1.16), IN(3.35), IN(0.78), "Central Coordinator",
           "Takes the request, checks the inputs are sensible,\nstarts the work, hands back the answer.", BLUE, tsize=8.2)
    s.node(IN(9.66), IN(1.16), IN(3.29), IN(0.78), "Background Worker",
           "Runs the heavy calculation on its own so the\ndashboard never freezes -- it answers in 0.21 s.", ORANGE, tsize=8.2)

    s.note(IN(0.34), IN(2.16), IN(5.30), IN(0.28), "No coding needed. A dam safety officer picks a dam and presses one button.")
    s.note(IN(6.28), IN(2.16), IN(6.60), IN(0.28),
           "Like a front desk plus a workshop: the desk answers instantly, the work happens out back.", accent=SKY)

    s.zone(IN(0.22), IN(2.72), IN(12.89), IN(4.30), "LAYER 3 · THE SIMULATION ENGINE -- where the flood is actually modelled", INDIGO)

    row1 = [
        (0.38, 2.30, "Dam Break Model", "How the wall gives way:\nbreach width, how fast it\nopens, peak water released.\nFrom published dam-safety\nresearch, not guesswork.", ORANGE),
        (2.80, 2.78, "Flood Spread Calculator", "Follows the water across the\nland second by second at 30-metre\ndetail. Slows it through forest,\nspeeds it over concrete. Adjusts\nits own step size to stay stable.", BLUE),
        (5.70, 2.24, "Uncertainty Analysis", "Runs 30 variations with\ndifferent breach sizes.\nReports best case, worst\ncase and most likely -- never\none false number.", TEAL),
        (8.06, 2.36, "Near-Dam 3D Physics", "Violent water right at the\nwall: overtopping, splashing.\nCovers about 600 m for 15 s.\nAdds detail; it does not\nreplace the main model.", PURPLE),
        (10.54, 2.44, "Independent Cross-Check", "The same textbook case run\nthrough Delft3D FM, a real\nDeltares kernel. Both engines\nland within 3 cm of each other.\nProof, not a claim.", shade(PURPLE, 0.22)),
    ]
    for x, w, title, desc, accent in row1:
        s.node(IN(x), IN(3.04), IN(w), IN(1.16), title, desc, accent, tsize=8.0, dsize=5.9)
    s.textbox(IN(7.58), IN(2.86), IN(0.86), IN(0.16), "one-way", size=5.4, color=PURPLE, italic=True, bold=True)

    row2 = [
        (0.38, 3.02, "Terrain Preparation", "Downloads satellite ground-height data, stitches the tiles together,\ncleans the artefacts, finds the dam wall, and maps what covers the\nland -- forest, town, farmland -- because that sets how fast water runs.", GREEN),
        (3.54, 2.94, "Flood Impact Assessment", "Turns depth into consequence: ankle-deep, waist-deep, two to five\nmetres, above five metres. Estimates buildings exposed and people\nat risk using published government formulas.", RED),
        (6.62, 3.08, "Quality Gates", "Four mandatory checks run before any result is released. Still water\nstays still. No water is lost. No impossible depths. Answers match\nthe textbook case. Fail any one and the result is blocked outright.", GREEN),
        (9.84, 3.27, "Report & Map Generator", "Flood maps that open in standard mapping software, Google Earth\noverlays, inundation boundaries, time-lapse animations and\nspreadsheets -- all geographically referenced at 30-metre detail.", INDIGO),
    ]
    for x, w, title, desc, accent in row2:
        s.node(IN(x), IN(4.30), IN(w), IN(1.00), title, desc, accent, tsize=8.0, dsize=5.8)

    s.zone(IN(0.22), IN(5.66), IN(12.89), IN(1.36), "LAYER 4 · DATA SOURCES -- every one free, open and legal to redistribute", NAVY, wash=0.93)
    sources = [
        (0.38, 1.94, "Satellite Ground Height", "European Space Agency,\n30-metre detail, worldwide,\nstored once and reused.", NAVY),
        (2.44, 2.02, "India's Dam Register", "The government list of\n5,000-plus large dams with\nheight, storage and river.", SLATE),
        (4.58, 2.14, "Satellite Flood Imagery", "Radar flood detection plus\npopulation density. Rejected\nautomatically if too poor.", GREEN),
        (6.84, 1.96, "Land Cover Map", "Forest, city or farmland at\n10-metre detail -- this decides\nhow fast the water travels.", SLATE),
        (8.92, 2.06, "Pre-loaded Dam Profiles", "Tehri at 260 m and 3,540 MCM,\nKhadakwasla at 33 m, plus their\ndownstream towns.", NAVY),
        (11.10, 1.87, "Offline Cache", "Fetched once, then held on\ndisk. Demo day needs no\nnetwork at all.", SLATE),
    ]
    for x, w, title, desc, accent in sources:
        s.chip(IN(x), IN(5.92), IN(w), IN(0.42), title, desc, accent)
    s.note(IN(4.10), IN(6.98), IN(5.20), IN(0.26), "No commercial licence, no field survey, no specialist -- total data cost is zero.")
    return s


# =========================================================================== #
# 2 -- HOW IT WORKS, STEP BY STEP
# =========================================================================== #

def slide_how_it_works() -> Page:
    s = Page("2. How It Works")
    s.frame("HOW IT WORKS -- STEP BY STEP",
            "From four simple inputs to a complete flood risk report, in minutes rather than weeks.",
            "Seven steps. The officer performs step one. The system performs the other six.", 2)

    s.panel(IN(0.22), IN(0.94), IN(4.10), IN(1.44), "Built-in uncertainty, not a single guess", [
        "Thirty variations run with different breach sizes",
        "Reports the fifth and ninety-fifth percentile arrival band",
        "Best case, worst case and most likely -- stated together",
        "This is how real engineering reports risk",
    ], TEAL)
    s.panel(IN(4.52), IN(0.94), IN(4.28), IN(1.44), "Checked against an independent engine", [
        "The same textbook case run through Delft3D FM as well",
        "A real Deltares kernel, not a lookalike of our own",
        "Our answer 0.0317 m error, theirs 0.0349 m",
        "The two engines agree to within 0.0294 m",
    ], PURPLE)
    s.panel(IN(9.00), IN(0.94), IN(4.11), IN(1.44), "Why the speed matters", [
        "Today: weeks of specialist setup and licensed software",
        "Today: field survey costs before a single map exists",
        "JalRaksha: four inputs, free data, a full run in 47 seconds",
        "Any trained officer can run it -- and it runs offline",
    ], AMBER)

    steps = [
        (0.22, 1.76, "1", "Pick a Dam", "Choose from the list, or type in\nposition, height and storage.\nFour numbers, nothing more.",
         "No specialist needed -- the numbers are public.", SLATE),
        (2.10, 1.72, "2", "Get the Terrain", "Satellite ground-height data\narrives at 30-metre detail and\nis cached for offline reuse.",
         "Like fetching a 3D photograph of the valley.", NAVY),
        (3.94, 1.80, "3", "Prepare the Land", "Smooth the artefacts, locate the\ndam wall, and label what covers\nthe ground downstream.",
         "Forest slows water down; concrete speeds it up.", GREEN),
        (5.86, 1.74, "4", "Model the Break", "Work out how wide the breach\ngrows, how quickly, and how much\nwater is released at the peak.",
         "Formulas drawn from decades of dam-safety study.", ORANGE),
        (7.72, 1.86, "5", "Simulate the Flood", "Follow the water downstream\nsecond by second across the whole\nlandscape -- the core calculation.",
         "The heavy step, and still only tens of seconds.", BLUE),
        (9.70, 1.72, "6", "Assess the Impact", "Which areas flood, how deep,\nwhen the water arrives, and how\nmany people are exposed.",
         "Depth becomes consequence, in plain numbers.", RED),
        (11.54, 1.57, "7", "Publish Results", "Maps, Google Earth overlays,\ncharts and downloadable reports,\nready for the people who decide.",
         "One run produces the whole package.", INDIGO),
    ]
    for x, w, num, title, desc, aside, accent in steps:
        s.node(IN(x), IN(2.72), IN(w), IN(1.62), f"{num}. {title}", desc, accent, tsize=8.6, dsize=6.0)
        s.textbox(IN(x), IN(4.44), IN(w), IN(0.66), aside, size=5.9, color=shade(AMBER, 0.35), italic=True, align="center")
    for i in range(len(steps) - 1):
        x_end = steps[i][0] + steps[i][1]
        x_next = steps[i + 1][0]
        s.edge(IN(x_end), IN(3.53), IN(x_next), IN(3.53), color=SKY, w=1.8)

    s.zone(IN(0.22), IN(5.44), IN(12.89), IN(1.56), "WHAT COMES OUT AT THE END", INDIGO, wash=0.94)
    outs = [
        (0.42, 2.42, "Arrival Time Map", "When the water reaches each\ntown -- the number that decides an evacuation order.", RED),
        (3.00, 2.36, "Inundation Envelope", "The outer boundary of the flood, with a\nfifth-to-ninety-fifth percentile band around it.", TEAL),
        (5.52, 2.30, "Depth and Hazard Bands", "Four hazard classes, from ankle-deep\nthrough to above five metres.", ORANGE),
        (7.98, 2.44, "People and Buildings Exposed", "Counts drawn from satellite population\nand building data, with the source stated.", INDIGO),
        (10.58, 2.53, "Evidence Pack", "The quality-gate results and the\nindependent cross-check, attached to\nevery single run.", GREEN),
    ]
    for x, w, title, desc, accent in outs:
        s.node(IN(x), IN(5.72), IN(w), IN(1.14), title, desc, accent, tsize=7.8, dsize=5.8)
    return s


# =========================================================================== #
# 3 -- USER JOURNEY (SWIMLANES)
# =========================================================================== #

def slide_user_journey() -> Page:
    s = Page("3. User Journey")
    s.frame("USER JOURNEY -- WHO DOES WHAT",
            "Four lanes. The officer clicks; everything to the right of that happens on its own.",
            "The person operating the system makes five decisions. The system takes roughly twenty thousand.", 3)

    lanes = [
        (0.22, 3.06, "THE OFFICER", "A dam-safety or disaster-management officer. No coding background.", SKY),
        (3.44, 3.22, "THE COORDINATOR", "Receives the request, checks it, and decides what work to start.", TEAL),
        (6.80, 3.10, "THE ENGINE", "Does the mathematics: breach, flood spread, impact.", BLUE),
        (10.04, 3.07, "THE REPORTER", "Turns results into maps, charts and files people can act on.", INDIGO),
    ]
    for x, w, name, role, accent in lanes:
        s.zone(IN(x), IN(1.28), IN(w), IN(5.62), name, accent, wash=0.96)
        s.textbox(IN(x + 0.10), IN(1.46), IN(w - 0.20), IN(0.34), role, size=6.2, color=MUTED, italic=True)

    rows = [
        (("Opens the dashboard in a browser", "Nothing to install."),
         ("Answers in under a fifth of a second", "Even mid-run."),
         ("Idle, waiting for work", ""),
         ("Shows the run picker", "Any past run loads instantly.")),
        (("Picks a dam -- say Tehri, 260 m", "Or types four numbers."),
         ("Checks the inputs are physically sensible", "Rejects nonsense early."),
         ("Loads terrain, or fetches it once", "yes -> straight through · no -> fetched once, then kept"),
         ("Draws the study area on the map", "Confirms before running.")),
        (("Keeps the defaults, presses Run", "One button."),
         ("Starts a separate worker for the heavy part", "The page stays alive."),
         ("Models the breach, then the flood spread", "Thirty variations."),
         ("Streams live progress, member by member", "Never a frozen bar.")),
        (("Watches the arrival times appear", "Town by town."),
         ("Saves each result as it lands", "Nothing is lost on a crash."),
         ("Scores impact: depth, hazard, people exposed", "Published formulas."),
         ("Plots the flood on a 2D map and a 3D globe", "Both stay loaded.")),
        (("Downloads the pack for the district authority", "Ready to circulate."),
         ("Attaches the quality-gate evidence", "Every run, no exceptions."),
         ("Optionally runs the near-dam 3D detail", "About 600 m, 15 s."),
         ("Exports maps, overlays, charts, spreadsheets", "Standard formats.")),
    ]
    y_positions = [1.82, 2.86, 3.90, 4.90, 5.86]
    heights = [0.86, 0.86, 0.82, 0.80, 0.90]
    lane_x = [0.36, 3.58, 6.94, 10.18]
    lane_w = [2.78, 2.94, 2.82, 2.79]
    lane_c = [SKY, TEAL, BLUE, INDIGO]

    for ri, row in enumerate(rows):
        y = y_positions[ri]
        h = heights[ri]
        for ci, (text, aside) in enumerate(row):
            accent = lane_c[ci]
            val = f"<b>{esc(text)}</b>" + (f"<br><i>{esc(aside)}</i>" if aside else "")
            s.rect(IN(lane_x[ci]), IN(y), IN(lane_w[ci]), IN(h), val, fill=tint(accent, 0.86), stroke=accent,
                   font=shade(accent, 0.40), fs=6.6, rounded=True, arc=8)
        mid = y + h / 2
        s.edge(IN(lane_x[0] + lane_w[0]), IN(mid), IN(lane_x[1]), IN(mid), color=SLATE, w=0.9)
        s.edge(IN(lane_x[1] + lane_w[1]), IN(mid), IN(lane_x[2]), IN(mid), color=SLATE, w=1.4 if ri == 2 else 0.9)
        s.edge(IN(lane_x[2] + lane_w[2]), IN(mid), IN(lane_x[3]), IN(mid), color=SLATE, w=0.9)

    for ci in range(4):
        cx = lane_x[ci] + lane_w[ci] / 2
        for ri in range(len(rows) - 1):
            s.edge(IN(cx), IN(y_positions[ri] + heights[ri]), IN(cx), IN(y_positions[ri + 1]), color=FAINT, w=0.7)

    s.diamond(IN(6.73), IN(3.29), IN(0.86), IN(0.60), "Terrain\nalready\nhere?", fill=AMBER, fs=5.6)
    return s


# =========================================================================== #
# 4 -- TECHNOLOGY STACK
# =========================================================================== #

def slide_tech_stack() -> Page:
    s = Page("4. Technology Stack")
    s.frame("WHAT IT IS BUILT WITH",
            "Every piece is open-source and free to use. Nothing here carries a licence fee.",
            "Total software licence cost: zero. Total field-survey cost: zero.", 4)

    columns = [
        (0.22, 2.42, "FLOOD SIMULATION", "The mathematics that moves the water", TEAL, [
            ("NumPy and SciPy", "the numerical core"),
            ("Numba", "compiles the hot loops, roughly 100x"),
            ("PySPH", "particle physics near the dam"),
            ("Matplotlib", "scientific plotting"),
            ("Delft3D FM", "Deltares kernel, 2026.01 build"),
        ]),
        (2.80, 2.62, "MAPS AND GEOGRAPHY", "Reads satellite data, writes map files", GREEN, [
            ("Rasterio", "reads satellite ground-height data"),
            ("GeoPandas", "geographic boundaries and joins"),
            ("Shapely", "flood-zone shapes"),
            ("PyProj", "converts between coordinate systems"),
            ("xarray", "time-series flood data"),
            ("Earth Engine", "radar flood and population layers"),
        ]),
        (5.58, 2.44, "SERVER AND API", "Coordinates the work, never blocks the page", SKY, [
            ("FastAPI", "the web service"),
            ("Uvicorn", "runs it"),
            ("Pydantic", "validates every input"),
            ("SQLite", "keeps the run history"),
            ("Celery", "optional distributed worker"),
        ]),
        (8.20, 2.50, "WHAT PEOPLE SEE", "Maps, globe and charts in the browser", PURPLE, [
            ("React", "the interface"),
            ("Vite", "instant reloads while building"),
            ("Leaflet", "the 2D flood map"),
            ("CesiumJS", "the 3D globe with real terrain"),
            ("Recharts", "arrival-time and depth charts"),
            ("ParaView", "cinematic flood animation"),
        ]),
        (10.88, 2.23, "PACKAGE AND PROVE", "Ships anywhere, tests every change", ORANGE, [
            ("Docker", "the whole system, one command"),
            ("Pytest", "the automated test suite"),
            ("Ruff", "keeps the code clean"),
            ("GitHub Actions", "re-runs the gates on every change"),
        ]),
    ]
    for x, w, title, blurb, accent, items in columns:
        s.node(IN(x), IN(0.98), IN(w), IN(0.74), title, blurb, accent, tsize=8.6, dsize=6.0)
        y = 1.84
        for name, purpose in items:
            val = f"<b>{esc(name)}</b><br><font color=\"#{MUTED}\">{esc(purpose)}</font>"
            s.rect(IN(x + 0.03), IN(y), IN(w - 0.06), IN(0.52), val, fill=tint(accent, 0.94), stroke=tint(accent, 0.55),
                   font=shade(accent, 0.35), fs=6.6, align="left", valign="middle", rounded=True, arc=8)
            y += 0.60

    s.note(IN(10.91), IN(4.40), IN(2.17), IN(1.22),
           "The one line item a conventional study cannot avoid -- the licensed modelling package -- "
           "simply has no equivalent on this slide.")

    s.zone(IN(0.22), IN(5.72), IN(12.89), IN(1.28), "WHERE THE DATA COMES FROM -- free, open, and cached so demo day needs no network", NAVY, wash=0.94)
    ext = [
        (0.40, 2.16, "Copernicus Ground Height", "European Space Agency · 30-metre detail", NAVY),
        (2.70, 2.02, "Earth Engine Imagery", "Radar flood extent and population density", GREEN),
        (4.86, 1.92, "ESA Land Cover", "Forest, town or farmland at 10 metres", SLATE),
        (6.92, 2.10, "Delft3D FM", "Deltares, Netherlands · independent check", PURPLE),
        (9.16, 2.06, "CWC Dam Register", "The official Indian list, 5,000-plus dams", NAVY),
        (11.36, 1.61, "Local Cache", "Fetched once, then offline", SLATE),
    ]
    for x, w, title, desc, accent in ext:
        val = f"<b>{esc(title)}</b><br><font color=\"#{MUTED}\">{esc(desc)}</font>"
        s.rect(IN(x), IN(5.98), IN(w), IN(0.72), val, fill=tint(accent, 0.88), stroke=accent, font=shade(accent, 0.35),
               fs=6.4, align="left", valign="middle", rounded=True, arc=6)
    return s


# =========================================================================== #
# 5 -- USE CASE
# =========================================================================== #

def slide_use_case() -> Page:
    s = Page("5. Use Case")
    s.frame("WHO USES IT, AND WHAT FOR",
            "Four kinds of user inside the country, four data services outside it, twelve things the system does.",
            "One system, four audiences: the operator, the emergency planner, the researcher and the policy maker.", 5)

    people = [
        (0.92, 1.20, "Dam Safety Officer", "Central Water Commission · watches dam health"),
        (0.92, 2.62, "Emergency Manager", "District and national authority · plans the evacuation"),
        (0.92, 4.04, "Researcher / Engineer", "Validates the model, runs comparative studies"),
        (0.92, 5.46, "Policy Maker", "State or centre · decides where the safety budget goes"),
    ]
    for cx, y, name, role in people:
        s.actor(IN(cx), IN(y), name, role)

    s.rect(IN(2.32), IN(1.02), IN(7.74), IN(5.92), "", fill=tint(SKY, 0.975), stroke=SKY, rounded=True, arc=3)
    s.rect(IN(4.42), IN(0.90), IN(3.54), IN(0.30), "EVERYTHING INSIDE THIS BOX IS JALRAKSHA", fill=SKY, stroke=SKY,
           font=WHITE, fs=7.4, rounded=True, arc=30)

    left = [
        (2.60, 3.18, 0.86, "Choose a dam and set the failure scenario", TEAL),
        (2.66, 3.06, 0.84, "Run a full flood simulation -- minutes, not weeks", BLUE),
        (2.58, 3.30, 0.88, "Run thirty what-if variations for an honest range", TEAL),
        (2.62, 3.22, 0.86, "Read the flood on a 2D map and on a 3D globe", INDIGO),
        (2.68, 3.02, 0.84, "Download the pack for the district authority", INDIGO),
        (2.60, 3.14, 0.86, "Get arrival times for every downstream town", RED),
    ]
    right = [
        (6.44, 3.14, 0.86, "Check answers against the known exact solution", GREEN),
        (6.38, 3.32, 0.88, "Cross-check against the independent Delft3D engine", PURPLE),
        (6.42, 3.24, 0.86, "Estimate the population exposed, from satellite data", RED),
        (6.50, 3.04, 0.84, "Estimate damage to buildings and to life", RED),
        (6.46, 3.10, 0.84, "Run the detailed 3D physics right at the wall", PURPLE),
        (6.40, 3.26, 0.88, "Rank several dams against each other by priority", GREEN),
    ]
    ys = [1.14, 2.11, 3.08, 4.05, 5.02, 5.99]
    for i, (x, w, h, text, accent) in enumerate(left):
        s.ellipse(IN(x), IN(ys[i]), IN(w), IN(h), esc(text), fill=tint(accent, 0.80), stroke=accent, font=shade(accent, 0.35), fs=6.5)
    for i, (x, w, h, text, accent) in enumerate(right):
        drop = 0.06 if (i % 2 and i < len(right) - 1) else 0.0
        s.ellipse(IN(x), IN(ys[i] + drop), IN(w), IN(h), esc(text), fill=tint(accent, 0.80), stroke=accent, font=shade(accent, 0.35), fs=6.5)

    services = [
        (10.42, 2.48, 1.22, "Copernicus Ground Height", "30-metre satellite elevation", NAVY),
        (10.42, 2.62, 2.62, "Earth Engine", "Radar flood extent, population", GREEN),
        (10.42, 2.55, 4.06, "Delft3D FM", "Independent verification engine", PURPLE),
        (10.42, 2.44, 5.48, "CWC Dam Register", "Official Indian dam records", NAVY),
    ]
    for x, w, y, name, desc, accent in services:
        val = f"<b>{esc(name)}</b><br><font color=\"#{MUTED}\">{esc(desc)}</font>"
        s.rect(IN(x), IN(y), IN(w), IN(0.72), val, fill=tint(accent, 0.88), stroke=accent, font=shade(accent, 0.35),
               fs=6.6, align="left", valign="middle", rounded=True, arc=6)
        s.edge(IN(x), IN(y + 0.36), IN(9.70), IN(y + 0.22), color=FAINT, w=0.7, head=False, dashed=True)

    for cx, y, _, _ in people:
        s.edge(IN(cx + 0.60), IN(y + 0.30), IN(2.62), IN(y + 0.22), color=FAINT, w=0.7, head=False, dashed=True)

    s.textbox(IN(10.42), IN(6.42), IN(2.62), IN(0.52),
              "Outside services are read, never written to. Nothing leaves the machine the system runs on.",
              size=6.0, color=MUTED, italic=True)
    return s


# =========================================================================== #
# 6 -- COMPONENT MAP
# =========================================================================== #

def slide_component_map() -> Page:
    s = Page("6. Component Map")
    s.frame("WHAT EACH PART DOES",
            "Six working parts and three supporting ones. Arrows show which way information travels.",
            "Each part depends only on the parts to its left, so any one of them can be replaced on its own.", 6)

    s.rect(IN(5.02), IN(0.96), IN(3.30), IN(0.52), "JALRAKSHA · THE WHOLE SYSTEM", fill=SKY, stroke=SKY, font=WHITE, fs=10, rounded=True, arc=20)

    parts = [
        (0.22, 2.06, "Flood Simulation Engine", BLUE,
         "The mathematical core. Follows the water across the terrain step by step, using equations settled in hydraulic engineering.",
         ["The stepping loop, timestep by timestep", "Flood-front tracking -- where the water actually goes",
          "Wet-and-dry handling at the flood edge", "Runs across every processor core available"]),
        (2.42, 2.18, "Terrain and Dam Break", GREEN,
         "Prepares the digital landscape, then models how the wall gives way -- how wide, how quickly, how much water is released.",
         ["Terrain smoothing and artefact cleaning", "Breach growth from published dam-safety work",
          "Study-area definition around the dam", "Ground cover mapped to how fast water flows"]),
        (4.78, 2.10, "Impact and Risk", RED,
         "Turns depth into consequence: which areas, how deep, how many people, and what it is likely to cost.",
         ["Four hazard classes, ankle-deep to above five metres", "Building damage from published damage curves",
          "Loss-of-life estimates from the standard tables", "Population exposed, read from satellite data"]),
        (7.06, 2.14, "Near-Dam 3D Physics", PURPLE,
         "Optional detail for the violent water right at the wall. It adds resolution; it never replaces the main simulation.",
         ["Hand-off from the flood solver, one direction only", "A 3D domain roughly 600 metres across",
          "Particle-based water, about 15 seconds of it", "Overtopping and splash behaviour at the crest"]),
        (9.38, 2.02, "Quality Assurance", GREEN,
         "Automated proof that must pass before a result is released. Four checks. Fail one and nothing is published.",
         ["Still water must stay still", "No water may be created or lost",
          "No impossible depths anywhere in the grid", "The answer must match the independent engine"]),
        (11.62, 1.49, "Reports and Maps", INDIGO,
         "Everything a decision maker actually receives.",
         ["Flood depth maps for standard mapping tools", "Boundary shapes for planning software",
          "Google Earth overlays", "Time-lapse animation frames", "Spreadsheets of arrival times"]),
    ]
    for x, w, name, accent, blurb, items in parts:
        s.edge(IN(6.67), IN(1.48), IN(x + w / 2), IN(1.86), color=FAINT, w=0.8, head=False)
        s.node(IN(x), IN(1.86), IN(w), IN(0.58), name, "", accent, tsize=8.2)
        s.textbox(IN(x + 0.02), IN(2.50), IN(w - 0.04), IN(0.58), blurb, size=5.7, color=MUTED, italic=False)
        y = 3.12
        for it in items:
            s.rect(IN(x), IN(y), IN(w), IN(0.44), esc(it), fill=tint(accent, 0.95), stroke=tint(accent, 0.6),
                   font=INK, fs=6.0, bold=False, align="left", valign="middle", rounded=True, arc=6)
            y += 0.50

    s.textbox(IN(0.22), IN(5.62), IN(6.02), IN(0.24), "The one rule the whole map obeys", size=8.4, color=MUTED, bold=True)
    s.note(IN(0.22), IN(5.94), IN(6.02), IN(1.04),
           "A part may only depend on the parts to its left. That is why the near-dam 3D physics can be switched "
           "off entirely without touching anything else, and why the reporting stage can be rewritten without "
           "going near the mathematics. It is also what keeps each part testable on its own.", align="left")

    s.textbox(IN(6.52), IN(5.62), IN(3.00), IN(0.24), "Supporting services", size=8.4, color=MUTED, bold=True)
    support = [
        (6.52, 2.06, "Settings Loader", "Reads the run settings and\nchecks them before anything starts", SLATE),
        (8.72, 2.14, "Dam Profile Library", "Tehri, Khadakwasla and their\ndownstream towns, ready to run", NAVY),
        (11.02, 2.09, "Offline Cache", "Holds everything downloaded so\nthe next run needs no network", SLATE),
    ]
    for x, w, name, desc, accent in support:
        val = f"<b>{esc(name)}</b><br>" + "<br>".join(f'<font color="#{MUTED}">{esc(l)}</font>' for l in desc.split("\n"))
        s.rect(IN(x), IN(5.94), IN(w), IN(1.04), val, fill=tint(accent, 0.90), stroke=accent, font=shade(accent, 0.35),
               fs=6.8, align="left", valign="middle", rounded=True, arc=6)
    return s


# =========================================================================== #
# 7 -- DATA FLOW
# =========================================================================== #

def slide_data_flow() -> Page:
    s = Page("7. Data Flow")
    s.frame("FROM RAW DATA TO A DECISION",
            "Three stages. Collect once, simulate on demand, then publish something a district officer can act on.",
            "Stage one happens once per dam. Stages two and three happen every time somebody asks a question.", 7)

    s.chevron(IN(0.22), IN(0.96), IN(3.20), IN(0.34), "STAGE 1 · COLLECT AND PREPARE", fill=NAVY, size=8.0)
    s.textbox(IN(3.56), IN(1.00), IN(5.40), IN(0.26),
              "Runs once per dam, then never again -- the results are cached on disk.", size=6.6, color=MUTED, italic=True)
    stage1 = [
        (0.22, 2.40, "Fetch the Terrain", "Satellite ground-height tiles at\n30-metre detail, free from the\nEuropean Space Agency.", NAVY),
        (2.78, 2.56, "Stitch and Clean", "Several tiles merged into one\nseamless surface, with cliff and\nwater-body artefacts removed.", TEAL),
        (5.50, 2.34, "Label the Ground", "Forest, town or farmland -- this\nis what sets how much the land\nslows the water down.", GREEN),
        (8.00, 2.42, "Define the Study Area", "Draw the box around the dam,\nin metres rather than degrees,\non an even calculation grid.", SLATE),
        (10.58, 2.53, "Locate the Wall", "Pin down exactly where the dam\nsits and where the breach would\nopen. Everything keys off this.", SLATE),
    ]
    for x, w, title, desc, accent in stage1:
        s.node(IN(x), IN(1.42), IN(w), IN(0.92), title, desc, accent, tsize=7.8, dsize=5.8)
    for i in range(len(stage1) - 1):
        s.edge(IN(stage1[i][0] + stage1[i][1]), IN(1.88), IN(stage1[i + 1][0]), IN(1.88), color=SKY, w=1.6)
    s.edge(IN(5.10), IN(2.34), IN(5.10), IN(2.72), color=AMBER, w=2.2)
    s.textbox(IN(5.30), IN(2.38), IN(6.60), IN(0.28),
              "terrain grid + breach position + ground-roughness map -> handed to the simulation",
              size=6.2, color=shade(AMBER, 0.35), italic=True)

    s.chevron(IN(0.22), IN(2.80), IN(3.20), IN(0.34), "STAGE 2 · SIMULATE", fill=BLUE, size=8.0)
    s.textbox(IN(3.56), IN(2.84), IN(6.20), IN(0.26),
              "The whole of this stage completes in about 47 seconds for a full Tehri run.", size=6.6, color=MUTED, italic=True)
    stage2 = [
        (0.22, 2.32, "Model the Failure", "Breach width, how fast it opens,\nand the peak water released.\nThirty variations, not one.", ORANGE),
        (2.70, 2.62, "Spread the Water", "Every cell of the landscape,\nsecond by second, downstream.\nThe core of the whole system.", BLUE),
        (5.48, 2.30, "Sweep the Uncertainty", "Different breach sizes give\ndifferent outcomes. The answer\nis a band, not a point.", TEAL),
        (7.94, 2.46, "Time the Arrivals", "When does the water reach each\ntown? This is the number an\nevacuation order depends on.", INDIGO),
        (10.56, 2.55, "Optional 3D Detail", "Violent water at the wall itself.\nAbout 600 metres, 15 seconds.\nIt can never reach a town.", PURPLE),
    ]
    for x, w, title, desc, accent in stage2:
        s.node(IN(x), IN(3.26), IN(w), IN(0.92), title, desc, accent, tsize=7.8, dsize=5.8)
    for i in range(len(stage2) - 1):
        s.edge(IN(stage2[i][0] + stage2[i][1]), IN(3.72), IN(stage2[i + 1][0]), IN(3.72), color=SKY, w=1.6)
    s.edge(IN(5.10), IN(4.18), IN(5.10), IN(4.56), color=AMBER, w=2.2)
    s.textbox(IN(5.30), IN(4.22), IN(6.80), IN(0.28),
              "maximum depth + arrival time + the percentile band -> handed to the reporting stage",
              size=6.2, color=shade(AMBER, 0.35), italic=True)

    s.chevron(IN(0.22), IN(4.64), IN(3.20), IN(0.34), "STAGE 3 · PUBLISH", fill=INDIGO, size=8.0)
    s.textbox(IN(3.56), IN(4.68), IN(6.60), IN(0.26),
              "Nothing reaches this stage until all four quality gates have passed.", size=6.6, color=MUTED, italic=True)
    stage3 = [
        (0.22, 2.52, "Score the Impact", "How deep in each area, how many\npeople exposed, and the likely\ndamage -- with the source stated.", RED),
        (2.90, 2.38, "Draw the Flood Maps", "Colour-coded depth maps that open\nin any standard mapping tool, plus\nGoogle Earth overlays.", INDIGO),
        (5.44, 2.30, "Render the Animation", "Time-lapse of the flood spreading,\nfor briefings and for public\nawareness material.", SLATE),
        (7.90, 2.44, "Fill the Dashboard", "Maps, globe, charts, gauge traces\nand every download, live in the\nbrowser. Nothing to install.", SKY),
        (10.50, 2.61, "Attach the Evidence", "The four gate results and the\nindependent cross-check travel\nwith the report, every time.", GREEN),
    ]
    for x, w, title, desc, accent in stage3:
        s.node(IN(x), IN(5.10), IN(w), IN(0.92), title, desc, accent, tsize=7.8, dsize=5.8)

    s.note(IN(0.22), IN(6.24), IN(6.40), IN(0.56),
           "The one-way arrow matters. The near-dam 3D physics reads the flood solver's output and refines it. "
           "It never feeds back. Anyone claiming a two-way coupling here would be overstating what was built.",
           accent=PURPLE, align="left")
    s.note(IN(6.86), IN(6.24), IN(6.25), IN(0.56),
           "Stage one is the reason this works offline. Once a dam's terrain has been fetched, "
           "the entire pipeline runs with the network unplugged -- which is the assumption demo day is built on.",
           accent=GREEN, align="left")
    return s


# =========================================================================== #
# 8 -- IMPACT AND COMPARISON
# =========================================================================== #

def slide_impact() -> Page:
    s = Page("8. Why It Matters")
    s.frame("WHY IT MATTERS",
            "India has more than five thousand large dams, many of them ageing. Today only a handful ever get studied.",
            "The point is not a better flood model. The point is that every dam can be screened, not just the funded ones.", 8)

    s.rect(IN(0.22), IN(0.96), IN(12.89), IN(0.62),
           "A conventional dam-break study takes <b>weeks</b> of specialist time and licensed software, so it is only "
           "commissioned for the dams somebody has already worried about.<br>"
           "JalRaksha completes the same screening in <b>minutes</b>, from free satellite data -- which changes who "
           "gets screened, not just how fast.",
           fill=tint(BLUE, 0.90), stroke=BLUE, font=INK, fs=9, align="left", valign="middle", rounded=True, arc=5)

    cards = [
        (0.22, 3.16, 1.66, "SAVES LIVES", GREEN, [
            "Arrival times per town -- the number that sets an evacuation order",
            "Flood extent showing which areas to clear, and in what order",
            "Population exposed, estimated from satellite data",
            "Works with the network unplugged, when it matters most",
        ]),
        (3.52, 3.02, 1.52, "SAVES MONEY", AMBER, [
            "No software licence to buy -- every component is open",
            "No field survey needed before the first map exists",
            "Minutes per dam instead of weeks",
            "Run by a trained officer, not a hired specialist",
        ]),
        (6.68, 3.30, 1.72, "HONEST BY DESIGN", TEAL, [
            "Reports a range, never a single falsely precise number",
            "Poor satellite imagery is refused, not quietly used",
            "Four quality gates block a bad result rather than flagging it",
            "Every limitation is stated on the report itself",
        ]),
        (10.12, 2.99, 1.58, "INDEPENDENTLY CHECKED", PURPLE, [
            "Matched against Delft3D FM on the same textbook case",
            "Our error 0.0317 m, theirs 0.0349 m",
            "Both engines agree to within 0.0294 m",
            "Built on two decades of published dam-safety research",
        ]),
    ]
    for x, w, h, title, accent, lines in cards:
        s.panel(IN(x), IN(1.76), IN(w), IN(h), title, lines, accent, tsize=9.4, lsize=6.4)

    s.textbox(IN(0.22), IN(3.62), IN(6.00), IN(0.26), "How that compares with current practice", size=10, color=INK, bold=True)
    s.table(
        IN(0.22), IN(3.96), [IN(2.82), IN(4.66), IN(5.35)], IN(0.34),
        ["What you need", "How it is done today", "How JalRaksha does it"],
        [
            ["Time to a first answer", "Weeks of specialist setup", "Minutes -- pick a dam and press run"],
            ["Data you must buy", "Licensed elevation data plus a field survey", "None. Free satellite data, cached locally"],
            ["Independent verification", "Rarely available, rarely published", "Cross-checked against Delft3D FM, published here"],
            ["How uncertainty is shown", "A single number, with no band around it", "Thirty runs -- best, worst and most likely"],
            ["Poor satellite imagery", "Used anyway, because there is nothing else", "Refused automatically below the quality threshold"],
            ["Network on the day", "Required -- the tools are cloud-hosted", "Not required. Everything runs from cache"],
        ],
        SKY, hsize=7.2, csize=6.4,
    )

    s.note(IN(0.22), IN(6.58), IN(6.30), IN(0.44),
           "Refusing a bad input is a feature, not a gap. At Khadakwasla the radar scene scored 0.486 against a "
           "0.5 threshold and was rejected outright -- no substitute overlay was drawn in its place.",
           accent=RED, align="left")
    s.note(IN(6.76), IN(6.58), IN(6.35), IN(0.44),
           "None of the right-hand column is aspiration. Every row in it is running today, on the machine this "
           "deck was built on, and the numbers quoted came off that machine.",
           accent=GREEN, align="left")
    return s


# =========================================================================== #
# 9 -- VALIDATION
# =========================================================================== #

def slide_validation() -> Page:
    s = Page("9. Validation")
    s.frame("HOW WE KNOW THE ANSWERS ARE RIGHT",
            "Four checks that must pass, plus a comparison against an engine we did not write.",
            "If a check fails, the result is blocked -- not flagged, not footnoted. Blocked.", 9)

    s.rect(IN(0.22), IN(0.96), IN(12.89), IN(0.46),
           "No result is ever shown until all four checks pass. A warning label on a wrong flood map is worse "
           "than no map at all, so a failed check stops the run.",
           fill=tint(RED, 0.86), stroke=RED, font=shade(RED, 0.30), fs=8.6, align="center", valign="middle", rounded=True, arc=8)

    tests = [
        (0.22, 3.16, "CHECK 1 · STILL WATER STAYS STILL", GREEN, [
            "Water in a bowl with nothing pushing it must not drift.",
            "Measured drift: 0.0000000000000598 metres per second.",
            "The threshold allows a thousand times more than that.",
            "Result: passes, with room to spare.",
        ]),
        (3.54, 3.06, "CHECK 2 · NO WATER APPEARS OR VANISHES", GREEN, [
            "Total water in the simulation must stay constant.",
            "Measured loss across a thousand steps: 0.000000 per cent.",
            "Exact to the limit of what the machine can represent.",
            "Result: passes.",
        ]),
        (6.82, 3.10, "CHECK 3 · NO IMPOSSIBLE NUMBERS", GREEN, [
            "Depth can never be negative, and nothing may go undefined.",
            "The flood edge, where water meets dry ground, is the hard part.",
            "Every cell across every test case stayed physical.",
            "Result: passes on all cases.",
        ]),
        (10.14, 2.97, "CHECK 4 · MATCHES THE KNOWN ANSWER", GREEN, [
            "A textbook dam-break has an exact answer written in 1892.",
            "Exact depth at the wall: 4.444 metres.",
            "Our answer: 4.532 metres -- an error of about 3 centimetres.",
            "Result: passes, well inside tolerance.",
        ]),
    ]
    for x, w, title, accent, lines in tests:
        s.panel(IN(x), IN(1.68), IN(w), IN(1.20), title, lines, accent, tsize=7.8, lsize=6.2, bullet="")

    s.textbox(IN(0.22), IN(3.06), IN(8.00), IN(0.28), "And then checked against an engine we did not write",
              size=11, color=shade(PURPLE, 0.20), bold=True)

    s.panel(IN(0.22), IN(3.42), IN(4.62), IN(1.98), "What was actually done", [
        "The same textbook case was run twice -- once through our engine, once through Delft3D FM.",
        "Delft3D FM is made by Deltares, an independent Dutch institute. Governments use it for real flood studies.",
        "It is a genuine Deltares kernel running here, 2026.01 build -- not a re-implementation of ours.",
        "Both runs were scored against the exact mathematical answer, over the interior of the domain.",
        "Neither engine was tuned to match the other.",
    ], PURPLE, tsize=8.8, lsize=6.4)

    s.note(IN(0.22), IN(5.52), IN(4.62), IN(0.72),
           "Ten metres of water, a flat frictionless bed, ten-metre cells, forty seconds of flow, and the three "
           "outermost cells at each end trimmed before scoring. Anyone can repeat it.", accent=PURPLE, align="left")

    s.textbox(IN(5.06), IN(3.44), IN(4.00), IN(0.26), "The result", size=8.8, color=shade(PURPLE, 0.25), bold=True)
    s.table(
        IN(5.06), IN(3.78), [IN(2.75), IN(1.85), IN(1.55), IN(1.78)], IN(0.36),
        ["Engine", "Error against the exact answer", "Depth at the wall", "Verdict"],
        [
            ["JalRaksha", "0.0317 m", "4.532 m", "passes"],
            ["Delft3D FM (Deltares)", "0.0349 m", "4.515 m", "passes"],
            ["The exact answer (1892)", "reference", "4.444 m", "reference"],
        ],
        PURPLE, hsize=6.6, csize=6.4,
    )
    s.note(IN(5.06), IN(5.36), IN(5.30), IN(0.88),
           "The two engines agree with each other to 0.0294 metres. Ten metres of water standing behind the wall, "
           "forty seconds of flow, and the whole disagreement between them is under three centimetres.",
           accent=GREEN, align="left")

    s.ellipse(IN(10.62), IN(5.32), IN(2.49), IN(0.96),
              f"<b>4 / 4 GATES PASSED</b><br><i>and within 3 cm of Delft3D FM</i>",
              fill=tint(GREEN, 0.86), stroke=GREEN, font=shade(GREEN, 0.30), fs=10)

    s.rect(IN(0.22), IN(6.44), IN(12.89), IN(0.56),
           "<b>In plain words:</b> the flood predictions here are as accurate as the software governments already trust, "
           "and we can show the working. What we do not claim is equally clear -- at 30-metre terrain detail, "
           "trust the arrival times and the flood boundary; treat any single depth reading as indicative.",
           fill=tint(AMBER, 0.90), stroke=AMBER, font=INK, fs=8.4, align="left", valign="middle", rounded=True, arc=5)
    return s


# =========================================================================== #
# 10 -- DEPLOYMENT, INNOVATION, ROADMAP
# =========================================================================== #

def slide_roadmap() -> Page:
    s = Page("10. Deployment & Roadmap")
    s.frame("HOW IT RUNS, WHAT IS NEW, WHAT COMES NEXT",
            "Packaged to run on one laptop or one server, with no network and no licence.",
            "Everything on the left of this slide already works. The right-hand column is what we build after the hackathon.", 10)

    s.textbox(IN(0.22), IN(0.94), IN(3.60), IN(0.26), "How it runs", size=11, color=INK, bold=True)
    stack = [
        (1.26, "A Browser", "Chrome, Firefox or Edge. Nothing to install,\nnothing to configure.", SKY),
        (2.28, "The Web Service", "Answers in about a fifth of a second, even\nwhile a simulation is running.", TEAL),
        (3.30, "The Simulation Worker", "A separate process, so a heavy calculation\ncan never freeze the page.", ORANGE),
        (4.32, "Local Storage", "Results and cached terrain, held on the\nmachine's own disk.", SLATE),
        (5.34, "One Container", "The whole system packaged so it starts\nanywhere with a single command.", INDIGO),
    ]
    for y, name, desc, accent in stack:
        val = f"<b>{esc(name)}</b><br>" + "<br>".join(f'<font color="#{MUTED}">{esc(l)}</font>' for l in desc.split("\n"))
        s.rect(IN(0.22), IN(y), IN(3.60), IN(0.88), val, fill=tint(accent, 0.90), stroke=accent, font=shade(accent, 0.35),
               fs=7.6, align="left", valign="middle", rounded=True, arc=6)
    for i in range(len(stack) - 1):
        s.edge(IN(2.02), IN(stack[i][0] + 0.88), IN(2.02), IN(stack[i + 1][0]), color=FAINT, w=0.9)

    s.textbox(IN(4.06), IN(0.94), IN(5.20), IN(0.26), "What is genuinely new here", size=11, color=INK, bold=True)
    innovations = [
        (4.06, 2.52, 1.26, "Verified, not asserted", "Cross-checked against a real Deltares kernel\nrunning on this machine -- demonstrated, not claimed.", PURPLE),
        (6.72, 2.54, 1.26, "A range, not a number", "Thirty variations every run, reported as a\npercentile band around the arrival time.", TEAL),
        (4.06, 2.52, 2.36, "Bad data is refused", "A radar scene below the quality threshold is\nrejected outright. No synthetic stand-in is ever drawn.", RED),
        (6.72, 2.54, 2.36, "Honest progress", "The dashboard reports which member of thirty is\nsolving, rather than a bar that sits still.", SKY),
        (4.06, 2.52, 3.46, "Runs with no network", "Everything cached after the first fetch, because\ndemo-day connectivity cannot be assumed.", ORANGE),
        (6.72, 2.54, 3.46, "Near-dam 3D detail", "Particle physics at the wall, handed off in one\ndirection only -- about 600 metres, 15 seconds.", PURPLE),
        (4.06, 2.52, 4.56, "Replaceable parts", "Any component can be swapped without touching\nthe others, because dependencies run one way.", INDIGO),
        (6.72, 2.54, 4.56, "Zero licence cost", "Every component is open-source. There is nothing\nto buy before a state can use it.", GREEN),
    ]
    for x, w, y, title, desc, accent in innovations:
        val = f"<b>{esc(title)}</b><br>" + "<br>".join(esc(l) for l in desc.split("\n"))
        s.rect(IN(x), IN(y), IN(w), IN(1.00), val, fill=tint(accent, 0.92), stroke=accent, font=shade(accent, 0.35),
               fs=7.2, align="left", valign="middle", rounded=True, arc=6)

    s.textbox(IN(9.52), IN(0.94), IN(3.60), IN(0.26), "Where it goes next", size=11, color=INK, bold=True)
    road = [
        (1.26, 2.20, "DONE", GREEN, [
            "The flood simulation engine", "The dashboard, eight working tabs",
            "All four quality gates passing", "The independent Delft3D cross-check",
            "Thirty-member uncertainty sweep", "Offline-first caching", "Single-command container",
        ]),
        (3.60, 1.40, "NOW", AMBER, [
            "Impact analysis, final pass", "Near-dam 3D integration polish", "Demo-day rehearsal and fallbacks",
        ]),
        (5.14, 1.28, "NEXT", SKY, [
            "Screen all five thousand registered dams", "Hand results to district authorities directly",
            "Alerts to the phones of people downstream", "A hosted service for states without hardware",
            "Feed Tier-2 detailed studies where warranted",
        ]),
    ]
    for y, h, label, accent, items in road:
        val = f"<b><font color=\"#{WHITE}\">{esc(label)}</font></b><br>" + "<br>".join("– " + esc(it) for it in items)
        s.rect(IN(9.52), IN(y), IN(3.59), IN(h), val, fill=tint(accent, 0.94), stroke=accent, font=INK, fs=6.6,
               align="left", valign="top", rounded=True, arc=5)
        s.rect(IN(9.64), IN(y - 0.11), IN(0.80), IN(0.24), esc(label), fill=accent, stroke=accent, font=WHITE, fs=7.6, rounded=True, arc=30)

    s.note(IN(4.06), IN(5.76), IN(5.20), IN(1.22),
           "The framing matters as much as the software. JalRaksha is a first-pass screening instrument: it tells a "
           "state which of its dams deserve a full surveyed study, and in what order. It does not replace that study, "
           "and the reports say so on their own face rather than in a footnote.", align="left")
    s.note(IN(0.22), IN(6.32), IN(3.60), IN(0.66),
           "One laptop is enough to run all of this. Nothing here assumes a data centre, a licence server "
           "or a working connection.", accent=SKY, align="left")
    s.note(IN(9.52), IN(6.56), IN(3.59), IN(0.42),
           "None of the last block has been started. It is listed so the boundary between what runs "
           "and what is planned stays visible.", accent=SLATE)
    return s


# =========================================================================== #

def main() -> None:
    builders = [
        slide_architecture, slide_how_it_works, slide_user_journey, slide_tech_stack,
        slide_use_case, slide_component_map, slide_data_flow, slide_impact,
        slide_validation, slide_roadmap,
    ]
    pages = [b() for b in builders]
    diagrams = "\n".join(p.xml(f"page{i}") for i, p in enumerate(pages, start=1))
    doc = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<mxfile host="app.diagrams.net" agent="JalRaksha build_architecture_drawio.py" version="24.0.0">\n'
        f"{diagrams}\n"
        f"</mxfile>\n"
    )
    OUTPUT.write_text(doc, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}  ({len(pages)} pages)")


if __name__ == "__main__":
    main()
