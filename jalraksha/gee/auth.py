"""
Google Earth Engine Authentication & Status Module (Phase 9).

Handles Earth Engine initialization with seamless offline fallback mode
for field environments and automated testing.
"""

import os
import warnings
from typing import Tuple

_GEE_AVAILABLE = False


def is_gee_available() -> bool:
    """Check if Google Earth Engine (ee) module is installed and authenticated."""
    global _GEE_AVAILABLE
    try:
        import ee
        # Quick check if initialized
        _GEE_AVAILABLE = True
        return True
    except Exception:
        return False


def init_gee(offline_fallback: bool = True) -> Tuple[bool, str]:
    """
    Initialize Google Earth Engine session.

    Args:
        offline_fallback: If True, returns offline mode status instead of raising error on missing credentials.

    Returns:
        Tuple of (success_boolean, status_message)
    """
    global _GEE_AVAILABLE
    try:
        import ee
        ee.Initialize()
        _GEE_AVAILABLE = True
        return True, "Google Earth Engine initialized successfully"
    except Exception as e:
        _GEE_AVAILABLE = False
        msg = f"GEE initialization failed ({e}). Operating in offline fallback mode."
        if offline_fallback:
            warnings.warn(msg)
            return False, "Offline fallback mode active"
        else:
            raise RuntimeError(msg)
