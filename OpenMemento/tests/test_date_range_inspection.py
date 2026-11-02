from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from memento.domain.media import CaptureTime, MediaAsset, TimestampSource
from memento.library import database
from memento.library.database import MediaLibrary
from memento.ui.date_range_dialog import DateRangeDialog


DAY = date(2026, 7, 12)


def store(library, root, name, capture):
    return library.save_asset(MediaAsset(name, root / (name + ".mp4"), 100,
        datetime.fromisoformat("2026-07-12T00:00:00+00:00"),
        capture_time=CaptureTime(datetime.fromisoformat(capture), TimestampSource.QUICKTIME, 0.9) if capture else None))


def test_page_uses_recorded_dates_inclusive_edges_and_one_preferred_location(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    store(library, tmp_path, "first", "2026-07-12T00:00:00+14:00")
    store(library, tmp_path, "last", "2026-07-12T23:59:59-12:00")
    store(library, tmp_path, "before", "2026-07-11T23:59:59-12:00")
    store(library, tmp_path, "after", "2026-07-13T00:00:00+14:00")
    store(library, tmp_path, "missing", None)
    with library._connection() as db:
        # The offline original remains inspectable; a duplicate is not a row.
        db.execute("UPDATE locations SET available=0 WHERE asset_id='first'")
        db.execute("""INSERT INTO locations(location_id, asset_id, path, path_key, size_bytes, modified_at, last_seen_at)
            SELECT 'copy', asset_id, ?, ?, size_bytes, modified_at, last_seen_at FROM locations WHERE asset_id='last'""",
            (str(tmp_path / "copy.mp4"), str(tmp_path / "copy.mp4").casefold()))
        db.execute("UPDATE locations SET available=0 WHERE location_id<>'copy' AND asset_id='last'")
        # No source location: excluded from both totals, like the existing API.
        db.execute("""INSERT INTO assets(asset_id, created_at, updated_at) VALUES ('orphan', '2026-01-01', '2026-01-01')""")
    page = library.capture_date_page(DAY, DAY, limit=1)
    assert (page.total, page.unknown, page.offset) == (2, 1, 0)
    assert page.assets[0].asset_id == "first"
    last = library.capture_date_page(DAY, DAY, offset=999, limit=1)
    assert last.offset == 1 and len(last.assets) == 1
    assert last.assets[0].asset_id == "last" and last.assets[0].path.name == "copy.mp4"
    assert last.assets[0].capture_time.value.utcoffset().total_seconds() == -12 * 3600
    empty = library.capture_date_page(date(2000, 1, 1), date(2000, 1, 1), offset=999)
    assert (empty.assets, empty.total, empty.unknown, empty.offset) == ((), 0, 1, 0)


@pytest.mark.parametrize("kwargs", [{"offset": -1}, {"offset": True}, {"offset": 1.5},
    {"limit": 0}, {"limit": 501}, {"limit": True}, {"limit": 2.5}])
def test_page_rejects_invalid_bounds(tmp_path, kwargs):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    with pytest.raises(ValueError):
        library.capture_date_page(DAY, DAY, **kwargs)


def test_page_rejects_invalid_date_range(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    for start, end in ((date(2026, 7, 13), DAY), ("2026-07-12", DAY), (datetime(2026, 7, 12), DAY)):
        with pytest.raises(ValueError):
            library.capture_date_page(start, end)


def test_page_counts_and_rows_share_snapshot_during_concurrent_correction(tmp_path, monkeypatch):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    store(library, tmp_path, "known", "2026-07-12T10:00:00")
    store(library, tmp_path, "missing", None)
    connect = library._connect
    changed = []

    def traced_connect():
        db = connect()

        def trace(statement):
            if "SELECT a.*, l.path" in statement and not changed:
                changed.append(True)
                with sqlite3.connect(library.path) as writer:
                    writer.execute("""UPDATE assets SET capture_time='2026-07-12T11:00:00',
                        capture_source='manual', capture_confidence=1 WHERE asset_id='missing'""")

        db.set_trace_callback(trace)
        return db

    monkeypatch.setattr(library, "_connect", traced_connect)
    page = library.capture_date_page(DAY, DAY)
    assert changed
    assert (page.total, page.unknown) == (1, 1)
    assert [asset.asset_id for asset in page.assets] == ["known"]
    updated = library.capture_date_page(DAY, DAY)
    assert (updated.total, updated.unknown, len(updated.assets)) == (2, 0, 2)


def test_twenty_thousand_recordings_use_bounded_pages_and_no_queries_during_paint(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    modified = "2026-07-12T00:00:00+00:00"
    # Equal recording times exercise the stable asset-ID tie breaker.
    with library._connection() as db:
        db.executemany("""INSERT INTO assets(asset_id, capture_time, capture_source, capture_confidence,
            created_at, updated_at) VALUES (?, '2026-07-12T10:00:00', 'quicktime', 0.9, ?, ?)""",
            [(f"asset-{index:05}", modified, modified) for index in range(20_000)])
        db.executemany("""INSERT INTO locations(location_id, asset_id, path, path_key, size_bytes, modified_at, last_seen_at)
            VALUES (?, ?, ?, ?, 100, ?, ?)""", [
                (f"location-{index:05}", f"asset-{index:05}", str(tmp_path / f"{index:05}.mp4"),
                 str(tmp_path / f"{index:05}.mp4").casefold(), modified, modified) for index in range(20_000)])
    connections, materialized = [], []
    connect, convert = library._connect, database._asset_from_row

    def tracked_connect():
        connections.append(1)
        return connect()

    def tracked_convert(row):
        materialized.append(row["asset_id"])
        return convert(row)

    monkeypatch.setattr(library, "_connect", tracked_connect)
    monkeypatch.setattr(database, "_asset_from_row", tracked_convert)
    monkeypatch.setattr(library, "list_assets_in_capture_date_range", lambda *_: pytest.fail("Unbounded read"))
    page = library.capture_date_page(DAY, DAY, limit=DateRangeDialog.PAGE_SIZE)
    dialog = DateRangeDialog(library, DAY, DAY, initial_page=page)
    assert len(connections) == 1 and len(materialized) == 200
    assert dialog.model.rowCount() == 200 and not dialog.previous_button.isEnabled()
    assert dialog.count_label.text() == "1–200 von 20000 Aufnahmen"
    assert dialog.model.rowCount(dialog.model.index(0, 0)) == 0
    assert dialog.model.data(QModelIndex()) is None
    assert dialog.model.data(dialog.model.index(0, 3), Qt.ItemDataRole.ToolTipRole) == str(tmp_path / "00000.mp4")
    assert "ohne Zeitzone" in dialog.model.data(dialog.model.index(0, 2))
    dialog.show()
    app.processEvents()
    assert len(connections) == 1  # Qt view painting never hits the database.
    dialog.next_button.click()
    assert dialog.page.offset == 200
    assert dialog.model.assets[0].asset_id == "asset-00200"
    assert len(connections) == 2 and len(materialized) == 400
    dialog.previous_button.click()
    assert dialog.model.assets[0].asset_id == "asset-00000"
    dialog.refresh(99_999)
    assert dialog.page.offset == 19_800 and not dialog.next_button.isEnabled()
    assert dialog.model.assets[-1].asset_id == "asset-19999"
    assert len(connections) == 4 and len(materialized) == 800
    # External edits may shrink the result set while a dialog remains open.
    with sqlite3.connect(library.path) as db:
        db.execute("UPDATE assets SET capture_time='2026-07-13T10:00:00' WHERE asset_id>='asset-00025'")
    dialog.refresh(dialog.page.offset)
    assert dialog.page.offset == 0 and dialog.model.rowCount() == 25
    assert dialog.count_label.text() == "1–25 von 25 Aufnahmen"
    assert not dialog.previous_button.isEnabled() and not dialog.next_button.isEnabled()
    dialog.accept()
    app.processEvents()
