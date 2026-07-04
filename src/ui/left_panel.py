"""
left_panel.py — the left investigation panel (Sections 1 & 3).

Houses FILTERS ONLY (no logs): the investigation time-range control, a sort
control for the log data, and the file list. It is placed inside a horizontal
QSplitter by MainWindow so its width is user-resizable and persisted.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox

from src.ui.timeframe_selector import TimeFrameSelector
from src.ui.tab_manager import TabManager

# Sort options exposed to MainWindow (Section 3). Chronological asc/desc plus
# by file name, at minimum.
SORT_TIME_ASC = "time_asc"
SORT_TIME_DESC = "time_desc"
SORT_NAME = "name"


class LeftPanel(QWidget):
    """Left filter panel — time range, sort control, file list."""

    sort_changed = Signal(str)  # one of the SORT_* codes

    def __init__(self, timezone: str, parent=None):
        super().__init__(parent)
        self.setObjectName("LeftSidebar")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(14)

        # -- File list --------------------------------------------------------
        self.tab_manager = TabManager()
        layout.addWidget(self.tab_manager)

        # -- Sort control (Section 3) -----------------------------------------
        sort_title = QLabel("SORT LOGS")
        sort_title.setProperty("class", "SectionTitle")
        layout.addWidget(sort_title)

        self.sort_combo = QComboBox()
        # Newest-first is the default (logs are read newest → oldest).
        self.sort_combo.addItem("Time — newest first", SORT_TIME_DESC)
        self.sort_combo.addItem("Time — oldest first", SORT_TIME_ASC)
        self.sort_combo.addItem("File name (A–Z)", SORT_NAME)
        self.sort_combo.currentIndexChanged.connect(
            lambda _i: self.sort_changed.emit(self.sort_combo.currentData())
        )
        layout.addWidget(self.sort_combo)

        # -- Investigation time range ----------------------------------------
        self.timeframe_selector = TimeFrameSelector(timezone=timezone)
        layout.addWidget(self.timeframe_selector)

        layout.addStretch()

    def current_sort(self) -> str:
        return self.sort_combo.currentData()
