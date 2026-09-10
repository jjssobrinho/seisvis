Milestone v5.1 — Depth Domain Foundation
Prerequisite: v44-done.

Model and I/O layer only. Teaches Dataset that a file may live in
the depth domain, detects it from SU headers, and lets `.sv`
declare it explicitly for any file. No UI in this milestone: the
Model Window arrives in v5.2. Everything here is pytest-covered.

Rationale: velocity models and other image-domain data are plotted
in metres, not milliseconds. Rather than branch the time-domain
render path (see CLAUDE.md's locked time-axis convention), depth
data is routed to a separate window with its own axis convention.
This milestone builds the model layer that routing will consult.

---

Domain model

New file `src/seisvis/models/vertical_domain.py`:

```python
VerticalDomain = Literal["time", "depth"]

# Seismic Unix ISSEISMIC(): trid values that mean "time domain".
# Everything else (130 DEPTH, 121 KT, 122 KOMEGA, ...) is not.
SEISMIC_TRIDS: frozenset[int] = frozenset({0, 1, 2, 3})

def domain_for_trid(trid: int) -> VerticalDomain: ...

@dataclass(frozen=True)
class DepthGeometry:
    dz: float                    # vertical sample spacing, metres (SU d1)
    z0: float                    # first sample depth, metres    (SU f1)
    dx: float                    # trace spacing, metres         (SU d2)
    x0: float                    # first trace position, metres  (SU f2)
    value_unit: str | None = None   # "m/s" etc; labels the crosshair readout
```

`domain_for_trid` mirrors SU's `ISSEISMIC` macro exactly: a short
allow-list of seismic trids, everything else is image domain.
Pure functions, no Qt, no I/O.

Dataset fields

Two additions, both defaulting to the time-domain behaviour that
exists today, so no existing code path changes:

```
vertical_domain: VerticalDomain = "time"
depth_geometry:  DepthGeometry | None = None    # non-None iff domain == "depth"
```

`sample_interval_ms` keeps its current meaning (milliseconds) and
is untouched. A depth dataset leaves it at whatever the header
gave and nothing reads it — `depth_geometry.dz` is the vertical
spacing for those.

`adopt_from` (the reload path) copies both new fields.

SU float header reads

`io/su_reader.py` currently maps every offset to a signed int
(`"i"`/`"h"`). SU's cwp-local block is float32 and aliases the
SEG-Y standard fields exactly:

| byte | SU (float32) | SEG-Y standard (int32) |
|------|--------------|------------------------|
| 181  | d1           | CDP_X                  |
| 185  | f1           | CDP_Y                  |
| 189  | d2           | INLINE_3D              |
| 193  | f2           | CROSSLINE_3D           |

Add to `_SUHeaderView` a separate accessor — do **not** change
`__getitem__`, which the rest of the app relies on returning int:

```python
def float_at(self, offset: int) -> float:
    """Read a 4-byte IEEE float at a 1-indexed header offset."""
```

Consequence to fix in the same milestone: `HeaderScanWorker` reads
INLINE_3D (189) and CROSSLINE_3D (193) unconditionally, including
for `.su` files, where those bytes are d2/f2 floats. Reading
`d2=5.0` as int32 yields 1084227584. This is benign today only
because d2/f2 are constant per file, so `np.unique(...).size == 1`
keeps the mode out of `available_modes`. Make it explicit: the SU
load path marks INLINE / CROSSLINE unavailable rather than relying
on that coincidence.

Detection in load_su

After opening the handle, read the first trace header:

```
trid = handle.header[0][segyio.TraceField.TraceIdentificationCode]
domain = domain_for_trid(trid)
```

When `domain == "depth"`, build `DepthGeometry` from `float_at` on
181 / 185 / 189 / 193. SU's own fallbacks, with a `log.warning`
naming the field, matching suximage's behaviour:

- `dz == 0` → 1.0
- `dx == 0` → 1.0
- `z0`, `x0` → 0.0 when absent

`log.info` the decision and the trid that drove it, always. When a
file opens with the wrong axis, that log line is the first thing
to look at.

`load_segy` gets no trid detection: SEG-Y Rev 2's trid=25 exists
but is vanishingly rare in practice, and SEG-Y has no d1/d2 in any
byte, so a declared domain without geometry is useless. SEG-Y
depth data arrives through `.sv` only.

`.sv` schema v3

`CURRENT_SCHEMA_VERSION = 3`. New optional block:

```json
"domain": {
  "kind": "depth",
  "dz": 5.0,  "z0": 0.0,
  "dx": 12.5, "x0": 0.0,
  "value_unit": "m/s"
}
```

Migration is additive: a v2 sidecar has no `"domain"` key, which
reads as `kind: "time"`. `from_json` keeps accepting v1 and v2
unchanged; only the version ceiling moves.

Precedence in both loaders, strongest first:

```
.sv domain  >  SU trid + d1/f1/d2/f2  >  "time" (default)
```

A `.sv` declaring `kind: "depth"` must carry dz and dx; missing
either is a load warning and the declaration is ignored (falls
through to the next rule) rather than producing a geometry with
silent 1.0 defaults the user never asked for.

Compatibility

`are_toggle_compatible(a, b, sort_config)` returns False when
either dataset has `vertical_domain == "depth"`. Depth datasets do
not enter toggle groups — that separation is the entire point of
the design. The catalog's drag-onto-canvas and multi-select-open
paths must honour the same rule; until v5.2 gives them somewhere
to go, attempting to open one reports "depth-domain dataset;
Model Window arrives in v5.2" on the status bar.

---

Tests

- `test_vertical_domain.py` — `domain_for_trid` table: 0/1/2/3 →
  "time"; 25, 121, 122, 130, 201 → "depth". `DepthGeometry` is
  frozen and hashable.
- `test_su_reader_floats.py` — `float_at` returns d1/f1/d2/f2 at
  181/185/189/193 in both endians; `__getitem__` at those same
  offsets still returns the (garbage) int, proving the accessors
  stay separate.
- `test_su_domain_detection.py` — a synthetic `.su` with trid=130
  and d1/d2 set loads as depth with the right geometry; trid=1
  loads as time with `depth_geometry is None`; dz=0 falls back to
  1.0 and warns.
- `test_su_inline_unavailable.py` — a `.su` file never reports
  INLINE / CROSSLINE in `available_modes`.
- `test_sv_schema_migration.py` (extend) — v2 sidecar → domain
  "time"; v3 round-trips the domain block; v4 still raises.
- `test_sv_domain_override.py` — `.sv` declaring depth wins over
  trid=1 on a `.su`; declares depth on a `.segy`; a declaration
  missing dz is ignored with a warning.
- `test_compatibility_depth.py` — depth dataset refused from a
  toggle group in both directions.

Out of scope for v5.1

Model Window, ModelView, catalog routing and marker (v5.2);
Domain panel in the Header Inspector (v5.3); multi-model members
and flicker (v5.4). No rendering code in this milestone.
