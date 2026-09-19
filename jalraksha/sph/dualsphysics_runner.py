"""
Near-field SPH on the GPU through DualSPHysics v5.4 (Phase 7).

WHY THIS ENGINE EXISTS. PySPH's GPU path (pysph_runner.py) is host-bound: on
the production Khadakwasla case (9,000 fluid particles, 15 s) the OpenCL run
was stopped unfinished at 2,442 s wall, 2,289 s of it CPU time, at 9.4 W of GPU
draw (docs/validation_findings.md §12). DualSPHysics runs the whole particle
loop — neighbour list, interaction, integration — in native CUDA, so the GPU
does the work. The first measurement on the build machine (the stock
01_DamBreak example, 171,496 particles, 2,374 steps to t = 0.2 s) took 12.4 s
on the RTX 4050.

HOW IT IS CALLED. DualSPHysics is an external program, LGPL-2.1, never linked
and never bundled. It is located on disk (JALRAKSHA_DUALSPHYSICS_DIR, else
<repo>/DualSPHysics_v5.4) and run as a subprocess. GenCase is NOT used: this
module writes the initial particle state (Case.xml + Case.bi4) itself, from
the same DEM-derived geometry pysph_runner builds, so the two engines start
from the same bed, walls, reservoir and breach velocity (sph/geometry.py holds
the shared rules). GenCase's own `drawbathymetry` would triangulate and
re-lattice the bed, which is a different geometry, and it cannot set a velocity
on a breach strip that follows the downsampled bed.

THE RESULT CONTRACT is pysph_runner.run_near_field_sph's, key for key, so the
service layer, the comparison and the dashboard need no second code path.
`engine`, `engine_label`, `sph_backend`, `sph_backend_label` and
`sph_backend_reason` always name what actually ran.

GPU OR CPU. `DualSPHysics5.4_win64.exe` WITHOUT `-gpu` silently runs on the
CPU, so `-gpu` is always passed on the GPU path and the device name is read
back from Run.out rather than assumed. With no CUDA device the program exits 1
and Run.out says "There are no available CUDA devices". "auto" and
"prefer_gpu" then run DualSPHysics's own OpenMP build and record why; "gpu"
raises. Never bit-compare the two: they integrate in different precisions
("Pos-Cell" on the GPU, "Pos-Double" on the CPU), the same stance
tests/test_solver_cuda.py takes for the SWE solver.

Reference: J.M. Dominguez et al. (2022) "DualSPHysics: from fluid dynamics to
multiphysics problems", Computational Particle Mechanics 9:867-895,
doi:10.1007/s40571-021-00404-2.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from jalraksha.sph.geometry import (
    FRONT_MIN_PARTICLES,
    GRAVITY,
    RHO_WATER,
    SPHUnavailableError,
    _assert_did_not_diverge,
    _downsample_bed,
    _sample_bed,
    _scratch_dir,
    breach_inflow_velocity,
    orient_downhill,
    particle_spacing_for_budget,
)

DUALSPHYSICS_DIR_ENV = "JALRAKSHA_DUALSPHYSICS_DIR"
SPH_BACKEND_ENV = "JALRAKSHA_SPH_BACKEND"
DEFAULT_DUALSPHYSICS_DIR = Path(__file__).resolve().parents[2] / "DualSPHysics_v5.4"
DUALSPHYSICS_VERSION = "v5.4"

# Fluid-particle budget. 250,000 fills the production window (1.2 x 1.2 km,
# reservoir in its upstream quarter) at about 5 m spacing for a 100 m head and
# 7 m for Tehri's 260 m — against 16 m and 22 m at PySPH's 9,000. Chosen to fit
# comfortably in a 6 GB laptop GPU, not from a convergence study.
TARGET_FLUID_PARTICLES = 250_000

# ---- DualSPHysics scheme settings. Each is the value of DualSPHysics's own
# validated dam-break example (examples/main/01_DamBreak, compared there against
# Koshizuka & Oka 1996) unless stated otherwise.
KERNEL_WENDLAND = 2  # quintic Wendland (Wendland 1995), DualSPHysics default kernel
STEP_SYMPLECTIC = 2  # symplectic position-Verlet (Dominguez et al. 2022 §2.4)
BOUNDARY_DBC = 1  # dynamic boundary particles (Crespo et al. 2007)
COEF_H = 1.0  # h = coefh * sqrt(3 dp^2) in 3D, as in 01_DamBreak
CFL_NUMBER = 0.2  # DualSPHysics default
TAIT_GAMMA = 7.0  # Tait EOS polytropic constant for water (Monaghan 1994)
COEF_SOUND = 20.0  # c0 = coefsound * speedsystem, the GenCase default
# TODO: UNVETTED — artificial viscosity alpha. 0.01 is the value DualSPHysics's
# XML reference names as "typical for Artificial"; its dam-break example uses
# 0.1. Neither was fitted to a flood over 30 m terrain. Verification queue, as
# for pysph_runner.ALPHA_VISCOSITY.
ARTIFICIAL_VISCOSITY = 0.01
DENSITY_DIFFUSION_FOURTAKAS = 2  # Fourtakas et al. (2019) density diffusion term
DENSITY_DIFFUSION_VALUE = 0.1  # DualSPHysics default delta
RHO_OUT_MIN = 700.0  # DualSPHysics default validity window (kg/m3); particles
RHO_OUT_MAX = 1300.0  # outside it are excluded and counted as escaped
# Snapshots written per run. They exist only to measure the front history and
# are deleted after parsing: 40 parts at 250k particles is about 440 MB.
N_OUTPUT_PARTS = 40

# Walls and bed are two particle layers, as in pysph_runner.
BOUNDARY_LAYERS = 2

_MK_FLUID_FIRST = 1
_MK_BOUND_FIRST = 10


# ─── install discovery ────────────────────────────────────────────────────────


def resolve_dualsphysics(custom_dir: Optional[str] = None) -> tuple:
    """
    Locate a DualSPHysics install.

    Order: `custom_dir`, then JALRAKSHA_DUALSPHYSICS_DIR, then
    <repo>/DualSPHysics_v5.4. A directory that was named explicitly but is
    wrong returns None with the reason — it never falls through to searching
    somewhere else, because a run that silently used a different install than
    the one configured is the provenance failure delft3d/runner.py avoids too.

    Returns:
        (paths or None, detail). paths has "dir", "gpu_exe", "cpu_exe".
    """
    explicit = custom_dir or os.environ.get(DUALSPHYSICS_DIR_ENV, "").strip()
    root = Path(explicit) if explicit else DEFAULT_DUALSPHYSICS_DIR
    source = "configured" if explicit else "default"

    if sys.platform.startswith("win"):
        bin_dir = root / "bin" / "windows"
        gpu_exe, cpu_exe = bin_dir / "DualSPHysics5.4_win64.exe", bin_dir / "DualSPHysics5.4CPU_win64.exe"
    else:
        bin_dir = root / "bin" / "linux"
        gpu_exe, cpu_exe = bin_dir / "DualSPHysics5.4_linux64", bin_dir / "DualSPHysics5.4CPU_linux64"

    if not root.is_dir():
        return None, f"DualSPHysics not found: {source} directory {root} does not exist"
    missing = [p.name for p in (gpu_exe, cpu_exe) if not p.is_file()]
    if missing:
        return None, f"DualSPHysics install at {root} is incomplete: missing {', '.join(missing)}"
    return {"dir": str(root), "gpu_exe": str(gpu_exe), "cpu_exe": str(cpu_exe)}, (
        f"DualSPHysics {DUALSPHYSICS_VERSION} at {root}"
    )


def is_dualsphysics_available(custom_dir: Optional[str] = None) -> tuple:
    """(available, detail) — mirrors pysph_runner.is_pysph_available."""
    paths, detail = resolve_dualsphysics(custom_dir)
    return paths is not None, detail


# ─── JBinaryData (.bi4) reader and writer ─────────────────────────────────────
#
# The format is DualSPHysics's JBinaryData (src_extra/ToVTK/source/
# JBinaryData.cpp): a 64-byte header, then one ITEM holding VALUES, ARRAYs and
# child ITEMs, every string length-prefixed with a uint32. Value TYPES are
# checked when DualSPHysics reads them, so the writer uses exactly the types
# GenCase v5.4.354 writes (measured from its output, not guessed).

_T_TEXT, _T_BOOL, _T_INT, _T_UINT, _T_ULLONG, _T_FLOAT, _T_DOUBLE = 1, 2, 7, 8, 10, 11, 12
_T_FLOAT3, _T_DOUBLE3 = 22, 23
_SCALAR_FMT = {2: "i", 3: "b", 4: "B", 5: "h", 6: "H", 7: "i", 8: "I", 9: "q", 10: "Q", 11: "f", 12: "d"}
_TRIPLE_FMT = {20: "3i", 21: "3I", 22: "3f", 23: "3d"}
_ARRAY_DTYPE = {
    2: "<i4", 3: "i1", 4: "u1", 5: "<i2", 6: "<u2", 7: "<i4", 8: "<u4", 9: "<i8", 10: "<u8",
    11: "<f4", 12: "<f8", 20: ("<i4", 3), 21: ("<u4", 3), 22: ("<f4", 3), 23: ("<f8", 3),
}


def _pack_str(text: str) -> bytes:
    raw = text.encode("latin1")
    return struct.pack("<I", len(raw)) + raw


def _pack_value(name: str, type_code: int, value) -> bytes:
    out = _pack_str(name) + struct.pack("<i", type_code)
    if type_code == _T_TEXT:
        return out + _pack_str(value)
    if type_code in _SCALAR_FMT:
        return out + struct.pack("<" + _SCALAR_FMT[type_code], value)
    return out + struct.pack("<" + _TRIPLE_FMT[type_code], *value)


def _pack_item(name: str, values: list, arrays: list, items: list) -> bytes:
    """values: [(name, type, value)]; arrays: [(name, type, ndarray)]; items: packed children."""
    values_blob = b"".join(_pack_value(*v) for v in values)
    values_blob = _pack_str("\nVALUES") + struct.pack("<I", len(values)) + values_blob if values else b""
    base = (
        _pack_str("\nITEM\n") + _pack_str(name) + struct.pack("<ii", 0, 0)
        + _pack_str("%.7E") + _pack_str("%.15E")
        + struct.pack("<III", len(arrays), len(items), len(values_blob))
    )
    parts = [struct.pack("<I", len(base)), base, values_blob]
    for array_name, type_code, data in arrays:
        data = np.ascontiguousarray(data, dtype=np.dtype(_ARRAY_DTYPE[type_code]).base)
        count = data.shape[0]
        definition = (
            _pack_str("\nARRAY") + _pack_str(array_name)
            + struct.pack("<iiII", 0, type_code, count, data.nbytes)
        )
        parts += [struct.pack("<I", len(definition)), definition, data.tobytes()]
    parts += items
    return b"".join(parts)


def _bi4_header(file_code: str) -> bytes:
    title = f"#FileJBD {file_code}"[:58].ljust(58).encode("latin1")
    return title + b"\n\x00" + bytes([0, 0, 0, 0])  # little-endian flag + 3 unused bytes


class _Bi4Reader:
    def __init__(self, blob: bytes, offset: int = 64):
        self.blob, self.offset = blob, offset

    def _u32(self) -> int:
        value = struct.unpack_from("<I", self.blob, self.offset)[0]
        self.offset += 4
        return value

    def _str(self) -> str:
        n = self._u32()
        text = self.blob[self.offset : self.offset + n].decode("latin1")
        self.offset += n
        return text

    def item(self, wanted_arrays=None) -> Dict[str, Any]:
        self._u32()
        if self._str() != "\nITEM\n":
            raise SPHUnavailableError("Unreadable DualSPHysics .bi4 file (bad item code).")
        name = self._str()
        self.offset += 8
        self._str(), self._str()
        n_arrays, n_items, size_values = self._u32(), self._u32(), self._u32()
        values: Dict[str, Any] = {}
        if size_values:
            end = self.offset + size_values
            self._str()
            for _ in range(self._u32()):
                key = self._str()
                type_code = struct.unpack_from("<i", self.blob, self.offset)[0]
                self.offset += 4
                if type_code == _T_TEXT:
                    values[key] = self._str()
                    continue
                fmt = "<" + (_SCALAR_FMT.get(type_code) or _TRIPLE_FMT[type_code])
                unpacked = struct.unpack_from(fmt, self.blob, self.offset)
                self.offset += struct.calcsize(fmt)
                values[key] = unpacked[0] if len(unpacked) == 1 else unpacked
            self.offset = end
        arrays: Dict[str, np.ndarray] = {}
        for _ in range(n_arrays):
            self._u32()
            self._str()
            array_name = self._str()
            self.offset += 4
            type_code = struct.unpack_from("<i", self.blob, self.offset)[0]
            self.offset += 4
            count, size = self._u32(), self._u32()
            if (wanted_arrays is None or array_name in wanted_arrays) and type_code != _T_TEXT:
                arrays[array_name] = np.frombuffer(
                    self.blob, dtype=np.dtype(_ARRAY_DTYPE[type_code]), count=count, offset=self.offset
                )
            self.offset += size
        items = [self.item(wanted_arrays) for _ in range(n_items)]
        return {"name": name, "values": values, "arrays": arrays, "items": items}


def read_part_file(path: Path, wanted_arrays=("Idp", "Posd", "Pos", "Vel")) -> Dict[str, Any]:
    """Read one Part_XXXX.bi4: its time and the requested particle arrays (copied)."""
    blob = Path(path).read_bytes()
    root = _Bi4Reader(blob).item(set(wanted_arrays))
    if not root["items"]:
        raise SPHUnavailableError(f"{path} holds no particle data.")
    part = root["items"][0]
    arrays = {k: np.array(v, copy=True) for k, v in part["arrays"].items()}
    if "Posd" in arrays:
        arrays["Pos"] = arrays.pop("Posd")
    return {"time_s": float(part["values"].get("TimeStep", 0.0)), "values": part["values"], "arrays": arrays}


# ─── case writer ──────────────────────────────────────────────────────────────


def _xml_number(value: float) -> str:
    return repr(float(value))


def write_case(
    case_dir: Path,
    bound_blocks: List[tuple],
    fluid_pos: np.ndarray,
    fluid_vel: np.ndarray,
    fluid_rho: np.ndarray,
    spacing: float,
    speed_of_sound: float,
    duration_s: float,
    time_out_s: float,
    case_name: str = "Case",
) -> Dict[str, float]:
    """
    Write Case.xml + Case.bi4 — the initial state DualSPHysics loads.

    Args:
        bound_blocks: [(label, positions[n,3])] fixed boundary blocks, in order.
        fluid_pos / fluid_vel / fluid_rho: the fluid block.

    Returns the derived constants (h, B, particle mass) so the caller can report
    exactly what the solver was given.
    """
    case_dir.mkdir(parents=True, exist_ok=True)
    smoothing_length = COEF_H * np.sqrt(3.0) * spacing
    tait_b = speed_of_sound**2 * RHO_WATER / TAIT_GAMMA
    particle_mass = RHO_WATER * spacing**3

    bound_pos = np.concatenate([b for _, b in bound_blocks], axis=0) if bound_blocks else np.zeros((0, 3))
    n_bound, n_fluid = bound_pos.shape[0], fluid_pos.shape[0]
    n_total = n_bound + n_fluid
    all_pos = np.concatenate([bound_pos, fluid_pos], axis=0)
    all_vel = np.concatenate([np.zeros((n_bound, 3)), fluid_vel], axis=0)
    all_rho = np.concatenate([np.full(n_bound, RHO_WATER), fluid_rho])
    pos_min, pos_max = all_pos.min(axis=0), all_pos.max(axis=0)

    header_values = [
        ("Piece", _T_UINT, 0), ("Npiece", _T_UINT, 1), ("RunCode", _T_TEXT, "00000000"),
        ("Date", _T_TEXT, "???"), ("AppName", _T_TEXT, "JalRaksha dualsphysics_runner"),
        ("CaseName", _T_TEXT, case_name), ("Data2d", _T_BOOL, 0), ("Data2dPosY", _T_DOUBLE, 0.0),
        ("MapPosMin", _T_DOUBLE3, (0.0, 0.0, 0.0)), ("MapPosMax", _T_DOUBLE3, (0.0, 0.0, 0.0)),
        # 96 / 99 are GenCase's "unset" markers for these two, copied as written.
        ("PeriMode", _T_INT, 96), ("PeriXinc", _T_DOUBLE3, (0.0, 0.0, 0.0)),
        ("PeriYinc", _T_DOUBLE3, (0.0, 0.0, 0.0)), ("PeriZinc", _T_DOUBLE3, (0.0, 0.0, 0.0)),
        ("AxisDiv", _T_INT, 99), ("CaseNp", _T_ULLONG, n_total), ("CaseNfixed", _T_ULLONG, n_bound),
        ("CaseNmoving", _T_ULLONG, 0), ("CaseNfloat", _T_ULLONG, 0), ("CaseNfluid", _T_ULLONG, n_fluid),
        ("CasePosMin", _T_DOUBLE3, tuple(map(float, pos_min))),
        ("CasePosMax", _T_DOUBLE3, tuple(map(float, pos_max))),
        ("NpDynamic", _T_BOOL, 0), ("ReuseIds", _T_BOOL, 0), ("Dp", _T_DOUBLE, spacing),
        ("H", _T_DOUBLE, smoothing_length), ("B", _T_DOUBLE, tait_b), ("Rhop0", _T_DOUBLE, RHO_WATER),
        ("Gamma", _T_DOUBLE, TAIT_GAMMA), ("MassBound", _T_DOUBLE, particle_mass),
        ("MassFluid", _T_DOUBLE, particle_mass),
    ]
    part = _pack_item(
        "PART_0000",
        [("Cpart", _T_UINT, 0), ("TimeStep", _T_DOUBLE, 0.0), ("Npok", _T_UINT, n_total),
         ("Nout", _T_UINT, 0), ("Step", _T_UINT, 0), ("RunTime", _T_DOUBLE, 0.0),
         ("DomainMin", _T_DOUBLE3, (0.0, 0.0, 0.0)), ("DomainMax", _T_DOUBLE3, (0.0, 0.0, 0.0))],
        [("Idp", _T_UINT, np.arange(n_total, dtype=np.uint32)), ("Posd", _T_DOUBLE3, all_pos),
         ("Vel", _T_FLOAT3, all_vel), ("Rhop", _T_FLOAT, all_rho)],
        [],
    )
    blob = _bi4_header("JPartDataBi4") + _pack_item("JPartDataBi4", header_values, [], [part])
    (case_dir / f"{case_name}.bi4").write_bytes(blob)

    fixed_rows, begin = [], 0
    for mkbound, (_, block) in enumerate(bound_blocks):
        fixed_rows.append(
            f'            <fixed mkbound="{mkbound}" mk="{_MK_BOUND_FIRST + mkbound}" '
            f'begin="{begin}" count="{block.shape[0]}" />'
        )
        begin += block.shape[0]
    gravity = f'<gravity x="0" y="0" z="{-GRAVITY}" />'
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<case app="JalRaksha dualsphysics_runner">
    <casedef>
        <constantsdef>
            {gravity}
            <rhop0 value="{RHO_WATER}" />
            <gamma value="{TAIT_GAMMA}" />
            <coefsound value="{COEF_SOUND}" />
            <speedsound value="{_xml_number(speed_of_sound)}" />
            <coefh value="{COEF_H}" />
            <cflnumber value="{CFL_NUMBER}" />
        </constantsdef>
        <mkconfig boundcount="240" fluidcount="9" />
    </casedef>
    <execution>
        <parameters>
            <parameter key="SavePosDouble" value="1" />
            <parameter key="Boundary" value="{BOUNDARY_DBC}" />
            <parameter key="StepAlgorithm" value="{STEP_SYMPLECTIC}" />
            <parameter key="Kernel" value="{KERNEL_WENDLAND}" />
            <parameter key="ViscoTreatment" value="1" />
            <parameter key="Visco" value="{ARTIFICIAL_VISCOSITY}" />
            <parameter key="ViscoBoundFactor" value="1" />
            <parameter key="DensityDT" value="{DENSITY_DIFFUSION_FOURTAKAS}" />
            <parameter key="DensityDTvalue" value="{DENSITY_DIFFUSION_VALUE}" />
            <parameter key="Shifting" value="0" />
            <parameter key="CoefDtMin" value="0.05" />
            <parameter key="DtIni" value="0" />
            <parameter key="DtMin" value="0" />
            <parameter key="DtFixed" value="0" />
            <parameter key="DtAllParticles" value="0" />
            <parameter key="TimeMax" value="{_xml_number(duration_s)}" />
            <parameter key="TimeOut" value="{_xml_number(time_out_s)}" />
            <parameter key="MinFluidStop" value="0" />
            <parameter key="RhopOutMin" value="{RHO_OUT_MIN}" />
            <parameter key="RhopOutMax" value="{RHO_OUT_MAX}" />
            <simulationdomain>
                <posmin x="default" y="default" z="default" />
                <posmax x="default" y="default" z="default + 50%" />
            </simulationdomain>
        </parameters>
        <particles np="{n_total}" nb="{n_bound}" nbf="{n_bound}" mkboundfirst="{_MK_BOUND_FIRST}" mkfluidfirst="{_MK_FLUID_FIRST}">
{chr(10).join(fixed_rows)}
            <fluid mkfluid="0" mk="{_MK_FLUID_FIRST}" begin="{n_bound}" count="{n_fluid}" />
        </particles>
        <constants>
            <data2d value="false" />
            {gravity}
            <cflnumber value="{CFL_NUMBER}" />
            <gamma value="{TAIT_GAMMA}" />
            <rhop0 value="{RHO_WATER}" />
            <dp value="{_xml_number(spacing)}" />
            <h value="{_xml_number(smoothing_length)}" />
            <b value="{_xml_number(tait_b)}" />
            <massbound value="{_xml_number(particle_mass)}" />
            <massfluid value="{_xml_number(particle_mass)}" />
        </constants>
        <motion />
    </execution>
</case>
"""
    (case_dir / f"{case_name}.xml").write_text(xml, encoding="utf-8")
    return {"h_m": float(smoothing_length), "tait_b_pa": float(tait_b), "particle_mass_kg": float(particle_mass)}


def hydrostatic_density(z: np.ndarray, surface_z: np.ndarray, speed_of_sound: float) -> np.ndarray:
    """
    Tait-consistent hydrostatic density, rho = rho0 (1 + rho0 g (s - z) / B)^(1/gamma).

    The same inversion pysph_runner.hydrostatic_density performs and GenCase's
    `rhopgradient=2` writes: a column started at uniform rho0 has zero pressure
    everywhere and must compress under its own weight first.
    """
    tait_b = RHO_WATER * speed_of_sound**2 / TAIT_GAMMA
    pressure = RHO_WATER * GRAVITY * np.maximum(0.0, surface_z - z)
    return RHO_WATER * (1.0 + pressure / tait_b) ** (1.0 / TAIT_GAMMA)


# ─── running ──────────────────────────────────────────────────────────────────


def _run_out_tail(out_dir: Path, lines: int = 12) -> str:
    run_out = out_dir / "Run.out"
    if not run_out.is_file():
        return "(no Run.out written)"
    text = run_out.read_text(encoding="latin1", errors="replace").strip().splitlines()
    return " | ".join(line.strip() for line in text[-lines:] if line.strip())


def _device_from_run_out(out_dir: Path) -> Optional[str]:
    run_out = out_dir / "Run.out"
    if not run_out.is_file():
        return None
    for line in run_out.read_text(encoding="latin1", errors="replace").splitlines():
        if line.startswith("Device default:"):
            return line.split('"')[1] if '"' in line else line.split(":", 1)[1].strip()
    return None


def _run_mode_from_run_out(out_dir: Path) -> Optional[str]:
    run_out = out_dir / "Run.out"
    if not run_out.is_file():
        return None
    for line in run_out.read_text(encoding="latin1", errors="replace").splitlines():
        if line.startswith("RunMode="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def _gpu_side_failure(out_dir: Path, log_text: str) -> bool:
    """
    True when a failed GPU run failed for a GPU reason (no device, CUDA error,
    device memory) — the cases a CPU rerun can answer. A failure in the case
    itself would fail identically on the CPU, so it is not retried.
    """
    haystack = log_text[-4000:] + " " + _run_out_tail(out_dir, 12)
    return any(marker in haystack for marker in ("no available CUDA devices", "CUDA", "GPU memory", "cuda"))


def _execute(exe: str, case_dir: Path, out_dir: Path, use_gpu: bool, timeout_s: float) -> tuple:
    """Run DualSPHysics once. Returns (returncode, combined log text)."""
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = [exe]
    if use_gpu:
        argv.append("-gpu")  # WITHOUT it the GPU executable silently runs on the CPU
    argv += [str(case_dir / "Case"), str(out_dir), "-svres:1", "-sv:binx", "-createdirs:1"]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            argv, cwd=str(Path(exe).parent), capture_output=True, text=True,
            errors="replace", timeout=timeout_s, creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise SPHUnavailableError(
            f"DualSPHysics did not finish within {timeout_s:.0f} s and was stopped."
        ) from exc
    log = (completed.stdout or "") + (completed.stderr or "")
    (out_dir / "run.log").write_text(log, encoding="utf-8")
    return completed.returncode, log


def _probe_case(case_dir: Path) -> None:
    """A 12 x 12 x 6-particle closed tank: enough to make DualSPHysics pick a device."""
    blocks, fluid = _closed_tank(n_cells=12, n_layers=6, spacing=0.1)
    c0 = COEF_SOUND * np.sqrt(GRAVITY * 0.6)
    write_case(case_dir, blocks, fluid, np.zeros_like(fluid),
               hydrostatic_density(fluid[:, 2], np.full(fluid.shape[0], 0.6), c0),
               0.1, c0, duration_s=0.01, time_out_s=0.01)


@lru_cache(maxsize=4)
def probe_dualsphysics_gpu(custom_dir: Optional[str] = None) -> tuple:
    """
    Whether DualSPHysics can run on a CUDA GPU here, measured by running it.

    Cached per process. Returns (ok, reason, device_name or None).
    """
    paths, detail = resolve_dualsphysics(custom_dir)
    if paths is None:
        return False, detail, None
    work = _run_dir("probe")
    case_dir, out_dir = work / "case", work / "out"
    try:
        _probe_case(case_dir)
        code, log = _execute(paths["gpu_exe"], case_dir, out_dir, use_gpu=True, timeout_s=120)
    except (OSError, SPHUnavailableError) as exc:
        return False, f"DualSPHysics GPU probe could not start ({type(exc).__name__}: {exc})", None
    device = _device_from_run_out(out_dir)
    mode = _run_mode_from_run_out(out_dir) or ""
    tail = _run_out_tail(out_dir, 4)
    shutil.rmtree(work, ignore_errors=True)
    if code != 0 or "GPU" not in mode:
        return False, f"DualSPHysics GPU probe failed (exit {code}): {tail}", None
    return True, f"DualSPHysics {DUALSPHYSICS_VERSION} CUDA device: {device}", device


def resolve_dsph_backend(requested: Optional[str] = None, custom_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Decide whether DualSPHysics runs on the GPU or on its CPU build.

      * "gpu"         — GPU or nothing, start to finish: RAISES when no CUDA
                        device can run it, and a GPU run that fails partway is
                        an error, never rerun on the CPU. What a dashboard
                        "cuda" run maps to.
      * "auto"        — GPU when it can run, else the CPU build with the reason.
      * "prefer_gpu"  — same as auto.
      * "cpu"         — DualSPHysics's OpenMP build.

    JALRAKSHA_SPH_BACKEND overrides "auto" and "prefer_gpu" (operator's choice);
    "cuda" and "opencl" are accepted there as spellings of "gpu".

    The returned dict carries "strict", decided HERE from the final request
    (after the override), so no caller can re-derive it differently. An earlier
    version computed it at each call site and treated any set environment
    variable as non-strict, so JALRAKSHA_SPH_BACKEND=gpu still let a failed
    GPU run finish on the CPU.
    """
    requested = str(requested if requested is not None else "auto").strip().lower()
    if requested in ("auto", "prefer_gpu", "prefer_opencl"):
        override = os.environ.get(SPH_BACKEND_ENV, "").strip().lower()
        if override:
            requested = override
    requested = {"cuda": "gpu", "opencl": "gpu", "prefer_opencl": "prefer_gpu"}.get(requested, requested)
    if requested not in ("auto", "gpu", "prefer_gpu", "cpu"):
        raise ValueError(f"SPH backend must be auto, gpu, prefer_gpu or cpu (got {requested!r})")

    paths, detail = resolve_dualsphysics(custom_dir)
    if paths is None:
        raise SPHUnavailableError(detail)
    cpu = {"sph_backend": "cpu", "exe": paths["cpu_exe"], "use_gpu": False,
           "label": "CPU (DualSPHysics OpenMP)", "strict": False}
    if requested == "cpu":
        return {**cpu, "reason": "CPU requested"}
    ok, reason, device = probe_dualsphysics_gpu(custom_dir)
    if not ok:
        if requested == "gpu":
            raise SPHUnavailableError(f"GPU SPH requested but unavailable: {reason}")
        return {**cpu, "reason": f"GPU unavailable, running DualSPHysics on the CPU: {reason}"}
    return {"sph_backend": "gpu", "exe": paths["gpu_exe"], "use_gpu": True,
            "label": f"GPU (CUDA, {device})", "reason": reason,
            "strict": requested == "gpu"}


# ─── geometry ────────────────────────────────────────────────────────────────


def _closed_tank(n_cells: int, n_layers: int, spacing: float) -> tuple:
    """Still water in a closed box: ([(label, bound positions)], fluid positions)."""
    idx = np.arange(n_cells) * spacing
    gx, gy, gz = np.meshgrid(idx, idx, (np.arange(n_layers) + 0.5) * spacing, indexing="ij")
    fluid = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
    walls = []
    outer = np.arange(-BOUNDARY_LAYERS, n_cells + BOUNDARY_LAYERS) * spacing
    heights = (np.arange(n_layers + 2) + 0.5) * spacing
    for layer in range(BOUNDARY_LAYERS):
        bx, by = np.meshgrid(outer, outer, indexing="ij")
        walls.append(np.column_stack([bx.ravel(), by.ravel(), np.full(bx.size, -(layer + 0.5) * spacing)]))
        for coord in (-(layer + 1) * spacing, (n_cells + layer) * spacing):
            a, h = np.meshgrid(outer, heights, indexing="ij")
            walls.append(np.column_stack([np.full(a.size, coord), a.ravel(), h.ravel()]))
            walls.append(np.column_stack([a.ravel(), np.full(a.size, coord), h.ravel()]))
    bound = np.unique(np.round(np.concatenate(walls) / spacing * 2.0) / 2.0 * spacing, axis=0)
    return [("tank", bound)], fluid


def _bed_boundary(bed: np.ndarray, spacing: float) -> np.ndarray:
    """
    Boundary particles under the bed, deep enough to close every terrain step.

    pysph_runner lays two layers under each cell. On a downsampled 30 m DEM a
    neighbouring column can sit several spacings lower, which leaves a vertical
    face with no particles in it; each column here extends down to below its
    lowest 4-neighbour so the bed is closed.
    """
    padded = np.pad(bed, 1, mode="edge")
    neighbour_min = np.minimum.reduce([padded[:-2, 1:-1], padded[2:, 1:-1], padded[1:-1, :-2], padded[1:-1, 2:]])
    step_layers = np.ceil(np.maximum(0.0, bed - neighbour_min) / spacing).astype(int)
    layers = np.maximum(BOUNDARY_LAYERS, step_layers + 1)
    ny, nx = bed.shape
    jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    counts = layers.ravel()
    col_j, col_i = np.repeat(jj.ravel(), counts), np.repeat(ii.ravel(), counts)
    offsets = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
    z = bed[col_j, col_i] - (offsets + 0.5) * spacing
    return np.column_stack([col_i * spacing, col_j * spacing, z])


def _walls(bed: np.ndarray, spacing: float, wall_height: float) -> np.ndarray:
    """Upstream (y<0) and both lateral walls, open downstream — as in pysph_runner."""
    ny, nx = bed.shape
    k = (np.arange(int(wall_height / spacing) + 1) + 0.5) * spacing
    pieces = []
    for layer in range(BOUNDARY_LAYERS):
        offset = (layer + 0.5) * spacing
        ii, kk = np.meshgrid(np.arange(nx), k, indexing="ij")
        pieces.append(np.column_stack([ii.ravel() * spacing, np.full(ii.size, -offset), bed[0, ii.ravel()] + kk.ravel()]))
        jj, kk = np.meshgrid(np.arange(ny), k, indexing="ij")
        pieces.append(np.column_stack([np.full(jj.size, -offset), jj.ravel() * spacing, bed[jj.ravel(), 0] + kk.ravel()]))
        pieces.append(np.column_stack([np.full(jj.size, (nx - 1) * spacing + offset), jj.ravel() * spacing,
                                       bed[jj.ravel(), nx - 1] + kk.ravel()]))
    return np.concatenate(pieces)


def _reservoir(bed: np.ndarray, spacing: float, dam_row: int, reservoir_depth_m: float) -> tuple:
    """Fluid lattice upstream of the dam row under a LEVEL surface (pysph_runner's rule)."""
    nx = bed.shape[1]
    surface_z = float(bed[0, :].min() + reservoir_depth_m)
    n_layers = int(reservoir_depth_m / spacing)
    jj, ii, kk = np.meshgrid(np.arange(dam_row), np.arange(nx), np.arange(n_layers), indexing="ij")
    z = bed[jj, ii] + (kk + 0.5) * spacing
    keep = z <= surface_z
    pos = np.column_stack([ii[keep] * spacing, jj[keep] * spacing, z[keep]])
    return pos, surface_z


# ─── public entry points ─────────────────────────────────────────────────────


def _run_dir(label: str) -> Path:
    """
    A fresh directory for one DualSPHysics run.

    Unique per call, never per dam: the API probes the GPU in a child process
    while runs may be solving, and two runs of the same dam can overlap.
    DualSPHysics deletes nothing in its output directory, so a shared one would
    mix snapshots from different runs.
    """
    return Path(tempfile.mkdtemp(prefix=f"{time.strftime('%Y%m%d-%H%M%S')}_", dir=_scratch_dir(f"dsph_{label}")))


def _cleanup_parts(out_dir: Path) -> None:
    """Delete the bulk particle data (snapshots and the initial state); keep Run.out, Run.csv, run.log and Case.xml."""
    for initial in (out_dir.parent / "case").glob("*.bi4"):
        initial.unlink(missing_ok=True)
    data = out_dir / "data"
    if data.is_dir():
        for part in data.glob("Part_*.bi4"):
            part.unlink(missing_ok=True)
        for extra in data.glob("PartOut_*.obi4"):
            extra.unlink(missing_ok=True)


def _run_with_fallback(backend: Dict[str, Any], case_dir: Path, out_dir: Path,
                       timeout_s: float, custom_dir: Optional[str]) -> Dict[str, Any]:
    code, log = _execute(backend["exe"], case_dir, out_dir, backend["use_gpu"], timeout_s)
    if code == 0:
        return backend
    failure = _run_out_tail(out_dir)
    if backend["use_gpu"] and backend.get("strict"):
        raise SPHUnavailableError(
            f"DualSPHysics GPU run failed (exit {code}) and the GPU was required, so it "
            f"was not rerun on the CPU: {failure}"
        )
    if backend["use_gpu"] and _gpu_side_failure(out_dir, log):
        paths, _ = resolve_dualsphysics(custom_dir)
        cpu = {"sph_backend": "cpu", "exe": paths["cpu_exe"], "use_gpu": False,
               "label": "CPU (DualSPHysics OpenMP)", "strict": False,
               "reason": f"GPU run failed, rerun on the CPU: {failure}"}
        code, log = _execute(cpu["exe"], case_dir, out_dir, False, timeout_s)
        if code == 0:
            return cpu
        failure = _run_out_tail(out_dir)
    raise SPHUnavailableError(f"DualSPHysics exited with code {code}: {failure}")


def run_near_field_sph(
    bed_elevation: np.ndarray,
    cell_size_m: float,
    reservoir_depth_m: float,
    breach_width_m: float,
    q_peak_m3_s: float,
    dam_row_fraction: float = 0.25,
    duration_s: float = 30.0,
    dam_name: str = "Dam",
    target_particles: int = TARGET_FLUID_PARTICLES,
    backend: Optional[str] = "auto",
    dualsphysics_dir: Optional[str] = None,
    timeout_s: float = 7200.0,
    keep_parts: bool = False,
) -> Dict[str, Any]:
    """
    Near-field dam-break over real terrain, run by DualSPHysics.

    Arguments and returned keys are pysph_runner.run_near_field_sph's; see its
    docstring. Additional keys: `n_excluded` (particles DualSPHysics removed
    for leaving the simulation domain or the density window, included in
    `n_escaped`), `solver_run_mode` (DualSPHysics's own "RunMode" line),
    `case_dir`/`output_dir` (Run.out and the case files are kept there).

    Raises:
        SPHUnavailableError: DualSPHysics is not installed, a strict GPU request
            cannot run, or the run failed. Never returns a substitute.
    """
    sph_backend = resolve_dsph_backend(backend, dualsphysics_dir)

    bed_elevation = np.asarray(bed_elevation, dtype=np.float64)
    if bed_elevation.ndim != 2:
        raise ValueError(f"bed_elevation must be 2D, got shape {bed_elevation.shape}")

    # Same orientation, spacing, bed and reservoir rules as the PySPH engine
    # (sph/geometry.py), so the two engines start from the same case.
    bed_elevation, rotations = orient_downhill(bed_elevation)
    bed_drop_m = float(bed_elevation[0, :].mean() - bed_elevation[-1, :].mean())
    ny_src, nx_src = bed_elevation.shape
    domain_length_m = ny_src * cell_size_m
    domain_width_m = nx_src * cell_size_m
    reservoir_depth_m = float(max(reservoir_depth_m, 1.0))
    spacing = particle_spacing_for_budget(
        domain_length_m, domain_width_m, reservoir_depth_m, dam_row_fraction, target_particles
    )
    bed, nx, ny = _downsample_bed(bed_elevation, cell_size_m, spacing)
    dam_row = max(1, int(ny * dam_row_fraction))

    fluid_pos, surface_z = _reservoir(bed, spacing, dam_row, reservoir_depth_m)
    if fluid_pos.shape[0] == 0:
        raise ValueError(
            f"No fluid particles generated (spacing={spacing:.2f} m, reservoir_depth="
            f"{reservoir_depth_m:.1f} m). The near-field window is too small for this dam."
        )
    bed_bound = _bed_boundary(bed, spacing)
    wall_bound = _walls(bed, spacing, reservoir_depth_m + 2.0 * spacing)

    # One-way SWE -> SPH handoff: u = Q/(h w) on the breach strip only.
    u_inflow = breach_inflow_velocity(q_peak_m3_s, reservoir_depth_m, breach_width_m)
    breach_centre_x = 0.5 * (nx - 1) * spacing
    breach_mask = (np.abs(fluid_pos[:, 0] - breach_centre_x) <= breach_width_m / 2.0) & (
        fluid_pos[:, 1] >= (dam_row - 1) * spacing
    )
    fluid_vel = np.zeros_like(fluid_pos)
    fluid_vel[breach_mask, 1] = u_inflow

    available_head_m = float(surface_z - np.min(bed))
    energy_bound_m_s = float(np.sqrt(2.0 * GRAVITY * max(available_head_m, 0.0)))
    # GenCase's default speedsystem is the dam-break speed sqrt(g h); h is taken
    # as the full available head over this window, not the reservoir depth,
    # because the released water falls that far and c0 must stay ~20x any flow speed.
    speed_system = max(np.sqrt(GRAVITY * max(available_head_m, reservoir_depth_m)), u_inflow, 1.0)
    speed_of_sound = COEF_SOUND * speed_system
    fluid_rho = hydrostatic_density(fluid_pos[:, 2], np.full(fluid_pos.shape[0], surface_z), speed_of_sound)

    work = _run_dir(dam_name)
    case_dir, out_dir = work / "case", work / "out"
    constants = write_case(
        case_dir, [("bed", bed_bound), ("walls", wall_bound)], fluid_pos, fluid_vel, fluid_rho,
        spacing, speed_of_sound, duration_s, time_out_s=duration_s / N_OUTPUT_PARTS,
    )
    n_bound = bed_bound.shape[0] + wall_bound.shape[0]
    n_fluid_initial = fluid_pos.shape[0]

    started = time.perf_counter()
    sph_backend = _run_with_fallback(sph_backend, case_dir, out_dir, timeout_s, dualsphysics_dir)
    wall_clock = time.perf_counter() - started
    run_mode = _run_mode_from_run_out(out_dir)

    domain_length_local = (ny - 1) * spacing
    domain_width_local = (nx - 1) * spacing
    parts = sorted((out_dir / "data").glob("Part_*.bi4"))
    if not parts:
        raise SPHUnavailableError(f"DualSPHysics wrote no particle output: {_run_out_tail(out_dir)}")

    front_time: List[float] = []
    front_position: List[float] = []
    final = None
    try:
        for index, part_path in enumerate(parts):
            wanted = ("Idp", "Posd", "Pos", "Vel") if index == len(parts) - 1 else ("Idp", "Posd", "Pos")
            part = read_part_file(part_path, wanted)
            fluid = part["arrays"]["Idp"] >= n_bound
            y_fluid = part["arrays"]["Pos"][fluid, 1]
            inside = (y_fluid >= 0.0) & (y_fluid <= domain_length_local)
            # Front = 99th percentile of in-domain fluid y (pysph_runner's rule).
            if index > 0 and inside.sum() >= FRONT_MIN_PARTICLES:
                front_time.append(part["time_s"])
                front_position.append(float(np.percentile(y_fluid[inside], 99.0)))
            if index == len(parts) - 1:
                final = part
    finally:
        if not keep_parts:
            _cleanup_parts(out_dir)

    fluid = final["arrays"]["Idp"] >= n_bound
    pos = final["arrays"]["Pos"][fluid].astype(np.float64)
    vel = final["arrays"]["Vel"][fluid].astype(np.float64)
    x, y, z = pos[:, 0].copy(), pos[:, 1].copy(), pos[:, 2].copy()
    u, v, w = vel[:, 0].copy(), vel[:, 1].copy(), vel[:, 2].copy()

    _assert_did_not_diverge(x, y, z, u, v, w, domain_length_local, domain_width_local, bed, spacing)

    speed = np.sqrt(u**2 + v**2 + w**2)
    bed_at_particle = _sample_bed(bed, x, y, spacing)
    depth = np.maximum(0.0, z - bed_at_particle)
    in_domain = (
        (y >= 0.0) & (y <= domain_length_local) & (x >= 0.0) & (x <= domain_width_local)
        & (z >= bed_at_particle - 3.0 * spacing)
    )
    n_excluded = int(n_fluid_initial - x.size)
    depth_in, speed_in = depth[in_domain], speed[in_domain]

    return {
        "x": x, "y": y, "z": z, "u": u, "v": v, "w": w,
        "particle_spacing_m": spacing,
        "particle_volume_m3": spacing**3,
        "particle_mass_kg": constants["particle_mass_kg"],
        "smoothing_length_m": constants["h_m"],
        "speed_of_sound_m_s": float(speed_of_sound),
        "n_fluid": int(n_fluid_initial),
        "n_boundary": int(n_bound),
        "front_time_s": front_time,
        "front_position_m": front_position,
        "front_speed_m_s": (
            (front_position[-1] - front_position[0]) / (front_time[-1] - front_time[0])
            if len(front_time) > 1 and front_time[-1] > front_time[0] else 0.0
        ),
        "max_depth_m": float(np.max(depth_in)) if depth_in.size else 0.0,
        "max_speed_m_s": float(np.max(speed_in)) if speed_in.size else 0.0,
        "n_escaped": int((~in_domain).sum()) + n_excluded,
        "n_excluded": n_excluded,
        "n_in_domain": int(in_domain.sum()),
        "available_head_m": available_head_m,
        "energy_bound_m_s": energy_bound_m_s,
        "front_exited_domain": bool(front_position and front_position[-1] >= 0.98 * domain_length_local),
        "domain_length_m": domain_length_m,
        "domain_width_m": domain_width_m,
        "duration_s": duration_s,
        "reservoir_depth_m": reservoir_depth_m,
        "u_inflow_m_s": u_inflow,
        "wall_clock_s": wall_clock,
        "dam_name": dam_name,
        "bed_drop_m": bed_drop_m,
        "orientation_rot90": int(rotations),
        "engine": "DualSPHysics",
        "engine_label": (
            f"DualSPHysics {DUALSPHYSICS_VERSION} (Wendland quintic, symplectic, DBC) on {sph_backend['label']}"
        ),
        "sph_backend": sph_backend["sph_backend"],
        "sph_backend_label": sph_backend["label"],
        "sph_backend_reason": sph_backend["reason"],
        "solver_run_mode": run_mode,
        "case_dir": str(case_dir),
        "output_dir": str(out_dir),
        "reaches_downstream_gauges": False,
        "coupling": "one-way SWE -> SPH handoff (no feedback)",
    }


def run_still_water_validation(
    depth_m: float = 10.0,
    spacing_m: float = 0.5,
    duration_s: float = 2.0,
    tank_cells: int = 20,
    backend: Optional[str] = "auto",
    dualsphysics_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Hydrostatic gate for DualSPHysics: water at rest in a closed tank must stay at rest.

    Same scene and same returned keys as pysph_runner.run_still_water_validation,
    run through this module's own case writer, so it tests the particle state
    and constants production runs are given.
    """
    sph_backend = resolve_dsph_backend(backend, dualsphysics_dir)
    n_layers = max(4, int(depth_m / spacing_m))
    blocks, fluid_pos = _closed_tank(max(4, int(tank_cells)), n_layers, spacing_m)
    surface_before = float(fluid_pos[:, 2].max())
    c0 = COEF_SOUND * np.sqrt(GRAVITY * depth_m)
    rho0 = hydrostatic_density(fluid_pos[:, 2], np.full(fluid_pos.shape[0], surface_before), c0)

    work = _run_dir("stillwater")
    case_dir, out_dir = work / "case", work / "out"
    write_case(case_dir, blocks, fluid_pos, np.zeros_like(fluid_pos), rho0, spacing_m, c0,
               duration_s, time_out_s=duration_s)
    n_bound = blocks[0][1].shape[0]
    sph_backend = _run_with_fallback(sph_backend, case_dir, out_dir, 1800.0, dualsphysics_dir)
    parts = sorted((out_dir / "data").glob("Part_*.bi4"))
    final = read_part_file(parts[-1], ("Idp", "Posd", "Pos", "Vel", "Rhop"))
    _cleanup_parts(out_dir)

    fluid = final["arrays"]["Idp"] >= n_bound
    z = final["arrays"]["Pos"][fluid, 2].astype(np.float64)
    vel = final["arrays"]["Vel"][fluid].astype(np.float64)
    rho = final["arrays"]["Rhop"][fluid].astype(np.float64)
    speed = np.sqrt((vel**2).sum(axis=1))
    tait_b = RHO_WATER * c0**2 / TAIT_GAMMA
    pressure = tait_b * ((rho / RHO_WATER) ** TAIT_GAMMA - 1.0)

    surface = float(np.percentile(z, 98))
    depth_below = surface - z
    interior = (depth_below > 2.0 * spacing_m) & (depth_below < depth_m - 2.0 * spacing_m)
    expected = RHO_WATER * GRAVITY
    distinct_layers = int(np.unique(np.round(z[interior] / spacing_m)).size)
    if interior.sum() >= 50 and distinct_layers >= 4:
        slope = float(np.polyfit(depth_below[interior], pressure[interior], 1)[0])
        slope_error_pct = 100.0 * abs(slope - expected) / expected
        slope_note = f"fitted over {int(interior.sum())} particles in {distinct_layers} layers"
    else:
        slope, slope_error_pct = None, None
        slope_note = (f"NOT MEASURED: only {int(interior.sum())} interior particles across "
                      f"{distinct_layers} layers.")

    return {
        "max_speed_m_s": float(np.max(speed)),
        "mean_speed_m_s": float(np.mean(speed)),
        "surface_drop_m": surface_before - surface,
        "hydrostatic_slope": slope,
        "expected_slope": expected,
        "slope_error_pct": slope_error_pct,
        "slope_note": slope_note,
        "density_error_pct": 100.0 * float(np.max(np.abs(rho - RHO_WATER))) / RHO_WATER,
        "all_finite": bool(np.all(np.isfinite(z)) and np.all(np.isfinite(rho))),
        "n_fluid": int(z.size),
        "n_excluded": int(fluid_pos.shape[0] - z.size),
        "spacing_m": spacing_m,
        "duration_s": duration_s,
        "engine": "DualSPHysics",
        "sph_backend": sph_backend["sph_backend"],
        "sph_backend_label": sph_backend["label"],
        "sph_backend_reason": sph_backend["reason"],
        "solver_run_mode": _run_mode_from_run_out(out_dir),
    }
