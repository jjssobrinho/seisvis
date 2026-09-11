"""Spelling of the crosshair readout.

Extracted from :class:`SeismicView` so it can be tested: the string building
used to live inside a 60-line if/elif reachable only through a Qt widget.
The view still decides *which* values to pass — that needs the dataset and
the group index — but no longer how they are written.

Layout, left to right:

```
CDP 712, Channel 38 | offset 1250 | SP 340 | t = 4751.84 ms | amp = 0.0524
└─ primary  └─ secondary  └───── extras ─────┘
```

Extras sit between the key fields and the time because that is where the
hierarchy reads: what trace this is, then what else is known about it, then
where in the trace and how strong.
"""

from __future__ import annotations

# Shown for an extra whose value has not arrived yet. A field that simply
# vanished while its read was in flight would read as a broken checkbox.
PENDING = "…"


def format_value(value: int | None) -> str:
    return PENDING if value is None else str(value)


def format_crosshair(
    *,
    primary: tuple[str, int] | None = None,
    secondary: tuple[str, int] | None = None,
    extras: list[tuple[str, int | None]] | None = None,
    trace: int,
    t_ms: float,
    amp: float | None,
) -> str:
    """Build the readout line.

    ``primary`` and ``secondary`` are ``(display name, value)``; with no
    committed sort both are None and the line falls back to the raw trace
    index. ``extras`` are ``(display name, value)`` where a None value means
    the read is still in flight.
    """
    amp_str = f"{amp:.4g}" if amp is not None else "—"
    t_str = f"{t_ms:.2f}"

    if primary is None:
        head = f"Trace {trace}"
    elif secondary is None:
        head = f"{primary[0]} {primary[1]}"
    else:
        head = f"{primary[0]} {primary[1]}, {secondary[0]} {secondary[1]}"

    parts = [head]
    for name, value in extras or []:
        parts.append(f"{name} {format_value(value)}")
    parts.append(f"t = {t_str} ms")
    parts.append(f"amp = {amp_str}")
    return " | ".join(parts)


__all__ = ["PENDING", "format_crosshair", "format_value"]
