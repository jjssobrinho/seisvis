"""Smoke tests — import-level checks, no Qt instance required."""


def test_import_app() -> None:
    import seisvis.app  # noqa: F401


def test_import_subpackages() -> None:
    import seisvis.controllers  # noqa: F401
    import seisvis.io  # noqa: F401
    import seisvis.models  # noqa: F401
    import seisvis.processing  # noqa: F401
    import seisvis.services  # noqa: F401
    import seisvis.utils  # noqa: F401
    import seisvis.workers  # noqa: F401
