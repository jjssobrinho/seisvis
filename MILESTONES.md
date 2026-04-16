Milestone M1 — Skeleton
Initialize a uv project with dependencies PySide6, pyqtgraph, segyio,
numpy, scipy, pytest, ruff, pre-commit. Create the directory skeleton
under src/seismic_viz/ including subpackages models/, io/,
processing/, services/, controllers/, workers/, ui/,
ui/toolbar/, ui/panels/, ui/dialogs/, ui/widgets/, utils/,
plus tests/ with a fixtures/ folder.
Implement src/seismic_viz/__main__.py and src/seismic_viz/app.py
that bootstrap a QApplication and show a QMainWindow laid out as:

A top toolbar region (a QWidget with QHBoxLayout) containing
three labeled placeholder groups: "Appearance", "Processing",
"Edit Target". All widgets inside are disabled.
Below the toolbar, a horizontal QSplitter whose left side is a
vertical QSplitter (top-left = Catalog placeholder,
bottom-left = Viewport Manager placeholder) and whose right side
is a single vertical QWidget placeholder labeled "Display Canvas".
The Display Canvas placeholder reserves space at the bottom for
the future Group Command Bar (an empty disabled widget for now).

Menu bar with File → Open (placeholder QAction, not wired) and
File → Exit. Status bar. Configure Python logging with both a console
handler and a rotating file handler writing to ./logs/seismic_viz.log.
Configure ruff (line length 100, target py311) and pre-commit with
ruff-check, ruff-format, and trailing-whitespace hooks.
Create an empty CHANGELOG.md with an "## [M1] Skeleton" section
(to be filled on completion).
Verify by running uv run python -m seismic_viz — the window must
launch, the toolbar must stay pinned at the top when resizing, and
the three-region split must reflow correctly.
On completion: fill in the CHANGELOG.md section, commit with
feat: M1 skeleton, tag m1-done, stop.
