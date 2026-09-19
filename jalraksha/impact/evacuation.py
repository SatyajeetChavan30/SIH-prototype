"""
Evacuation directives per gauge: EVACUATE, PREPARE, MONITOR, or NO_ARRIVAL.

This module is the ONE definition of how a gauge's hazard class and warning
lead time become a directive. FD2320 once had five definitions in this repo and
two live ones disagreed on real output (docs/validation_findings.md §10); a
directive table copied into the frontend or the dossier would repeat that. So
the service computes the directive here, stores it with the gauge row, and
every surface renders the stored payload, colours included.

Nothing here runs a solver. The inputs are what a finished run already reports
per gauge: peak depth, median arrival time, the boundary-proximity flag and the
note.

WHAT A DIRECTIVE IS NOT
-----------------------
It is a screening prompt ordered by hazard and warning time, not an evacuation
order. The thresholds below are chosen, not published, and every payload says
so (``thresholds_unvetted``). Three traps decide whether that is safe to show:

1. **No arrival is not safety.** ``arrival_time_s`` is null both when the flood
   never reached a gauge AND when the gauge lies outside the solver domain.
   Returning MONITOR for the second case would print reassurance where nothing
   was simulated. A null arrival therefore yields NO_ARRIVAL, which carries the
   gauge's note verbatim and is labelled "Not assessed", in grey.
2. **A near-boundary gauge is not a measurement.** Its depth is shaped by the
   transmissive outflow condition as well as by the flood. The directive is
   still issued, and ``near_boundary`` travels with it so the screen can say so.
3. **A minority arrival is not a median.** When fewer than half the ensemble
   members reached a gauge, the arrival and depth are one or two realisations.
   ``minority_arrival`` travels with the directive for the same reason.

No colour here is green. A directive is a prompt to act or to watch; none of
the four states means "safe", and the palette should not suggest one does.

WHY THE GATE IS A LABEL, NOT A REFUSAL
--------------------------------------
Quarantined regressions (natural_dam.py, fatality.py, damage.py) refuse to run
while unverified, because a wrong coefficient there silently changes a figure.
A directive has no figure to change: it orders gauges already on screen, and a
dashboard that refuses to order them protects nobody. So the gate here is
``DIRECTIVE_THRESHOLDS_VERIFIED = False``, echoed as ``thresholds_unvetted`` in
every payload together with the threshold values themselves, and the dashboard
renders a Caveat beside any directive that carries it. docs/DECISIONS.md §17.

Imports numpy and ``jalraksha.impact.hazard`` only. The hazard class comes from
``HazardClassifier.classify_depth_only`` rather than a new depth table: a gauge
reports a peak depth and no velocity, and a second band table is exactly how
the dashboard and the shapefile came to disagree about a 1.5 m-deep cell.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

import numpy as np

from jalraksha.impact.hazard import DEBRIS_FACTOR_DEFAULT, HazardClassifier, HazardLevel


class Directive(str, Enum):
    """The four directive states, strongest first."""

    EVACUATE = "evacuate"
    PREPARE = "prepare"
    MONITOR = "monitor"
    NO_ARRIVAL = "no_arrival"


# TODO: UNVETTED — docs/VERIFICATION_LOG.md row 39. Chosen for screening, not
# taken from published guidance. A wet gauge whose flood arrives sooner than
# this after the breach is escalated from PREPARE to EVACUATE. Two hours is a
# working figure for "less time than an organised evacuation of a riverside
# settlement plausibly needs"; no Indian or international source for that
# number has been transcribed.
DIRECTIVE_LEAD_TIME_S = 7200.0

# TODO: UNVETTED — row 39. The weakest FD2320 class that prompts any action. At
# LOW (HR >= 0 and wet above 5 cm), any gauge the flood actually wets gets at
# least PREPARE; a gauge that is reached but stays below the wet threshold gets
# MONITOR.
DIRECTIVE_HAZARD_FLOOR = HazardLevel.LOW

# TODO: UNVETTED — row 39. The class at which a gauge is told to evacuate
# whatever its lead time. FD2320 describes "significant" as danger for most
# people, which is the reason for choosing it; mapping that description to an
# evacuation threshold is a judgement, not a published rule.
EVACUATE_HAZARD_LEVEL = HazardLevel.SIGNIFICANT

DIRECTIVE_THRESHOLDS_VERIFIED = False
DIRECTIVE_THRESHOLDS_SOURCE = (
    "UNVETTED: chosen for screening, not from published guidance "
    "(docs/VERIFICATION_LOG.md row 39)"
)

# Rank of each FD2320 class, for ordering. DRY < LOW < ... < EXTREME.
_HAZARD_RANK = {
    HazardLevel.DRY: 0,
    HazardLevel.LOW: 1,
    HazardLevel.MODERATE: 2,
    HazardLevel.SIGNIFICANT: 3,
    HazardLevel.EXTREME: 4,
}

# Rendered from the payload, never from a stylesheet (the same route FD2320
# colours take). Every pair is >= 7:1 contrast (WCAG AAA), asserted by
# tests/test_evacuation.py. No green: see the module docstring.
DIRECTIVE_COLORS: Dict[Directive, Dict[str, str]] = {
    Directive.EVACUATE: {"bg": "#7f1d1d", "fg": "#ffffff"},
    Directive.PREPARE: {"bg": "#fff1d6", "fg": "#6b3a00"},
    Directive.MONITOR: {"bg": "#e3edf9", "fg": "#0d3a6e"},
    Directive.NO_ARRIVAL: {"bg": "#ececec", "fg": "#3d3d3d"},
}

DIRECTIVE_LABELS: Dict[Directive, str] = {
    Directive.EVACUATE: "Evacuate",
    Directive.PREPARE: "Prepare",
    Directive.MONITOR: "Monitor",
    # Not "safe", not "clear": nothing was assessed at this gauge.
    Directive.NO_ARRIVAL: "Not assessed",
}


def hazard_level_at_depth(depth_m: Optional[float]) -> Optional[HazardLevel]:
    """
    FD2320 class of a single peak depth, through the shared classifier.

    Depth-only (|V| = 0), because a gauge row carries no velocity. That
    under-states hazard where flow is fast, which ``classify_depth_only``
    documents; it is the same reduction the dashboard's gauge badge uses.

    Returns None for a missing or non-finite depth, so an unknown depth can
    never be read as DRY.
    """
    if depth_m is None:
        return None
    depth = float(depth_m)
    if not np.isfinite(depth):
        return None
    level = HazardClassifier().classify_depth_only(np.array([depth]))[0]
    return level


def _thresholds() -> Dict[str, Any]:
    return {
        "lead_time_s": DIRECTIVE_LEAD_TIME_S,
        "hazard_floor": DIRECTIVE_HAZARD_FLOOR.value,
        "evacuate_hazard_level": EVACUATE_HAZARD_LEVEL.value,
        "hazard_scheme": f"FD2320 depth-only (|V| = 0), debris factor {DEBRIS_FACTOR_DEFAULT}",
    }


def directive_for_gauge(
    hazard_level: Optional[HazardLevel],
    arrival_time_s: Optional[float],
    near_boundary: Optional[bool],
    note: Optional[str],
    *,
    minority_arrival: bool = False,
) -> Dict[str, Any]:
    """
    The directive for one gauge.

    Rules, first match wins:

    1. No arrival                              -> NO_ARRIVAL (note carried verbatim)
    2. Arrived, depth unknown                  -> PREPARE
    3. Class >= EVACUATE_HAZARD_LEVEL          -> EVACUATE
    4. Class >= floor and lead < LEAD_TIME     -> EVACUATE
    5. Class >= floor                          -> PREPARE
    6. Otherwise (reached but below wet)       -> MONITOR

    Monotonic by construction: raising the hazard class or shortening the lead
    time never moves a gauge to a weaker directive.

    Args:
        hazard_level: FD2320 class of the gauge's peak depth, or None when the
            depth is unknown (see ``hazard_level_at_depth``).
        arrival_time_s: Ensemble-median arrival after the breach (s), or None.
        near_boundary: The gauge's boundary-contamination flag, passed through.
        note: The gauge's note (no-arrival reason, minority arrival, ...).
        minority_arrival: True when fewer than half the members arrived.

    Returns:
        A JSON-serialisable dict; the colours and thresholds travel with it.
    """
    lead_time_s = None if arrival_time_s is None else float(arrival_time_s)

    if lead_time_s is None or not np.isfinite(lead_time_s):
        directive = Directive.NO_ARRIVAL
        lead_time_s = None
        # Not assessed means no class either. A no-arrival gauge's depth column
        # is often 0.0 rather than null, which would otherwise surface here as
        # "dry" - a reassurance the run never measured.
        hazard_level = None
        basis = note or "No arrival was recorded at this gauge."
    elif hazard_level is None:
        directive = Directive.PREPARE
        basis = "Flood arrival without a depth reading at this gauge."
    else:
        rank = _HAZARD_RANK[hazard_level]
        if rank >= _HAZARD_RANK[EVACUATE_HAZARD_LEVEL]:
            directive = Directive.EVACUATE
            basis = f"Peak hazard class {hazard_level.value}."
        elif rank >= _HAZARD_RANK[DIRECTIVE_HAZARD_FLOOR] and lead_time_s < DIRECTIVE_LEAD_TIME_S:
            directive = Directive.EVACUATE
            basis = (
                f"Peak hazard class {hazard_level.value}, arriving "
                f"{lead_time_s / 60.0:.0f} min after the breach."
            )
        elif rank >= _HAZARD_RANK[DIRECTIVE_HAZARD_FLOOR]:
            directive = Directive.PREPARE
            basis = f"Peak hazard class {hazard_level.value}."
        else:
            directive = Directive.MONITOR
            basis = "The flood reaches this gauge but stays below the wet threshold."

    return {
        "directive": directive.value,
        "label": DIRECTIVE_LABELS[directive],
        "color": dict(DIRECTIVE_COLORS[directive]),
        "hazard_level": None if hazard_level is None else hazard_level.value,
        "lead_time_s": lead_time_s,
        "basis": basis,
        "near_boundary": None if near_boundary is None else bool(near_boundary),
        "minority_arrival": bool(minority_arrival),
        "note": note,
        "thresholds_unvetted": not DIRECTIVE_THRESHOLDS_VERIFIED,
        "threshold_source": DIRECTIVE_THRESHOLDS_SOURCE,
        "thresholds": _thresholds(),
    }
