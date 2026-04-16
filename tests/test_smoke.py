"""Smoke tests — import-level checks, no Qt instance required."""


def test_import_app() -> None:
    import seismic_viz.app  # noqa: F401


def test_import_subpackages() -> None:
    import seismic_viz.controllers  # noqa: F401
    import seismic_viz.io  # noqa: F401
    import seismic_viz.models  # noqa: F401
    import seismic_viz.processing  # noqa: F401
    import seismic_viz.services  # noqa: F401
    import seismic_viz.utils  # noqa: F401
    import seismic_viz.workers  # noqa: F401
