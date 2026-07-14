"""
TabManager — creates and manages one tab entry per loaded log file in the
left sidebar (Section 5.2, Presentation Layer / Section 6.3.4 Zone 2).

Tab states (Section 6.3.4):
    Active   (cyan border)  — currently focused log panel
    Match    (green border) — contains events within the investigation window
    Inactive (greyed out)   — no events within the investigation window

Owned by: Fatima

"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QClipboard, QAction
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QMenu, QApplication


class LogTab(QFrame):
    """A single clickable tab entry representing one loaded log source."""

    clicked_tab = Signal(str)  # source_label

    def __init__(self, source_label: str, color_hex: str, parent=None):
        super().__init__(parent)
        self.source_label = source_label
        self.color_hex = color_hex
        self.state = "inactive"  # "active" | "match" | "inactive"

        # Themeable — these were hardcoded blue/green regardless of theme,
        # which is exactly the "random blue" bug reported in light mode.
        # "match" keeps a fixed semantic green (recognizable status color,
        # not tied to the accent palette) but its background now uses a
        # theme-neutral surface instead of a hardcoded dark-green tint that
        # would look like a stray dark blob on a light theme.
        self._theme_accent = "#00c4e8"
        self._theme_bg_input = "#101a30"
        self._theme_row_selected = "#122036"
        self._theme_text_dim = "#7284a8"
        self._theme_text = "#c8d3ea"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        self.dot = QLabel()
        self.dot.setFixedSize(6, 6)
        layout.addWidget(self.dot)

        self.name_label = QLabel(source_label)
        self.name_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.name_label)

        layout.addStretch()

        # Section 3 — the per-file count badge was removed as noise.

        self.set_state("inactive")

    def set_theme(self, theme: dict) -> None:
        self._theme_accent = theme["accent"]
        self._theme_bg_input = theme["bg_input"]
        self._theme_row_selected = theme["row_selected_bg"]
        self._theme_text_dim = theme["text_secondary"]
        self._theme_text = theme["text_primary"]
        self.set_state(self.state)  # re-render the current state with the new colors

    def set_state(self, state: str) -> None:
        """state: 'active' | 'match' | 'inactive'

        Driven by TabManager.highlight_active_tabs() from LogFilter results:
        'match' = this file has events in the window, 'inactive' = it doesn't.
        (Clicking a file no longer sets a persistent 'active' highlight — the
        file list is display-only.)
        """
        self.state = state
        if state == "active":
            border_color = self._theme_accent
            self.dot.setStyleSheet(f"background-color: {border_color}; border-radius: 3px;")
            self.setStyleSheet(
                f"background-color: {self._theme_row_selected}; border: 1px solid {border_color}; border-radius: 4px;")
            self.name_label.setStyleSheet(f"font-size: 12px; color: {self._theme_text}; background: transparent;")
            self.setWindowOpacity(1.0)
        elif state == "match":
            border_color = "#57cc99"
            self.dot.setStyleSheet(f"background-color: {border_color}; border-radius: 3px;")
            self.setStyleSheet(
                f"background-color: {self._theme_bg_input}; border: 1px solid {border_color}; border-radius: 4px;")
            self.name_label.setStyleSheet(f"font-size: 12px; color: {self._theme_text}; background: transparent;")
            self.setWindowOpacity(1.0)
        else:  # inactive
            self.dot.setStyleSheet(f"background-color: {self._theme_text_dim}; border-radius: 3px;")
            self.setStyleSheet("background-color: transparent; border: 1px solid transparent; border-radius: 4px;")
            self.name_label.setStyleSheet(f"font-size: 12px; color: {self._theme_text_dim}; background: transparent;")
            self.setWindowOpacity(0.85)

    def mousePressEvent(self, event) -> None:
        self.clicked_tab.emit(self.source_label)
        super().mousePressEvent(event)


class TabManager(QWidget):
    """Holds and manages all LogTab entries — Section 6.3.4 Zone 2 subsection 1."""

    tab_selected = Signal(str)  # source_label

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tabs: dict[str, LogTab] = {}
        self._theme: dict | None = None

        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(3)

        title = QLabel("LOG SOURCES")
        title.setProperty("class", "SectionTitle")
        self.layout_.addWidget(title)
        # 1. Enable custom context menu policy
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def set_theme(self, theme: dict) -> None:
        self._theme = theme
        for tab in self._tabs.values():
            tab.set_theme(theme)

    def _show_context_menu(self, pos):
        # 2. Find which child widget (LogTab) was clicked
        widget = self.childAt(pos)

        # Traverse up to find the LogTab parent if a child (like the dot/label) was clicked
        tab = widget
        while tab and not isinstance(tab, LogTab):
            tab = tab.parentWidget()

        if isinstance(tab, LogTab):
            menu = QMenu(self)
            copy_action = QAction("Copy filename", self)
            copy_action.triggered.connect(
                lambda: QApplication.clipboard().setText(tab.source_label)
            )
            menu.addAction(copy_action)
            menu.exec(self.mapToGlobal(pos))

    def add_tab(self, source_label: str, color_hex: str) -> None:
        """Section 4.7.1 step 7 — TabManager.add_tab(source_label)."""
        if source_label in self._tabs:
            return
        tab = LogTab(source_label, color_hex)
        if self._theme is not None:
            tab.set_theme(self._theme)
        tab.clicked_tab.connect(self.tab_selected.emit)
        self._tabs[source_label] = tab
        self.layout_.addWidget(tab)

    def remove_tab(self, source_label: str) -> None:
        """Removes the tab for a closed log panel.

        Called from MainWindow._on_panel_closed() so a tab never points at
        a LogWindowWidget that no longer exists.
        """
        tab = self._tabs.pop(source_label, None)
        if tab is not None:
            self.layout_.removeWidget(tab)
            tab.deleteLater()

    def highlight_active_tabs(self, active_sources: list[str], inactive_sources: list[str]) -> None:
        """Called after ApplyFilter completes: active_sources -> "match",
        inactive_sources -> "inactive".
        """
        for label in active_sources:
            if label in self._tabs:
                self._tabs[label].set_state("match")
        for label in inactive_sources:
            if label in self._tabs:
                self._tabs[label].set_state("inactive")

    def set_focused_tab(self, source_label: str) -> None:
        for label, tab in self._tabs.items():
            tab.set_state("active" if label == source_label else tab.state)

    def order(self) -> list[str]:
        return list(self._tabs.keys())

    def reorder(self, ordered_labels: list[str]) -> None:
        """Re-lay the tabs in the given order (Section 3 sort-by-name). The
        section title stays at the top; only the tab widgets are re-added.
        """
        for label in ordered_labels:
            tab = self._tabs.get(label)
            if tab is not None:
                self.layout_.removeWidget(tab)
                self.layout_.addWidget(tab)