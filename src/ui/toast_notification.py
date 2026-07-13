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

Positioning: show_toast() takes an optional `anchor` widget (the button/
control that triggered the action) and appears just below it, so the
confirmation reads as a direct response to what was clicked rather than a
generic notification arriving from a fixed corner of the screen. Falls back
to the bottom-right corner only when no anchor is given.

Theming: "info" and "neutral" dot colors come from the active theme (accent
and text_secondary) since those carry no fixed semantic meaning of their own
— e.g. in a light/coral theme, "info" reads as pink/coral rather than the
hardcoded blue this had before. "success" and "warning" stay fixed semantic
green/amber, matching the same convention used for status text elsewhere
(a universal green=good/amber=caution reads correctly in any theme).
"""

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QPoint
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGraphicsOpacityEffect

TOAST_WIDTH = 340
TOAST_MARGIN = 16
TOAST_ANCHOR_GAP = 8      # gap between the anchor widget's bottom edge and the toast
TOAST_EDGE_PAD = 10       # never let the toast touch the window edge
TOAST_DURATION_MS = 2800
TOAST_ANIM_MS = 200

# Fixed semantic colors — universal enough to stay constant across themes.
SUCCESS_COLOR = "#1fd1c0"
WARNING_COLOR = "#ffab2e"


class ToastNotification(QWidget):
    """Single-slot, auto-dismissing toast, anchored near whatever triggered it."""

    def __init__(self, parent, theme: dict | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("ToastCard")
        self.setFixedWidth(TOAST_WIDTH)

        # Themeable — defaults match what shipped before theme switching
        # existed, in case set_theme() is never called.
        self._bg = "#0e1526"
        self._border = "#1c2740"
        self._text_primary = "#c8d3ea"
        self._text_secondary = "#7284a8"
        self._accent = "#2e8fff"

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(10)

        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        outer.addWidget(self._dot, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._title = QLabel()
        self._sub = QLabel()
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

        self._anchor: QWidget | None = None
        self._current_kind = "info"

        self.set_theme(theme or {
            "bg_input": self._bg, "border": self._border,
            "text_primary": self._text_primary, "text_secondary": self._text_secondary,
            "accent": self._accent,
        })


        self.hide()

    # -- Public API ------------------------------------------------------------

    def set_theme(self, theme: dict) -> None:
        self._bg = theme["bg_input"]
        self._border = theme["border"]
        self._text_primary = theme["text_primary"]
        self._text_secondary = theme["text_secondary"]
        self._accent = theme["accent"]

        self.setStyleSheet(
            "QWidget#ToastCard {"
            f"  background-color: {self._bg};"
            f"  border: 1px solid {self._border};"
            "  border-radius: 8px;"
            "}"
        )
        self._title.setStyleSheet(
            f"color: {self._text_primary}; font-size: 12.5px; font-weight: 500; background: transparent;"
        )
        self._sub.setStyleSheet(f"color: {self._text_secondary}; font-size: 11.5px; background: transparent;")
        self._apply_dot_color(self._current_kind)

    def _dot_color_for(self, kind: str) -> str:
        return {
            "success": SUCCESS_COLOR,
            "info": self._accent,
            "neutral": self._text_secondary,
            "warning": WARNING_COLOR,
        }.get(kind, self._accent)

    def _apply_dot_color(self, kind: str) -> None:
        self._dot.setStyleSheet(f"background-color: {self._dot_color_for(kind)}; border-radius: 4px;")

    def show_toast(self, title: str, subtitle: str = "", kind: str = "info", anchor: QWidget | None = None) -> None:
        """anchor: the widget (usually a button) that triggered this action —
        the toast appears just below it instead of a fixed screen corner.
        Falls back to the bottom-right corner if omitted or no longer valid.
        """
        self._current_kind = kind
        self._apply_dot_color(kind)
        self._title.setText(title)
        self._sub.setText(subtitle)
        self._sub.setVisible(bool(subtitle))
        self._anchor = anchor
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
        correctly (whether that's near its trigger widget or the corner).
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

    def _anchor_is_usable(self) -> bool:
        if self._anchor is None:
            return False
        try:
            return self._anchor.isVisible()
        except RuntimeError:
            # The underlying Qt widget was deleted (e.g. a popped-out log
            # window's button, closed since the toast was first shown).
            return False

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return

        if self._anchor_is_usable():
            # Just below the anchor's bottom-left corner, mapped into the
            # parent window's coordinate space (the anchor lives somewhere
            # in the widget tree, not necessarily a direct child of parent).
            bottom_left = self._anchor.mapTo(parent, QPoint(0, self._anchor.height()))
            x = bottom_left.x()
            y = bottom_left.y() + TOAST_ANCHOR_GAP
            # Clamp so it never overflows the window, e.g. a button near the
            # right edge would otherwise push the toast off-screen.
            x = min(x, parent.width() - self.width() - TOAST_EDGE_PAD)
            x = max(x, TOAST_EDGE_PAD)
            y = min(y, parent.height() - self.height() - TOAST_EDGE_PAD)
            y = max(y, TOAST_EDGE_PAD)
            self.move(x, y)
        else:
            # Fallback: bottom-right corner (no anchor given, or it's gone).
            x = parent.width() - self.width() - TOAST_MARGIN
            y = parent.height() - self.height() - TOAST_MARGIN
            self.move(max(x, 0), max(y, 0))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition()