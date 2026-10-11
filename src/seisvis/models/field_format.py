"""How a header value is written for the user.

Header fields are ints (every SEG-Y field) or floats (named-column backends).
Ints print exactly as they always have. A float holding a whole number prints
as that integer — so ``100.0`` reads ``100``, and an int field carried as
float64 (the attribute plot's arrays) reads exactly as the int did. Other
floats print to ten significant digits.
"""

from __future__ import annotations

import math
from numbers import Integral, Real

# Shown where a value cannot exist (a NaN float).
NO_VALUE = "—"


def format_header_value(value: int | float) -> str:
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real):
        v = float(value)
        if math.isnan(v):
            return NO_VALUE
        if v.is_integer() and abs(v) < 2**53:
            return str(int(v))
        return f"{v:.10g}"
    return str(value)


__all__ = ["NO_VALUE", "format_header_value"]
