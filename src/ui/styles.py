"""
styles.py — central QSS stylesheet for AnaLog Labs.

Every hex value here is taken directly from Section 6.3.2 (Color Specification)
of the System Design document. If a color needs to change, change it here only —
no other file should hardcode a hex value.

Owned by: Fatima

"""

# Color spec — Section 6.3.2 -------------------------------------------------
COLOR_BG_APP = "#05070d"            # Application background (SOC dark)
COLOR_BG_PANEL = "#0b0f1c"          # Panel background
COLOR_SOURCE_CYAN = "#2e8fff"       # Primary accent (Application source)
COLOR_SOURCE_GREEN = "#1fd1c0"      # Secondary accent (Interactive sign-in source)
COLOR_SOURCE_YELLOW = "#ffab2e"     # Tertiary accent (Auth details source)
COLOR_SOURCE_PINK = "#ff4fa3"       # Quaternary accent (MSISignIns source)
COLOR_FLAG_GLOW = "#ffffff"         # Reserved for flagged/correlated glow only
COLOR_ROW_HIGHLIGHT_BG = "#182238"  # Matched/highlighted row
COLOR_ROW_SELECTED_BG = "#122036"   # Selected row
COLOR_STATUS_SUCCESS = "#1fd1c0"
COLOR_STATUS_FAILURE = "#ff4fa3"
COLOR_STATUS_WARNING = "#ffab2e"
COLOR_TEXT_PRIMARY = "#c8d3ea"
COLOR_TEXT_SECONDARY = "#7284a8"
COLOR_BORDER = "#1c2740"
COLOR_CORRELATED_INDICATOR = "#ffffff"

# Typography — Section 6.3.3 --------------------------------------------------
FONT_FAMILY = "Segoe UI, -apple-system, sans-serif"


MAIN_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLOR_BG_APP};
    color: {COLOR_TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
}}

/* ---------------- Top navigation bar ---------------- */
QWidget#TopNavBar {{
    background-color: {COLOR_BG_PANEL};
    border-bottom: 1px solid {COLOR_BORDER};
}}

QLabel#LogoLabel {{
    font-size: 14px;
    font-weight: 500;
    color: {COLOR_SOURCE_CYAN};
}}

QPushButton {{
    background-color: #101a30;
    border: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    padding: 5px 12px;
    border-radius: 6px;
}}

QPushButton:hover {{
    border-color: {COLOR_SOURCE_CYAN};
    color: {COLOR_TEXT_PRIMARY};
}}

QPushButton:pressed {{
    background-color: #0a1220;
}}

QPushButton#PrimaryButton {{
    background-color: {COLOR_SOURCE_CYAN};
    border: none;
    color: #04101f;
    font-weight: 500;
}}

QPushButton#ToggleActive {{
    background-color: {COLOR_SOURCE_CYAN};
    border: none;
    color: #04101f;
}}

QComboBox {{
    background-color: #101a30;
    border: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    padding: 4px 8px;
    border-radius: 6px;
}}

QComboBox:hover {{
    border-color: {COLOR_SOURCE_CYAN};
}}

/* ---------------- Left sidebar ---------------- */
QWidget#LeftSidebar {{
    background-color: #080b16;
    border-right: 1px solid {COLOR_BORDER};
}}

QLabel.SectionTitle {{
    font-size: 10px;
    font-weight: 500;
    color: {COLOR_SOURCE_CYAN};
    text-transform: uppercase;
}}

QLineEdit#FilterInput {{
    background-color: #101a30;
    border: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_PRIMARY};
    font-size: 10px;
    padding: 4px 6px;
    border-radius: 6px;
}}

QLineEdit#FilterInput:focus {{
    border-color: {COLOR_SOURCE_CYAN};
}}

QPushButton#ApplyFilterButton {{
    background-color: {COLOR_SOURCE_CYAN};
    color: #04101f;
    font-weight: 500;
    font-size: 11px;
    border: none;
    padding: 6px;
    border-radius: 6px;
}}

QPushButton#ClearFilterButton {{
    background-color: transparent;
    border: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_PRIMARY};
    font-size: 10px;
    padding: 4px;
    border-radius: 6px;
}}

/* ---------------- Log panel (Zone 3) ---------------- */
QWidget#LogPanelHeader {{
    background-color: {COLOR_BG_PANEL};
    border-bottom: 1px solid {COLOR_BORDER};
}}

QTableView {{
    background-color: {COLOR_BG_APP};
    color: {COLOR_TEXT_SECONDARY};
    gridline-color: #10182c;
    border: none;
    font-size: 10px;
    selection-background-color: {COLOR_ROW_SELECTED_BG};
}}

QHeaderView::section {{
    background-color: {COLOR_BG_APP};
    color: {COLOR_SOURCE_CYAN};
    font-size: 9px;
    font-weight: 500;
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
}}

/* ---------------- Event detail panel (Zone 4) ---------------- */
QWidget#EventDetailPanel {{
    background-color: #080b16;
    border-top: 1px solid {COLOR_BORDER};
}}

QLabel.FieldKey {{
    font-size: 9px;
    color: {COLOR_TEXT_SECONDARY};
    text-transform: uppercase;
}}

QLabel.FieldValue {{
    font-size: 11px;
    color: {COLOR_TEXT_PRIMARY};
}}

QLabel#RawJsonLabel {{
    background-color: {COLOR_BG_APP};
    color: {COLOR_TEXT_SECONDARY};
    font-family: Consolas, monospace;
    font-size: 9px;
    padding: 8px 10px;
}}

/* ---------------- Right dashboard (Zone 5) ---------------- */
QWidget#RightDashboard {{
    background-color: #080b16;
    border-left: 1px solid {COLOR_BORDER};
}}

QFrame.StatCard {{
    background-color: #0e1526;
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
}}

QLabel.StatValue {{
    font-size: 14px;
    font-weight: 500;
    color: {COLOR_TEXT_PRIMARY};
}}

QScrollBar:vertical {{
    background-color: {COLOR_BG_APP};
    width: 8px;
}}

QScrollBar::handle:vertical {{
    background-color: #1c2740;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLOR_SOURCE_CYAN};
}}

/* ---------------- Visualizations — unified dark SOC panel ---------------- */
ActivityHeatmap, TimelineWidget, ActivityFrequencyChart, SpikeChart, BubbleChart {{
    background-color: #05070d;
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}

/* ---------------- Log Window Headers ---------------- */
QLabel#FilenameLabel {{
    color: {COLOR_TEXT_PRIMARY};
    font-weight: bold;
    font-size: 12px;
}}
"""
