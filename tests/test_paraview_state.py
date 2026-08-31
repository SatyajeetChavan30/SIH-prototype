"""
Saved ParaView state files must reference their data by ABSOLUTE path.

ParaView writes a reader's file path into a .pvsm verbatim and, on restore,
resolves it against the CWD of whatever process opens the state — not against
the state file's own location. A relative path therefore produces a state that
loads only from the directory it was generated in.

That shipped once: states embedded "data/simulation/<run>.xdmf", so opening one
anywhere but the repo root gave `vtkXdmfReader ERR| Error opening file`,
points=0, and a blank render view. It survived review because the API launches
ParaView with the repo root as CWD, and because the checks used at the time
(does paraview.exe start? does the XML contain the expected filter proxies?)
cannot tell a working scene from an empty one.

This test can. It is the cheap, headless guard for that class of bug.

Requires ParaView. Skipped where it is absent, matching how the VTK-dependent
tests in test_xdmf_export.py behave.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RENDER_SCRIPT = REPO_ROOT / "paraview" / "render_static.py"

PVPYTHON = Path(os.environ.get(
    "JALRAKSHA_PVPYTHON_EXE", r"C:/Program Files/ParaView 6.2.0/bin/pvpython.exe"))

# The smallest dataset in the repo (~93 KB) — this test is about path handling,
# not rendering fidelity, so there is no reason to pay for a large one.
DATASET = REPO_ROOT / "data" / "simulation" / "khadakwasla_terrain.xdmf"

pytestmark = [
    pytest.mark.skipif(not PVPYTHON.exists(),
                       reason=f"pvpython not found at {PVPYTHON}"),
    pytest.mark.skipif(not DATASET.exists(),
                       reason=f"dataset not staged: {DATASET} (data/ is gitignored)"),
]

# Matches a path-like value anywhere in the state XML.
_PATHISH = re.compile(r'value="([^"]*\.(?:xdmf|h5|vtp|vti|vtu))"', re.I)
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")


@pytest.fixture(scope="module")
def state_file(tmp_path_factory) -> Path:
    """Build a real .pvsm the same way the API does, from a RELATIVE input path."""
    out = tmp_path_factory.mktemp("pvsm") / "state.pvsm"
    # Deliberately pass the dataset relative to the repo root: that is exactly
    # what the API used to do, and what previously poisoned the state.
    relative_dataset = DATASET.relative_to(REPO_ROOT)
    proc = subprocess.run(
        [str(PVPYTHON), str(RENDER_SCRIPT),
         "--xdmf", str(relative_dataset),
         "--save-state", str(out)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0 or not out.exists():
        pytest.fail(
            f"could not build a state file (exit {proc.returncode}).\n"
            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
        )
    return out


def test_state_embeds_only_absolute_dataset_paths(state_file):
    text = state_file.read_text(encoding="utf-8", errors="replace")
    found = _PATHISH.findall(text)
    assert found, "state referenced no dataset file at all — the reader is missing"
    relative = [v for v in found if not _ABSOLUTE.match(v)]
    assert not relative, (
        "state embeds relative dataset path(s), so it will restore blank for any "
        f"process whose CWD is not the repo root: {relative}"
    )


def test_state_points_at_the_dataset_it_was_built_from(state_file):
    """A resolved path must still be the SAME file, not merely absolute."""
    text = state_file.read_text(encoding="utf-8", errors="replace")
    found = [Path(v) for v in _PATHISH.findall(text)]
    assert any(p.name == DATASET.name for p in found), (
        f"no reference to {DATASET.name} among {[p.name for p in found]}"
    )
    for path in found:
        if path.name == DATASET.name:
            assert path.resolve() == DATASET.resolve(), (
                f"state points at {path}, expected {DATASET}"
            )


def test_state_restores_with_data_from_an_unrelated_cwd(state_file, tmp_path):
    """
    The end-to-end guard: restore headlessly from a directory that is NOT the
    repo root and assert the reader actually produced points.

    points == 0 is the blank window, expressed as a number.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys\n"
        "from paraview.simple import *\n"
        "LoadState(sys.argv[1])\n"
        "total = 0\n"
        "for key, src in GetSources().items():\n"
        "    try:\n"
        "        src.UpdatePipeline()\n"
        "        total += src.GetDataInformation().GetNumberOfPoints()\n"
        "    except Exception:\n"
        "        pass\n"
        "print('TOTAL_POINTS', total)\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(PVPYTHON), str(probe), str(state_file)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=300,
    )
    match = re.search(r"TOTAL_POINTS (\d+)", proc.stdout)
    assert match, f"probe produced no result.\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
    assert int(match.group(1)) > 0, (
        "state restored with zero points from an unrelated CWD — this is the "
        "blank-render-view bug. stderr:\n" + proc.stderr[-2000:]
    )
    assert "Error opening file" not in proc.stderr, (
        "reader could not open its dataset:\n" + proc.stderr[-2000:]
    )


# The base block reaches a DIFFERENT reader (XMLPolyDataReader) via a different
# call site than the dataset, so the coercion has to be proven on both. It is
# not covered by the tests above, which build a state without --base-block.
BASE_BLOCK = REPO_ROOT / "data" / "simulation" / "khadakwasla_terrain_base.vtp"


@pytest.fixture(scope="module")
def state_with_base_block(tmp_path_factory) -> Path:
    # Build the block if it is missing rather than skipping. Base blocks are
    # generated artifacts under a gitignored data/, so on most checkouts the
    # skip branch would be the ONLY branch — and a guard that never runs is not
    # a guard. The builder is plain Python (no ParaView) and near-instant on a
    # 93 KB dataset.
    if not BASE_BLOCK.exists():
        build = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "paraview" / "base_block.py"),
             "--dataset", str(DATASET)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
        )
        if build.returncode != 0 or not BASE_BLOCK.exists():
            pytest.skip(
                f"could not build a base block ({build.returncode}): "
                f"{(build.stderr or build.stdout)[-400:]}"
            )
    out = tmp_path_factory.mktemp("pvsm_block") / "state.pvsm"
    proc = subprocess.run(
        [str(PVPYTHON), str(RENDER_SCRIPT),
         "--xdmf", str(DATASET.relative_to(REPO_ROOT)),
         "--base-block", str(BASE_BLOCK.relative_to(REPO_ROOT)),
         "--save-state", str(out)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0 or not out.exists():
        pytest.fail(
            f"could not build a base-block state (exit {proc.returncode}).\n"
            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
        )
    return out


def test_base_block_path_is_also_absolute(state_with_base_block):
    text = state_with_base_block.read_text(encoding="utf-8", errors="replace")
    found = _PATHISH.findall(text)
    vtp = [v for v in found if v.lower().endswith(".vtp")]
    assert vtp, f"state has no .vtp reference; found {found}"
    relative = [v for v in vtp if not _ABSOLUTE.match(v)]
    assert not relative, (
        f"base block embedded by relative path — the block will vanish when the "
        f"state is opened from another directory: {relative}"
    )


# Probe kept as a plain triple-quoted constant: it is a pvpython script written
# to disk verbatim, and embedding it as an escaped one-liner is how the last
# attempt at this test broke.
_LAYOUT_PROBE = '''
import sys
from paraview.simple import *
LoadState(sys.argv[1])
# Deliberately NOT GetActiveViewOrCreate: that CREATES a view when the state
# supplies none, which is precisely how this bug escaped verification.
views = GetViews()
layouts = GetLayouts()
in_layout = bool(views) and GetLayout(views[0]) is not None
print("VIEWS", len(views))
print("LAYOUTS", len(layouts))
print("IN_LAYOUT", int(in_layout))
'''


def test_state_supplies_a_view_inside_a_layout(state_file, tmp_path):
    """
    The ParaView GUI builds its tabs from LAYOUTS, not from views.

    A state carrying a RenderView that belongs to no layout restores as a fully
    populated Pipeline Browser beside an EMPTY tab: every filter listed, nothing
    drawn. That shipped, and headless rendering cannot detect it — a view renders
    and screenshots perfectly well outside any layout.
    """
    probe = tmp_path / "layout_probe.py"
    probe.write_text(_LAYOUT_PROBE, encoding="utf-8")
    proc = subprocess.run(
        [str(PVPYTHON), str(probe), str(state_file)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=300,
    )

    def value(key: str) -> int:
        match = re.search(key + r"\s+(\d+)", proc.stdout)
        assert match, (
            f"probe reported no {key}.\nstdout:\n{proc.stdout[-2000:]}"
            f"\nstderr:\n{proc.stderr[-2000:]}"
        )
        return int(match.group(1))

    assert value("VIEWS") > 0, "state supplies no view at all"
    assert value("LAYOUTS") > 0, (
        "state has no layout — the ParaView GUI restores the pipeline into an "
        "empty tab and renders nothing"
    )
    assert value("IN_LAYOUT") == 1, "the state's view is not assigned to a layout"
