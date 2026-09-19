"""
Evacuation directives: ordering, the three traps, and the labels.

The threshold VALUES are unvetted (docs/VERIFICATION_LOG.md row 39) and will be
revised, so these tests assert ORDERING and behaviour rather than numbers, the
stance test_terrain.py takes for the WorldCover roughness legend. A revised
lead time or hazard floor must not require rewriting this file; a directive
that gets weaker as the hazard grows must fail it.

Offline by construction: jalraksha.impact imports nothing from jalraksha.gee.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from jalraksha.impact import evacuation
from jalraksha.impact.evacuation import (
    DIRECTIVE_COLORS,
    Directive,
    directive_for_gauge,
    hazard_level_at_depth,
)
from jalraksha.impact.hazard import HazardClassifier, HazardLevel

# Strongest first; a directive's strength is its position counted from the end.
_STRENGTH = {
    Directive.NO_ARRIVAL.value: -1,  # not on the scale at all
    Directive.MONITOR.value: 0,
    Directive.PREPARE.value: 1,
    Directive.EVACUATE.value: 2,
}

_LEVELS = [
    HazardLevel.DRY, HazardLevel.LOW, HazardLevel.MODERATE,
    HazardLevel.SIGNIFICANT, HazardLevel.EXTREME,
]
_LEAD_TIMES_S = [0.0, 60.0, 900.0, 3600.0, 7199.0, 7200.0, 7201.0, 21600.0, 86400.0]


def _strength(level, lead_s):
    return _STRENGTH[directive_for_gauge(level, lead_s, False, None)["directive"]]


class TestOrdering:
    def test_more_hazard_never_downgrades_a_directive(self):
        for lead in _LEAD_TIMES_S:
            strengths = [_strength(level, lead) for level in _LEVELS]
            assert strengths == sorted(strengths), (lead, strengths)

    def test_less_lead_time_never_downgrades_a_directive(self):
        for level in _LEVELS:
            # Lead times descending: the directive may only strengthen.
            strengths = [_strength(level, lead) for lead in sorted(_LEAD_TIMES_S, reverse=True)]
            assert strengths == sorted(strengths), (level, strengths)

    def test_the_scale_is_actually_used(self):
        """Ordering holds trivially for a constant; make sure it is not one."""
        seen = {
            directive_for_gauge(level, lead, False, None)["directive"]
            for level, lead in itertools.product(_LEVELS, _LEAD_TIMES_S)
        }
        assert {Directive.MONITOR.value, Directive.PREPARE.value,
                Directive.EVACUATE.value} <= seen


class TestNoArrivalIsNotSafety:
    OUTSIDE = "Gauge lies outside the solver domain; increase domain_radius_km"

    def test_a_null_arrival_never_yields_monitor(self):
        for level in [None, *_LEVELS]:
            payload = directive_for_gauge(level, None, False, self.OUTSIDE)
            assert payload["directive"] == Directive.NO_ARRIVAL.value

    def test_the_note_is_carried_verbatim(self):
        payload = directive_for_gauge(None, None, None, self.OUTSIDE)
        assert payload["note"] == self.OUTSIDE
        assert payload["basis"] == self.OUTSIDE

    def test_it_reads_as_not_assessed_in_grey(self):
        payload = directive_for_gauge(None, None, None, None)
        assert payload["label"] == "Not assessed"
        assert payload["color"] == DIRECTIVE_COLORS[Directive.NO_ARRIVAL]
        assert payload["lead_time_s"] is None

    def test_a_zero_depth_without_arrival_is_not_reported_as_dry(self):
        """Measured: no-arrival gauges carry max_depth_m 0.0, not null."""
        payload = directive_for_gauge(hazard_level_at_depth(0.0), None, False, None)
        assert payload["directive"] == Directive.NO_ARRIVAL.value
        assert payload["hazard_level"] is None

    def test_a_non_finite_arrival_is_treated_as_none(self):
        """The solver's never-wet sentinel is inf; it is not an arrival time."""
        payload = directive_for_gauge(HazardLevel.EXTREME, float("inf"), False, None)
        assert payload["directive"] == Directive.NO_ARRIVAL.value

    def test_an_unknown_depth_is_never_read_as_dry(self):
        payload = directive_for_gauge(None, 1800.0, False, None)
        assert payload["directive"] == Directive.PREPARE.value
        assert hazard_level_at_depth(None) is None
        assert hazard_level_at_depth(float("nan")) is None


class TestFlagsTravel:
    def test_near_boundary_propagates(self):
        assert directive_for_gauge(HazardLevel.LOW, 900.0, True, None)["near_boundary"] is True
        assert directive_for_gauge(HazardLevel.LOW, 900.0, False, None)["near_boundary"] is False
        assert directive_for_gauge(HazardLevel.LOW, 900.0, None, None)["near_boundary"] is None

    def test_minority_arrival_propagates(self):
        payload = directive_for_gauge(HazardLevel.LOW, 900.0, False, "MINORITY ARRIVAL: 1 of 4",
                                      minority_arrival=True)
        assert payload["minority_arrival"] is True
        assert payload["note"] == "MINORITY ARRIVAL: 1 of 4"

    def test_the_thresholds_say_they_are_unvetted_and_state_themselves(self):
        payload = directive_for_gauge(HazardLevel.LOW, 900.0, False, None)
        assert evacuation.DIRECTIVE_THRESHOLDS_VERIFIED is False
        assert payload["thresholds_unvetted"] is True
        assert "UNVETTED" in payload["threshold_source"]
        assert payload["thresholds"]["lead_time_s"] == evacuation.DIRECTIVE_LEAD_TIME_S
        assert payload["thresholds"]["hazard_floor"] == evacuation.DIRECTIVE_HAZARD_FLOOR.value


class TestOneHazardDefinition:
    @pytest.mark.parametrize("depth", [0.0, 0.04, 0.2, 0.49, 0.51, 1.2, 1.6, 3.9, 4.1, 12.0])
    def test_the_class_comes_from_the_shared_classifier(self, depth):
        """No second band table: whatever FD2320 says, the directive agrees."""
        expected = HazardClassifier().classify_depth_only(np.array([depth]))[0]
        assert hazard_level_at_depth(depth) is expected


def _relative_luminance(hex_colour):
    channels = [int(hex_colour.lstrip("#")[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


class TestColours:
    @pytest.mark.parametrize("directive", list(Directive))
    def test_every_pair_is_at_least_seven_to_one(self, directive):
        pair = DIRECTIVE_COLORS[directive]
        high, low = sorted([_relative_luminance(pair["bg"]), _relative_luminance(pair["fg"])],
                           reverse=True)
        assert (high + 0.05) / (low + 0.05) >= 7.0

    @pytest.mark.parametrize("directive", list(Directive))
    def test_no_background_is_green(self, directive):
        """None of the four states means safe; the palette must not say so."""
        bg = DIRECTIVE_COLORS[directive]["bg"].lstrip("#")
        red, green, blue = (int(bg[i:i + 2], 16) for i in (0, 2, 4))
        assert not (green > red + 16 and green > blue + 16), directive
