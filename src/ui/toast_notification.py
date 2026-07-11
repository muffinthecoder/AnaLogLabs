"""
toast_notification.py — lightweight, non-blocking action feedback.

Several actions in the app previously happened silently: apply/clear filter,
import results, sync scroll on/off, flag add/remove, session notes export,
log window pop-out/redock/close, and display timezone changes. This widget
surfaces a brief, auto-dismissing confirmation for those — never blocking,
never required to proceed.

Single-slot by design: a new show_toast() call while one is already visible
replaces its content and restarts the dismiss timer, rather than stacking
multiple toasts. Simpler and avoids toast pile-ups during a busy import.
"""

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGraphicsOpacityEffect

TOAST_WIDTH = 340
TOAST_MARGIN = 16
TOAST_DURATION_MS = 2800
TOAST_ANIM_MS = 200

# Kind -> accent dot color. Mirrors the app's status color language
# (teal = success, blue = info/neutral action, amber = warning) rather than
# inventing a new palette just for toasts.
DOT_COLORS = {
    "success": "#1fd1c0",
    "info": "#2e8fff",
    "neutral": "#7284a8",
    "warning": "#ffab2e",
}


class ToastNotification(QWidget):
    """Bottom-right, single-slot, auto-dismissing toast."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("ToastCard")
        self.setFixedWidth(TOAST_WIDTH)
        self.setStyleSheet(
            "QWidget#ToastCard {"
            "  background-color: #0e1526;"
            "  border: 1px solid #1c2740;"
            "  border-radius: 8px;"
            "}"
        )

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(10)

        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        outer.addWidget(self._dot, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._title = QLabel()
        self._title.setStyleSheet("color: #c8d3ea; font-size: 11.5px; font-weight: 500; background: transparent;")
        self._sub = QLabel()
        self._sub.setStyleSheet("color: #7284a8; font-size: 10.5px; background: transparent;")
        self._sub.setWordWrap(True)
        text_col.addWidget(self._title)
        text_col.addWidget(self._sub)
        outer.addLayout(text_col, 1)

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(0.0)

        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(TOAST_ANIM_MS)
        self._fade.finished.connect(self._on_fade_finished)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self.hide()

    # -- Public API ------------------------------------------------------------

    def show_toast(self, title: str, subtitle: str = "", kind: str = "info") -> None:
        color = DOT_COLORS.get(kind, DOT_COLORS["info"])
        self._dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
        self._title.setText(title)
        self._sub.setText(subtitle)
        self._sub.setVisible(bool(subtitle))
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()

        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._hide_timer.start(TOAST_DURATION_MS)

    def reposition(self) -> None:
        """Call when the parent window resizes so the toast stays anchored
        to the bottom-right corner.
        """
        self._reposition()

    # -- Internal ----------------------------------------------------------------

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if self._opacity.opacity() <= 0.01:
            self.hide()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        x = parent.width() - self.width() - TOAST_MARGIN
        y = parent.height() - self.height() - TOAST_MARGIN
        self.move(max(x, 0), max(y, 0))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition()