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
from src.ui.session_notes import SessionNotesWidget
# Add these imports at the top
from PySide6.QtCore import Qt
from PySide6.QtGui import QClipboard, QAction
from PySide6.QtWidgets import QMenu, QApplication

# Sort options exposed to MainWindow (Section 3). Chronological asc/desc.
# (A "File name (A-Z)" option previously existed here but was removed —
# it never actually reordered anything meaningful for the investigator.)
SORT_TIME_ASC = "time_asc"
SORT_TIME_DESC = "time_desc"


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
        self.sort_combo.currentIndexChanged.connect(
            lambda _i: self.sort_changed.emit(self.sort_combo.currentData())
        )
        layout.addWidget(self.sort_combo)

        # -- Investigation time range ----------------------------------------
        self.timeframe_selector = TimeFrameSelector(timezone=timezone)
        layout.addWidget(self.timeframe_selector)

        layout.addStretch()
        layout.addWidget(self.tab_manager, stretch=1)  # Tab manager takes most space

        self.session_notes = SessionNotesWidget()
        layout.addWidget(self.session_notes)

        # 1. Enable custom context menu on the TabManager
        self.tab_manager.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tab_manager.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos):
        # 2. Get the specific tab/item clicked
        # TabManager likely uses itemAt() or indexAt() to find the tab
        item = self.tab_manager.itemAt(pos)

        # If your TabManager uses a list/tree, itemAt might return an object
        # that has a .text() method
        if item:
            menu = QMenu(self)
            copy_action = QAction("Copy filename", self)

            # 3. Connect the action to copy the text to the clipboard
            copy_action.triggered.connect(
                lambda: QApplication.clipboard().setText(item.text())
            )

            menu.addAction(copy_action)
            menu.exec(self.tab_manager.mapToGlobal(pos))

    def current_sort(self) -> str:
        return self.sort_combo.currentData()