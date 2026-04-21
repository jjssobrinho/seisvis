Milestone M7 — Toolbar Wire-Up
Prerequisite: m6-done.
Processing operations
In src/seismic_viz/processing/:

gain.py: ConstantGain(db: float) with
apply(arr) -> arr and pad_samples = 0.
agc.py: AGC(window_ms, enabled) with
apply(arr, sample_interval_ms) -> arr — windowed RMS
normalization along time axis;
pad_samples = ceil(window_ms / sample_interval_ms).
filters.py: Bandpass(low_hz, high_hz, order, enabled) with
scipy.signal.butter + sosfiltfilt;
pad_samples ≈ 3 * order / (low_hz * sample_interval_ms / 1000)
clamped to a sane maximum.

ProcessingChain
Replace the M3 identity chain with an ordered
[ConstantGain, AGC, Bandpass], each togglable.
pad_samples = sum of enabled ops' budgets.
apply(arr, sample_interval_ms) runs each enabled op in order.
Stable hash() for cache keying.
Active group controller
src/seismic_viz/controllers/active_group_controller.py:

Holds references to the project and the global toolbar.
Subscribes to every toolbar signal (colormap, clip, gain,
bandpass, AGC).
For each signal, reads active group's edit_target_index and
link_all:

link_all == True: applies to every member.
Otherwise: applies to members[edit_target_index] only.


On active_toggle_group_changed / edit_target_changed /
member_added / member_removed: rebinds toolbar widgets to
the current target's values using blockSignals(True). No
phantom emissions.
Default link_all: True on groups where every member is
compatible with the reference; False otherwise.

Edit target selector
src/seismic_viz/ui/toolbar/edit_target_selector.py:
[1] [2] … [All] exclusive button group, rebuilt on member-count
changes or active-group changes. Emits
target_changed(index, link_all). Beyond 12 members, arrange
buttons in two rows — never hide any.
Toolbar groups
In src/seismic_viz/ui/toolbar/:

appearance_group.py: colormap QComboBox (seismic, RdBu,
gray, petrel); dual-handle clip percentile slider (1–99);
gain QSlider dB (−40 to +40).
processing_group.py: bandpass enable + low/high/order
spinboxes; AGC enable + window ms spinbox.
Composed in global_toolbar.py with separators plus the edit
target selector on the right.

Colormaps
src/seismic_viz/utils/colormaps.py: get_colormap(name) -> np.ndarray[(256, 4), uint8] for the four supported names.
Applied via ImageItem.setLookupTable.
Cache and workers

Slice cache key already includes processing-chain hash; edits
invalidate the target member's cache (or all when link_all).
Run the chain inside SliceWorker when bandpass or AGC is
enabled on slices > 500k samples; otherwise inline.

Reset button
Small "Reset target" button on the right of the toolbar clears
the current target(s) — default DisplayState, empty
ProcessingChain. With link_all, resets every member.
Tests

tests/test_processing.py: each op on known inputs (bandpass
rejects DC; AGC on a ramp → near-constant envelope).
tests/test_controller.py: link_all == True routes to every
member; link_all == False only to target; member removal
clamps edit_target_index; active-group switch rebinds without
phantom emits.

On completion: commit feat: M7 toolbar wire-up with N-way edit target, tag m7-done, stop.
