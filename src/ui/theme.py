"""
theme.py — the app's switchable color themes.

Replaces the old fixed constants in styles.py with a THEMES dict + a
build_stylesheet(theme) function, so the whole app (QSS-styled chrome AND
the QPainter/pyqtgraph chart internals, which don't respond to QSS at all)
can be re-themed at runtime instead of being fixed at import time.

Three themes, per the investigator's request:
  - "original" (default) — the literal original palette (light-blue chart
    panels on a dark shell) this app shipped with before the visual redesign.
  - "dark" — the current SOC dark theme, unchanged from what ships today.
  - "coral_reef" — a light-mode option (soft aqua shell, coral/teal/gold/
    plum accents) for investigators who find the dark themes too dark.

Adding a fourth theme later is just adding another entry to THEMES — every
consumer (build_stylesheet, the chart widgets' set_theme(), color_map's
set_palette()) reads from the dict, nothing is hardcoded per-theme outside
this file.
"""

FONT_FAMILY = "Segoe UI, -apple-system, sans-serif"

THEMES = {
    "original": {
        "bg_app": "#0f1526",
        "bg_sidebar": "#131929",
        "bg_input": "#1e2a4a",
        "bg_pressed": "#141d38",
        "bg_statcard": "#1a2035",
        "accent": "#00c4e8",
        "accent_contrast_text": "#0a1020",
        "text_primary": "#c0cce8",
        "text_secondary": "#8090b0",
        "border": "#2a3050",
        "gridline": "#1a2035",
        "scrollbar_handle": "#2e3f6a",
        "row_selected_bg": "#0a1e30",
        "row_highlighted_bg": "#1a2a10", "row_highlighted_text": "#c8e89a",
        "row_flag_bg": "#3a1428", "row_flag_text": "#ff1493",
        "row_default_text": "#8090b0", "row_selected_text": "#c0e4f8",
        "nav_bg": "#131929",
        "chart_heat_bg": "#bec9e9", "chart_heat_border": "#859ad6",
        "chart_spike_bg": "#bec9e9", "chart_spike_border": "#859ad6",
        "chart_bubble_bg": "#bec9e9", "chart_bubble_border": "#859ad6",
        "chart_text": "#161d35", "chart_text_dim": "#3a4560", "chart_outline": "#859ad6",
        "flag_color": "#ff1493",
        "accent_palette": ["#1e3a5f", "#2d5a3d", "#c15a1e", "#a3243f", "#5b3a7d", "#1f6b6b", "#a3246e", "#6b4226"],
    },
    "dark": {
        "bg_app": "#05070d",
        "bg_sidebar": "#080b16",
        "bg_input": "#101a30",
        "bg_pressed": "#0a1220",
        "bg_statcard": "#0e1526",
        "accent": "#2e8fff",
        "accent_contrast_text": "#04101f",
        "text_primary": "#c8d3ea",
        "text_secondary": "#7284a8",
        "border": "#1c2740",
        "gridline": "#10182c",
        "scrollbar_handle": "#1c2740",
        "row_selected_bg": "#122036",
        "row_highlighted_bg": "#1a2a10", "row_highlighted_text": "#c8e89a",
        "row_flag_bg": "#3a2e0a", "row_flag_text": "#ffd60a",
        "row_default_text": "#8090b0", "row_selected_text": "#c0e4f8",
        "nav_bg": "#0b0f1c",
        "chart_heat_bg": "#05070d", "chart_heat_border": "#1c2740",
        "chart_spike_bg": "#05070d", "chart_spike_border": "#1c2740",
        "chart_bubble_bg": "#05070d", "chart_bubble_border": "#1c2740",
        "chart_text": "#c8d3ea", "chart_text_dim": "#7284a8", "chart_outline": "#1c2740",
        "flag_color": "#ffffff",
        "accent_palette": ["#2e8fff", "#1fd1c0", "#ffab2e", "#ff4fa3", "#8f7fff", "#7ee787", "#4fc3f7", "#ff8a65"],
    },
    "coral_reef": {
        "bg_app": "#eafbf6",
        "bg_sidebar": "#f2fdfa",
        "bg_input": "#dff5ef",
        "bg_pressed": "#cdeee5",
        "bg_statcard": "#f2fdfa",
        "accent": "#ff6b6b",
        "accent_contrast_text": "#ffffff",
        "text_primary": "#12343b",
        "text_secondary": "#4f7a78",
        "border": "#b8e6da",
        "gridline": "#d3ecE5",
        "scrollbar_handle": "#a9ddd0",
        "row_selected_bg": "#d3f0ea",
        "row_highlighted_bg": "#ffd6de", "row_highlighted_text": "#a8283f",
        "row_flag_bg": "#ffe9b8", "row_flag_text": "#8a5a00",
        "row_default_text": "#4f7a78", "row_selected_text": "#12343b",
        "nav_bg": "#087f8c",
        "chart_heat_bg": "#ffe8e6", "chart_heat_border": "#ffbdb5",
        "chart_spike_bg": "#fff6df", "chart_spike_border": "#f5dfa0",
        "chart_bubble_bg": "#f2e9f7", "chart_bubble_border": "#d9c0ea",
        "chart_text": "#12343b", "chart_text_dim": "#5c8a87", "chart_outline": "#cfe8e2",
        "flag_color": "#d6402f",
        "accent_palette": ["#d94f3f", "#087f8c", "#c9971f", "#a83246", "#6a4c93", "#2f8f7a", "#2f6fb0", "#b8622f"],
    },
}

THEME_LABELS = {
    "original": "Original",
    "dark": "Dark",
    "coral_reef": "Light",
}

DEFAULT_THEME = "original"


def build_stylesheet(theme: dict) -> str:
    """Generates the full app QSS from a theme dict — the parameterized
    replacement for the old fixed MAIN_STYLESHEET string.
    """
    t = theme
    # Nav text/logo needs a color that reads on nav_bg specifically, which
    # isn't always the same as the general `accent` (e.g. coral_reef's nav_bg
    # is a solid teal block, so a light color reads better there than coral).
    nav_text = t.get("nav_text", t["accent"])
    return f"""
QMainWindow, QWidget {{
    background-color: {t['bg_app']};
    color: {t['text_primary']};
    font-family: {FONT_FAMILY};
}}

/* Plain QLabels otherwise render with an opaque default background instead
   of showing whatever's actually behind them (a real Qt/PySide6 quirk, not
   a color choice) — this was the root cause behind several "text is there
   but invisible" reports. A more specific rule (e.g. QLabel#RawJsonLabel's
   own background-color below) still correctly wins over this per normal
   QSS specificity, so this only affects labels that don't set their own. */
QLabel {{
    background: transparent;
}}

/* ---------------- Top navigation bar ---------------- */
QWidget#TopNavBar {{
    background-color: {t['nav_bg']};
    border-bottom: 1px solid {t['border']};
}}

QLabel#LogoLabel {{
    font-size: 15px;
    font-weight: 500;
    color: {nav_text};
}}

QPushButton {{
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    color: {t['text_secondary']};
    font-size: 12px;
    padding: 5px 12px;
    border-radius: 6px;
}}

QPushButton:hover {{
    border-color: {t['accent']};
    color: {t['text_primary']};
}}

QPushButton:pressed {{
    background-color: {t['bg_pressed']};
}}

QPushButton#PrimaryButton {{
    background-color: {t['accent']};
    border: none;
    color: {t['accent_contrast_text']};
    font-weight: 500;
}}

QPushButton#ToggleActive {{
    background-color: {t['accent']};
    border: none;
    color: {t['accent_contrast_text']};
}}

QComboBox {{
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    color: {t['text_secondary']};
    font-size: 12px;
    padding: 4px 8px;
    border-radius: 6px;
}}

QComboBox:hover {{
    border-color: {t['accent']};
}}

/* ---------------- Left sidebar ---------------- */
QWidget#LeftSidebar {{
    background-color: {t['bg_sidebar']};
    border-right: 1px solid {t['border']};
}}

QLabel.SectionTitle {{
    font-size: 11px;
    font-weight: 500;
    color: {t['accent']};
    text-transform: uppercase;
}}

QLineEdit#FilterInput {{
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    color: {t['text_primary']};
    font-size: 11px;
    padding: 4px 6px;
    border-radius: 6px;
}}

QLineEdit#FilterInput:focus {{
    border-color: {t['accent']};
}}

QPushButton#ApplyFilterButton {{
    background-color: {t['accent']};
    color: {t['accent_contrast_text']};
    font-weight: 500;
    font-size: 12px;
    border: none;
    padding: 6px;
    border-radius: 6px;
}}

QPushButton#ClearFilterButton {{
    background-color: transparent;
    border: 1px solid {t['border']};
    color: {t['text_primary']};
    font-size: 11px;
    padding: 4px;
    border-radius: 6px;
}}

/* ---------------- Log panel (Zone 3) ---------------- */
QWidget#LogPanelHeader {{
    background-color: {t['nav_bg']};
    border-bottom: 1px solid {t['border']};
}}

QTableView {{
    background-color: {t['bg_app']};
    color: {t['text_secondary']};
    gridline-color: {t['gridline']};
    border: none;
    font-size: 11px;
    selection-background-color: {t['row_selected_bg']};
}}

QHeaderView::section {{
    background-color: {t['bg_app']};
    color: {t['accent']};
    font-size: 10px;
    font-weight: 500;
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid {t['border']};
}}

/* ---------------- Event detail panel (Zone 4) ---------------- */
QWidget#EventDetailPanel {{
    background-color: {t['bg_sidebar']};
    border-top: 1px solid {t['border']};
}}

QLabel.FieldKey {{
    font-size: 10px;
    color: {t['text_secondary']};
    text-transform: uppercase;
}}

QLabel.FieldValue {{
    font-size: 12px;
    color: {t['text_primary']};
}}

QLabel#RawJsonLabel {{
    background-color: {t['bg_app']};
    color: {t['text_secondary']};
    font-family: Consolas, monospace;
    font-size: 10px;
    padding: 8px 10px;
}}

/* ---------------- Right dashboard (Zone 5) ---------------- */
QWidget#RightDashboard {{
    background-color: {t['bg_sidebar']};
    border-left: 1px solid {t['border']};
}}

QFrame.StatCard {{
    background-color: {t['bg_statcard']};
    border: 1px solid {t['border']};
    border-radius: 8px;
}}

QLabel.StatValue {{
    font-size: 15px;
    font-weight: 500;
    color: {t['text_primary']};
}}

QScrollBar:vertical {{
    background-color: {t['bg_app']};
    width: 8px;
}}

QScrollBar::handle:vertical {{
    background-color: {t['scrollbar_handle']};
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {t['accent']};
}}

/* ---------------- Visualizations ---------------- */
ActivityHeatmap {{
    background-color: {t['chart_heat_bg']};
    border: 1px solid {t['chart_heat_border']};
    border-radius: 10px;
}}
SpikeChart {{
    background-color: {t['chart_spike_bg']};
    border: 1px solid {t['chart_spike_border']};
    border-radius: 10px;
}}
BubbleChart {{
    background-color: {t['chart_bubble_bg']};
    border: 1px solid {t['chart_bubble_border']};
    border-radius: 10px;
}}
TimelineWidget, ActivityFrequencyChart {{
    background-color: {t['chart_heat_bg']};
    border: 1px solid {t['chart_heat_border']};
    border-radius: 10px;
}}

/* ---------------- Log Window Headers ---------------- */
QLabel#FilenameLabel {{
    color: {t['text_primary']};
    font-weight: bold;
    font-size: 13px;
}}
"""