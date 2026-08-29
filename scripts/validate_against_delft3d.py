"""
Validate JalRaksha against the real Delft3D FM kernel.

    python scripts/validate_against_delft3d.py --case ritter
    python scripts/validate_against_delft3d.py --case tehri
    python scripts/validate_against_delft3d.py --case both

Writes a comparison figure and a metrics JSON under data/validation/, which is
what the SIH validation slide is made from.

The Ritter case is the one that can be scored: it has an exact solution, so
both engines are measured against theory rather than against each other. The
Tehri case has no ground truth and is reported as engine-vs-engine agreement,
labelled as such.

Requires a Delft3D FM kernel. If none is installed the script says so and exits
non-zero rather than fabricating a comparison — see CLAUDE.md on fallbacks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from jalraksha.validation.delft3d_benchmark import (  # noqa: E402
    BenchmarkUnavailableError, compare_ritter,
)


def _plot_ritter(result: dict, out_path: Path) -> Path:
    """Depth profile: both engines against the exact solution."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = result["x"]
    fig, (ax, ax_err) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]})

    ax.plot(x, result["analytical"], color="k", lw=2.5, label="Ritter (1892) exact", zorder=3)
    ax.plot(x, result["delft3d"], color="#E53935", lw=1.8, ls="--",
            label="Delft3D FM (dflowfm-cli)", zorder=4)
    ax.plot(x, result["jalraksha"], color="#1565C0", lw=1.8, ls="-.",
            label="JalRaksha 2D SWE", zorder=5)

    # Shade the boundary cells excluded from scoring, so the reader can see
    # exactly what was and was not counted rather than taking it on trust.
    margin = result.get("boundary_margin_cells", 0)
    if margin:
        span = margin * result["dx_m"]
        for lo, hi in ((x.min(), x.min() + span), (x.max() - span, x.max())):
            ax.axvspan(lo, hi, color="grey", alpha=0.18, zorder=1)
            ax_err.axvspan(lo, hi, color="grey", alpha=0.18, zorder=1)
        ax.text(x.min() + span, result["h_left_m"] * 0.55,
                f"  boundary cells excluded\n  from scoring ({margin} each end)",
                fontsize=8, color="#555", va="center")

    ax.axvline(0.0, color="grey", lw=1, ls=":")
    ax.text(0.0, result["h_left_m"] * 0.97, " dam", color="grey", va="top", fontsize=9)
    ax.axhline(result["exact_depth_at_dam_m"], color="grey", lw=0.8, ls=":")
    ax.text(x.min(), result["exact_depth_at_dam_m"], f"  4h₀/9 = "
            f"{result['exact_depth_at_dam_m']:.2f} m", color="grey",
            va="bottom", fontsize=9)

    ax.set_ylabel("water depth (m)")
    ax.set_title(
        f"Ritter dam-break — h₀ = {result['h_left_m']:.0f} m, t = {result['t_end_s']:.0f} s, "
        f"Δx = {result['dx_m']:.0f} m, frictionless flat bed")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)

    ax_err.plot(x, result["jalraksha"] - result["analytical"], color="#1565C0",
                lw=1.2, label="JalRaksha − exact")
    ax_err.plot(x, result["delft3d"] - result["analytical"], color="#E53935",
                lw=1.2, label="Delft3D FM − exact")
    ax_err.axhline(0.0, color="k", lw=0.8)
    ax_err.set_xlabel("distance from dam (m)")
    ax_err.set_ylabel("error (m)")
    ax_err.legend(loc="upper right", fontsize=9)
    ax_err.grid(alpha=0.3)

    jr = result["jalraksha_vs_analytical"]
    d3 = result["delft3d_vs_analytical"]
    fig.text(0.01, 0.01,
             f"RMSE vs exact —  JalRaksha {jr['rmse_m']:.4f} m   |   "
             f"Delft3D FM {d3['rmse_m']:.4f} m   |   "
             f"engines agree to {result['engine_agreement']['rmse_m']:.4f} m RMSE",
             fontsize=9, color="#333")

    fig.tight_layout(rect=[0, 0.03, 1, 1])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def _jsonable(value):
    """NumPy arrays and scalars into something json can write."""
    if isinstance(value, np.ndarray):
        return [round(float(v), 6) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def run_ritter(out_dir: Path, dflowfm_path: str | None) -> dict:
    print("=== Ritter dam-break: JalRaksha vs Delft3D FM vs exact solution ===")
    result = compare_ritter(out_dir / "ritter_model", dflowfm_path=dflowfm_path)

    jr = result["jalraksha_vs_analytical"]
    d3 = result["delft3d_vs_analytical"]
    print(f"  exact depth at dam (4h0/9) : {result['exact_depth_at_dam_m']:.3f} m")
    print(f"  JalRaksha   vs exact  RMSE : {jr['rmse_m']:.4f} m   "
          f"(h@dam {jr['depth_at_dam_m']:.3f} m)")
    print(f"  Delft3D FM  vs exact  RMSE : {d3['rmse_m']:.4f} m   "
          f"(h@dam {d3['depth_at_dam_m']:.3f} m)")
    print(f"  engine-vs-engine      RMSE : {result['engine_agreement']['rmse_m']:.4f} m")

    figure = _plot_ritter(result, out_dir / "ritter_validation.png")
    print(f"  figure: {figure}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", choices=["ritter", "tehri", "both"],
                        default="ritter")
    parser.add_argument("--dflowfm", default=None,
                        help="Path to dflowfm-cli.exe (else auto-discovered).")
    parser.add_argument("--out", default=str(REPO_ROOT / "data" / "validation"))
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict = {}
    try:
        if args.case in ("ritter", "both"):
            results["ritter"] = run_ritter(out_dir, args.dflowfm)
        if args.case in ("tehri", "both"):
            from jalraksha.validation.delft3d_benchmark import compare_tehri
            results["tehri"] = compare_tehri(out_dir / "tehri_model",
                                             dflowfm_path=args.dflowfm)
            _report_tehri(results["tehri"], out_dir)
    except BenchmarkUnavailableError as exc:
        # Not a traceback: this is an expected, actionable state.
        print(f"\nCannot validate against Delft3D: {exc}", file=sys.stderr)
        return 2

    metrics_path = out_dir / "validation_metrics.json"
    metrics_path.write_text(json.dumps(_jsonable(results), indent=2), encoding="utf-8")
    print(f"\nmetrics: {metrics_path}")
    return 0


def _report_tehri(result: dict, out_dir: Path) -> None:
    """Print and plot the Tehri gauge comparison."""
    from jalraksha.validation.delft3d_benchmark import plot_tehri_gauges

    print("\n=== Tehri dam-break: JalRaksha vs Delft3D FM (no ground truth) ===")
    for row in result["gauges"]:
        jr = row["jalraksha_arrival_s"]
        d3 = row["delft3d_arrival_s"]
        fmt = lambda v: f"{v / 60.0:6.1f} min" if v is not None else "      —   "
        print(f"  {row['name']:<12} JalRaksha {fmt(jr)}   Delft3D {fmt(d3)}")
    figure = plot_tehri_gauges(result, out_dir / "tehri_validation.png")
    print(f"  figure: {figure}")


if __name__ == "__main__":
    raise SystemExit(main())
