"""
TabManager — creates and manages one tab entry per loaded log file in the
left sidebar (Section 5.2, Presentation Layer / Section 6.3.4 Zone 2).

Tab states (Section 6.3.4):
    Active   (cyan border)  — currently focused log panel
    Match    (green border) — contains events within the investigation window
    Inactive (greyed out)   — no events within the investigation window
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame


class LogTab(QFrame):
    """A single clickable tab entry representing one loaded log source."""

    clicked_tab = Signal(str)  # source_label

    def __init__(self, source_label: str, color_hex: str, parent=None):
        super().__init__(parent)
        self.source_label = source_label
        self.color_hex = color_hex
        self.state = "inactive"  # "active" | "match" | "inactive"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        self.dot = QLabel()
        self.dot.setFixedSize(6, 6)
        layout.addWidget(self.dot)

        self.name_label = QLabel(source_label)
        self.name_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.name_label)

        layout.addStretch()

        self.count_badge = QLabel("0")
        self.count_badge.setStyleSheet(
            "font-size: 10px; background-color: #1e2a4a; color: #4a5a7a; "
            "padding: 1px 5px; border-radius: 10px;"
        )
        layout.addWidget(self.count_badge)

        self.set_state("inactive")

    def set_state(self, state: str) -> None:
        """state: 'active' | 'match' | 'inactive'

        TODO (Hiba/Fatima — Section 4.7.2 step 5-6):
            Called from TabManager.highlight_active_tabs() once LogFilter
            returns matched/active/inactive source lists.
        """
        self.state = state
        if state == "active":
            border_color = "#00c4e8"
            self.dot.setStyleSheet(f"background-color: {border_color}; border-radius: 3px;")
            self.setStyleSheet(f"background-color: #1a2540; border: 1px solid {border_color}; border-radius: 4px;")
        elif state == "match":
            border_color = "#57cc99"
            self.dot.setStyleSheet(f"background-color: {border_color}; border-radius: 3px;")
            self.setStyleSheet(f"background-color: #1a2a1a; border: 1px solid {border_color}; border-radius: 4px;")
        else:  # inactive
            self.dot.setStyleSheet("background-color: #3a4a6a; border-radius: 3px;")
            self.setStyleSheet("background-color: transparent; border: 1px solid transparent; border-radius: 4px;")
            self.setWindowOpacity(0.6)

    def set_match_count(self, count: int) -> None:
        self.count_badge.setText(str(count))

    def mousePressEvent(self, event) -> None:
        self.clicked_tab.emit(self.source_label)
        super().mousePressEvent(event)


class TabManager(QWidget):
    """Holds and manages all LogTab entries — Section 6.3.4 Zone 2 subsection 1."""

    tab_selected = Signal(str)  # source_label

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tabs: dict[str, LogTab] = {}

        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(3)

        title = QLabel("LOG SOURCES")
        title.setProperty("class", "SectionTitle")
        self.layout_.addWidget(title)

    def add_tab(self, source_label: str, color_hex: str) -> None:
        """Section 4.7.1 step 7 — TabManager.add_tab(source_label)."""
        if source_label in self._tabs:
            return
        tab = LogTab(source_label, color_hex)
        tab.clicked_tab.connect(self.tab_selected.emit)
        self._tabs[source_label] = tab
        self.layout_.addWidget(tab)

    def highlight_active_tabs(self, active_sources: list[str], inactive_sources: list[str]) -> None:
        """Section 4.7.2 step 6 — called after ApplyFilter completes.

        TODO (Hiba):
            active_sources -> state "match" (or "active" for currently focused)
            inactive_sources -> state "inactive"
        """
        for label in active_sources:
            if label in self._tabs:
                self._tabs[label].set_state("match")
        for label in inactive_sources:
            if label in self._tabs:
                self._tabs[label].set_state("inactive")

    def set_match_count(self, source_label: str, count: int) -> None:
        if source_label in self._tabs:
            self._tabs[source_label].set_match_count(count)

    def set_focused_tab(self, source_label: str) -> None:
        for label, tab in self._tabs.items():
            tab.set_state("active" if label == source_label else tab.state)
