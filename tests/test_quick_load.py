"""Quick-load by full path: the path check and the catalog entry point.

Covers the pure check behind the dialog's light (`services/quick_load.py`)
and the wiring that makes the action reachable from a right-click on the
catalog's "Loaded" row.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from seisvis.models.project import Project  # noqa: E402
from seisvis.services.quick_load import (  # noqa: E402
    check_path,
    normalize_path_text,
    resolve_path_text,
    split_path_lines,
)
from seisvis.ui.dialogs.quick_load_dialog import (  # noqa: E402
    _MIN_WIDTH,
    _SCREEN_FRACTION,
    QuickLoadDialog,
    target_width,
)
from seisvis.ui.panels.catalog_panel import (  # noqa: E402
    GROUP_DERIVED,
    GROUP_LOADED,
    CatalogPanel,
)


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# --- check_path ---


def test_existing_segy_reads_ok(segy_2d: Path) -> None:
    check = check_path(str(segy_2d))
    assert check.state == "ok"
    assert check.ok
    assert check.label == "ok"
    assert check.path == segy_2d


def test_existing_su_reads_ok(su_line: Path) -> None:
    assert check_path(str(su_line)).ok


def test_missing_file_reads_not_found(tmp_path: Path) -> None:
    check = check_path(str(tmp_path / "nope.segy"))
    assert check.state == "not_found"
    assert check.label == "not found"
    assert not check.ok


def test_blank_text_is_empty_not_an_error() -> None:
    for text in ("", "   ", '""'):
        check = check_path(text)
        assert check.state == "empty"
        assert check.label == ""
        assert check.path is None


def test_directory_is_not_a_file(tmp_path: Path) -> None:
    check = check_path(str(tmp_path))
    assert check.state == "not_a_file"
    assert not check.ok


def test_existing_file_with_unsupported_suffix(tmp_path: Path) -> None:
    other = tmp_path / "notes.txt"
    other.write_text("not seismic")
    check = check_path(str(other))
    assert check.state == "unsupported"
    assert not check.ok


def test_surrounding_quotes_and_whitespace_are_stripped(segy_2d: Path) -> None:
    assert check_path(f'  "{segy_2d}"  ').ok
    assert check_path(f"'{segy_2d}'").ok
    assert normalize_path_text(f' "{segy_2d}" ') == str(segy_2d)


def test_tilde_expands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, su_line: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = home / "line.su"
    target.write_bytes(su_line.read_bytes())
    monkeypatch.setenv("HOME", str(home))
    assert resolve_path_text("~/line.su") == target
    assert check_path("~/line.su").ok


def test_suffix_check_is_case_insensitive(tmp_path: Path, segy_2d: Path) -> None:
    upper = tmp_path / "LINE.SGY"
    upper.write_bytes(segy_2d.read_bytes())
    assert check_path(str(upper)).ok


# --- dialog ---


def test_dialog_light_tracks_the_text(gui_app, segy_2d: Path, tmp_path: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog()
    assert dlg.rows[0].light.text == ""
    assert dlg.paths() == []

    dlg.set_path_text(str(tmp_path / "missing.segy"))
    assert dlg.rows[0].light.text == "not found"
    assert dlg.paths() == []

    dlg.set_path_text(str(segy_2d))
    assert dlg.rows[0].light.text == "ok"
    assert dlg.paths() == [segy_2d]
    dlg.deleteLater()


def test_dialog_load_button_follows_validity(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog()
    button = _load_button(dlg)
    assert not button.isEnabled()
    dlg.set_path_text(str(segy_2d))
    assert button.isEnabled()
    dlg.set_path_text("/definitely/not/here.segy")
    assert not button.isEnabled()
    dlg.deleteLater()


def test_dialog_accepts_an_initial_path(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog(initial=str(segy_2d))
    assert dlg.rows[0].light.text == "ok"
    assert dlg.paths() == [segy_2d]
    dlg.deleteLater()


# --- multiple rows ---


def _load_button(dlg: QuickLoadDialog):  # noqa: ANN202
    from PySide6.QtWidgets import QDialogButtonBox

    return dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Open)


def test_enter_on_the_last_filled_row_opens_a_new_one(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog(initial=str(segy_2d))
    dlg.show()
    assert len(dlg.rows) == 1
    dlg.rows[0].edit.returnPressed.emit()
    assert len(dlg.rows) == 2
    assert dlg.rows[1].text() == ""
    assert dlg.focusWidget() is dlg.rows[1].edit
    dlg.deleteLater()


def test_enter_on_a_middle_row_moves_on_without_adding(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog(initial=str(segy_2d))
    dlg.show()
    dlg.add_row(str(segy_2d))
    dlg.rows[0].edit.returnPressed.emit()
    assert len(dlg.rows) == 2
    assert dlg.focusWidget() is dlg.rows[1].edit
    dlg.deleteLater()


def test_enter_on_a_trailing_blank_row_accepts(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog(initial=str(segy_2d))
    dlg.add_row("")
    accepted: list[int] = []
    dlg.accepted.connect(lambda: accepted.append(1))
    dlg.rows[1].edit.returnPressed.emit()
    assert len(dlg.rows) == 2  # no extra row
    assert accepted == [1]
    dlg.deleteLater()


def test_paths_collects_every_valid_row_in_order(
    gui_app,  # noqa: ARG001
    segy_2d: Path,
    su_line: Path,
) -> None:
    dlg = QuickLoadDialog()
    dlg.set_paths([str(su_line), str(segy_2d)])
    assert dlg.paths() == [su_line, segy_2d]
    dlg.deleteLater()


def test_blank_rows_are_skipped_not_counted(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog()
    dlg.set_paths([str(segy_2d), "", "   "])
    assert dlg.paths() == [segy_2d]
    assert _load_button(dlg).isEnabled()
    dlg.deleteLater()


def test_duplicate_rows_load_once(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog()
    dlg.set_paths([str(segy_2d), str(segy_2d)])
    assert dlg.paths() == [segy_2d]
    dlg.deleteLater()


def test_one_bad_row_blocks_the_load_and_is_named(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog()
    dlg.set_paths([str(segy_2d), "/no/such/file.segy"])
    assert not _load_button(dlg).isEnabled()
    status = dlg.findChild(QLabel, None)
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    assert any("line 2" in t for t in texts), texts
    assert status is not None

    # Clearing the offending row unblocks it.
    dlg.set_path_text("", 1)
    assert _load_button(dlg).isEnabled()
    dlg.deleteLater()


def test_removing_a_row_drops_its_path(gui_app, segy_2d: Path, su_line: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog()
    dlg.set_paths([str(segy_2d), str(su_line)])
    dlg.remove_row(dlg.rows[0])
    assert len(dlg.rows) == 1
    assert dlg.paths() == [su_line]
    dlg.deleteLater()


def test_the_last_row_is_cleared_rather_than_removed(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog(initial=str(segy_2d))
    dlg.remove_row(dlg.rows[0])
    assert len(dlg.rows) == 1
    assert dlg.rows[0].text() == ""
    assert dlg.paths() == []
    dlg.deleteLater()


# --- multi-line paste ---


def test_split_path_lines_drops_blanks_and_decoration() -> None:
    text = '/a/one.segy\n  "/b/two.su"  \n\n/c/three.sgy\n'
    assert split_path_lines(text) == ["/a/one.segy", "/b/two.su", "/c/three.sgy"]


def test_split_path_lines_handles_crlf_and_lone_cr() -> None:
    assert split_path_lines("/a.segy\r\n/b.su\r/c.sgy") == ["/a.segy", "/b.su", "/c.sgy"]


def test_split_path_lines_of_one_path_is_one_entry() -> None:
    assert split_path_lines("  /a/one.segy\n") == ["/a/one.segy"]
    assert split_path_lines("   ") == []


def _paste(row, text: str = "", urls: list[str] | None = None) -> None:  # noqa: ANN001
    """Paste *text* (or file *urls*) into a row, through the real clipboard.

    ``QLineEdit.paste`` is the route every paste gesture ends at, so going
    through it exercises what Ctrl+V, the context menu and a middle-click
    all do.
    """
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtWidgets import QApplication

    clipboard = QApplication.clipboard()
    if urls is not None:
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(u) for u in urls])
        clipboard.setMimeData(data)
    else:
        clipboard.setText(text)
    row.edit.paste()


def test_pasting_several_paths_opens_a_row_each(
    gui_app,  # noqa: ARG001
    segy_2d: Path,
    su_line: Path,
) -> None:
    dlg = QuickLoadDialog()
    _paste(dlg.rows[0], f"{segy_2d}\n{su_line}\n")
    assert len(dlg.rows) == 2
    assert dlg.paths() == [segy_2d, su_line]
    dlg.deleteLater()


def test_pasting_one_path_stays_in_its_row(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog()
    _paste(dlg.rows[0], str(segy_2d))
    assert len(dlg.rows) == 1
    assert dlg.paths() == [segy_2d]
    dlg.deleteLater()


def test_pasting_into_a_middle_row_keeps_the_order(
    gui_app,  # noqa: ARG001
    segy_2d: Path,
    su_line: Path,
    tmp_path: Path,
) -> None:
    last = tmp_path / "last.su"
    last.write_bytes(su_line.read_bytes())
    dlg = QuickLoadDialog(initial=str(segy_2d))
    dlg.add_row(str(last))
    _paste(dlg.rows[0], f"\n{su_line}\n{su_line}\n")  # pasted at the end of row 1's text
    assert [r.text() for r in dlg.rows][1:3] == [str(su_line), str(su_line)]
    assert dlg.rows[3].text() == str(last)
    dlg.deleteLater()


def test_pasting_into_a_half_typed_row_completes_it(
    gui_app,  # noqa: ARG001
    segy_2d: Path,
    su_line: Path,
) -> None:
    dlg = QuickLoadDialog()
    head, tail = str(segy_2d)[:6], str(segy_2d)[6:]
    dlg.set_path_text(head)
    dlg.rows[0].edit.setCursorPosition(len(head))
    _paste(dlg.rows[0], f"{tail}\n{su_line}")
    assert dlg.rows[0].text() == str(segy_2d)
    assert dlg.paths() == [segy_2d, su_line]
    dlg.deleteLater()


def test_pasted_files_from_a_file_manager_arrive_as_urls(
    gui_app,  # noqa: ARG001
    segy_2d: Path,
    su_line: Path,
) -> None:
    dlg = QuickLoadDialog()
    _paste(dlg.rows[0], urls=[str(segy_2d), str(su_line)])
    assert dlg.paths() == [segy_2d, su_line]
    dlg.deleteLater()


def test_paste_focuses_the_last_row_it_opened(gui_app, segy_2d: Path, su_line: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog()
    dlg.show()
    _paste(dlg.rows[0], f"{segy_2d}\n{su_line}")
    assert dlg.focusWidget() is dlg.rows[-1].edit
    dlg.deleteLater()


# --- width ---


def test_dialog_starts_wide_and_grows_with_the_longest_path(gui_app, tmp_path: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog()
    start = dlg.width()
    screen = dlg.screen()
    cap = int(screen.availableGeometry().width() * _SCREEN_FRACTION) if screen else _MIN_WIDTH
    # Opens at the preferred width, or the screen cap when the display is
    # narrower than that.
    assert start >= min(_MIN_WIDTH, cap)
    deep = tmp_path / ("nested/" * 30) / "survey_line_0007_migrated_final.segy"
    dlg.set_path_text(str(deep))
    assert dlg.width() >= start
    dlg.deleteLater()


def test_width_never_exceeds_the_screen(gui_app, tmp_path: Path) -> None:  # noqa: ARG001
    dlg = QuickLoadDialog()
    dlg.set_path_text(str(tmp_path / ("x" * 4000)))
    screen = dlg.screen()
    if screen is not None:
        assert dlg.width() <= screen.availableGeometry().width()
    dlg.deleteLater()


def test_width_grows_with_the_longest_path() -> None:
    cap = 2400
    short = target_width(300, 120, cap, _MIN_WIDTH)
    long = target_width(1800, 120, cap, short)
    assert short == _MIN_WIDTH  # a short path does not shrink the dialog
    assert long == 1920


def test_width_stops_at_the_cap() -> None:
    assert target_width(9000, 120, 1500, _MIN_WIDTH) == 1500


def test_width_only_grows_while_editing() -> None:
    wide = target_width(1800, 120, 2400, _MIN_WIDTH)
    assert target_width(200, 120, 2400, wide) == wide


def test_a_window_wider_than_the_cap_is_pulled_back() -> None:
    # The one case where the width shrinks: a window left wider than the
    # screen allows comes back to what its contents need, cap-bounded.
    pulled = target_width(200, 120, 1000, 1600)
    assert pulled <= 1000
    assert pulled == _MIN_WIDTH


def test_a_screen_narrower_than_the_preferred_width_wins() -> None:
    cap = _MIN_WIDTH - 200
    assert target_width(0, 0, cap, cap) == cap


# --- catalog entry point ---


def _menu_texts(menu) -> list[str]:  # noqa: ANN001
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_right_click_on_loaded_row_offers_quick_load(gui_app) -> None:  # noqa: ARG001
    panel = CatalogPanel(Project())
    index = panel.model.index(GROUP_LOADED, 0, QModelIndex())
    menu = panel.build_context_menu_at(index)
    assert menu is not None
    assert _menu_texts(menu) == ["Load datasets by path…"]
    panel.deleteLater()


def test_quick_load_action_emits_every_chosen_path(
    gui_app,  # noqa: ARG001
    segy_2d: Path,
    su_line: Path,
    monkeypatch,
) -> None:
    import seisvis.ui.dialogs.quick_load_dialog as dialog_module

    class _AcceptingDialog(dialog_module.QuickLoadDialog):
        def exec(self) -> int:
            self.set_paths([str(segy_2d), str(su_line)])
            return 1

    monkeypatch.setattr(dialog_module, "QuickLoadDialog", _AcceptingDialog)

    panel = CatalogPanel(Project())
    emitted: list[list[Path]] = []
    panel.quick_load_requested.connect(emitted.append)
    menu = panel.build_loaded_context_menu()
    menu.actions()[0].trigger()
    assert emitted == [[segy_2d, su_line]]
    panel.deleteLater()


def test_derived_row_has_no_menu(gui_app) -> None:  # noqa: ARG001
    panel = CatalogPanel(Project())
    index = panel.model.index(GROUP_DERIVED, 0, QModelIndex())
    assert panel.build_context_menu_at(index) is None
    panel.deleteLater()


def test_empty_space_with_no_selection_offers_quick_load(gui_app) -> None:  # noqa: ARG001
    panel = CatalogPanel(Project())
    menu = panel.build_context_menu_at(QModelIndex())
    assert menu is not None
    assert _menu_texts(menu) == ["Load datasets by path…"]
    panel.deleteLater()
