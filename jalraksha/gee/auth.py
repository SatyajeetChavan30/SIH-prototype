"""
Google Earth Engine authentication and status (Phase 9).

Answers one question honestly: **can this process actually query Earth Engine
right now, and if not, why not?**

WHY THIS WAS REWRITTEN. The previous `is_gee_available()` returned True for a
bare successful `import ee`, without ever initializing a session. That was
harmless only while `earthengine-api` was uninstalled. The moment it is
installed — which is now — every caller takes its "live" branch, fails inside
on a missing project or missing credentials, hits a bare `except: pass`, and
returns synthetic `np.random` data labelled as offline. A reader sees plausible
numbers and no indication that nothing was fetched.

So availability here means an actual `ee.Initialize(project=...)` succeeded,
and the failure reason is carried out verbatim rather than collapsed to a
boolean. Earth Engine's own messages are specific and actionable — "Google
Earth Engine API has not been used in project X before or it is disabled",
"no project found", "Please authorize access" — and each names a different fix.

SETUP (all three are required):

    pip install earthengine-api
    earthengine authenticate                      # interactive browser sign-in
    set JALRAKSHA_GEE_PROJECT=<your-gcp-project>  # with the EE API enabled

References:
  - Gorelick, N. et al. (2017) "Google Earth Engine: Planetary-scale geospatial
    analysis for everyone", Remote Sensing of Environment 202:18-27.
"""

from __future__ import annotations

import os
import threading
from typing import Optional, Tuple

#: Environment variable naming the Google Cloud project to bill/authorise
#: Earth Engine against. Earth Engine has required a Cloud project since the
#: 2023 access change, so there is no sensible default to fall back on.
GEE_PROJECT_ENV = "JALRAKSHA_GEE_PROJECT"

# Initialization is a network round-trip, so the outcome is cached. Guarded by a
# lock because FastAPI serves requests from a threadpool and two concurrent
# /gee/latest calls would otherwise both pay for it.
_LOCK = threading.Lock()
_STATUS: Optional[Tuple[bool, str]] = None


def gee_project() -> str:
    """The configured Cloud project, or "" if none is set."""
    return os.environ.get(GEE_PROJECT_ENV, "").strip()


def reset_gee_status() -> None:
    """Forget the cached status. For tests, and after changing the project."""
    global _STATUS
    with _LOCK:
        _STATUS = None


def gee_status(force: bool = False) -> Tuple[bool, str]:
    """
    Whether Earth Engine is usable in this process, and why not if it is not.

    Args:
        force: Re-check even if a previous result is cached.

    Returns:
        (available, reason). `reason` names the PROJECT when available, and
        carries Earth Engine's own error text when not — do not paraphrase it
        into something generic on the way to the user.
    """
    global _STATUS
    with _LOCK:
        if _STATUS is not None and not force:
            return _STATUS
        _STATUS = _probe()
        return _STATUS


def _probe() -> Tuple[bool, str]:
    """Attempt a real Earth Engine session. Never raises."""
    try:
        import ee
    except ImportError as exc:
        return False, (
            f"earthengine-api is not installed ({exc}). "
            f"Install it with: pip install earthengine-api"
        )

    project = gee_project()
    if not project:
        return False, (
            f"{GEE_PROJECT_ENV} is not set. Earth Engine requires a Google "
            f"Cloud project with the Earth Engine API enabled; register a free "
            f"non-commercial one at https://code.earthengine.google.com/register "
            f"and set {GEE_PROJECT_ENV} to its project ID."
        )

    try:
        ee.Initialize(project=project)
    except Exception as exc:
        # Passed through verbatim. EE distinguishes "not authenticated" from
        # "API not enabled on this project" from "project does not exist", and
        # each needs a different action from whoever is reading this.
        return False, f"ee.Initialize(project={project!r}) failed: {exc}"

    return True, f"Earth Engine ready (project={project})"


def is_gee_available() -> bool:
    """
    True only if a real Earth Engine session could be established.

    Kept as a predicate for existing callers, but it is now backed by an actual
    initialization rather than by `import ee` succeeding. Prefer gee_status()
    where the reason matters, which is almost everywhere.
    """
    return gee_status()[0]


def init_gee(offline_fallback: bool = True) -> Tuple[bool, str]:
    """
    Initialize an Earth Engine session.

    Args:
        offline_fallback: If True, report failure instead of raising.

    Returns:
        (success, message) — the message is the real reason on failure.

    Raises:
        RuntimeError: if initialization fails and offline_fallback is False.
    """
    available, reason = gee_status(force=True)
    if available or offline_fallback:
        return available, reason
    raise RuntimeError(reason)
