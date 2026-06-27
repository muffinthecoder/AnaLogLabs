"""
styles.py — central QSS stylesheet for AnaLog Labs.

Every hex value here is taken directly from Section 6.3.2 (Color Specification)
of the System Design document. If a color needs to change, change it here only —
no other file should hardcode a hex value.

Owned by: Fatima

"""

# Color spec — Section 6.3.2 -------------------------------------------------
COLOR_BG_APP = "#0f1526"            # Application background
COLOR_BG_PANEL = "#161d35"          # Panel background
COLOR_SOURCE_CYAN = "#00c4e8"       # Interactive sign-in source
COLOR_SOURCE_GREEN = "#57cc99"      # MUPC events source
COLOR_SOURCE_YELLOW = "#ffd60a"     # WLC events source
COLOR_ROW_HIGHLIGHT_BG = "#1a2a10"  # Matched/highlighted row
COLOR_ROW_SELECTED_BG = "#0a1e30"   # Selected row
COLOR_STATUS_SUCCESS = "#57cc99"
COLOR_STATUS_FAILURE = "#e06060"
COLOR_STATUS_WARNING = "#e8b840"
COLOR_TEXT_PRIMARY = "#c0cce8"
COLOR_TEXT_SECONDARY = "#8090b0"
COLOR_BORDER = "#2a3050"
COLOR_CORRELATED_INDICATOR = "#ffd60a"

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
    background-color: #1e2a4a;
    border: 1px solid #2e3f6a;
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 4px;
}}

QPushButton:hover {{
    border-color: {COLOR_SOURCE_CYAN};
}}

QPushButton#PrimaryButton {{
    background-color: {COLOR_SOURCE_CYAN};
    border: none;
    color: #0a1020;
    font-weight: 500;
}}

QPushButton#ToggleActive {{
    background-color: {COLOR_SOURCE_CYAN};
    border: none;
    color: #0a1020;
}}

QComboBox {{
    background-color: #1e2a4a;
    border: 1px solid #2e3f6a;
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    padding: 4px 8px;
    border-radius: 4px;
}}

/* ---------------- Left sidebar ---------------- */
QWidget#LeftSidebar {{
    background-color: #131929;
    border-right: 1px solid {COLOR_BORDER};
}}

QLabel.SectionTitle {{
    font-size: 10px;
    font-weight: 500;
    color: #4a5a7a;
    text-transform: uppercase;
}}

QLineEdit#FilterInput {{
    background-color: #1e2a4a;
    border: 1px solid #2e3f6a;
    color: {COLOR_TEXT_PRIMARY};
    font-size: 10px;
    padding: 4px 6px;
    border-radius: 4px;
}}

QPushButton#ApplyFilterButton {{
    background-color: {COLOR_SOURCE_CYAN};
    color: #0a1020;
    font-weight: 500;
    font-size: 11px;
    border: none;
    padding: 5px;
    border-radius: 4px;
}}

QPushButton#ClearFilterButton {{
    background-color: transparent;
    border: 1px solid #2e3f6a;
    color: #4a5a7a;
    font-size: 10px;
    padding: 4px;
    border-radius: 4px;
}}

/* ---------------- Log panel (Zone 3) ---------------- */
QWidget#LogPanelHeader {{
    background-color: {COLOR_BG_PANEL};
    border-bottom: 1px solid {COLOR_BORDER};
}}

QTableView {{
    background-color: {COLOR_BG_APP};
    color: {COLOR_TEXT_SECONDARY};
    gridline-color: #1a2035;
    border: none;
    font-size: 10px;
    selection-background-color: {COLOR_ROW_SELECTED_BG};
}}

QHeaderView::section {{
    background-color: {COLOR_BG_PANEL};
    color: #4a5a7a;
    font-size: 9px;
    font-weight: 500;
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
}}

/* ---------------- Event detail panel (Zone 4) ---------------- */
QWidget#EventDetailPanel {{
    background-color: #131929;
    border-top: 1px solid {COLOR_BORDER};
}}

QLabel.FieldKey {{
    font-size: 9px;
    color: #4a5a7a;
    text-transform: uppercase;
}}

QLabel.FieldValue {{
    font-size: 11px;
    color: {COLOR_TEXT_PRIMARY};
}}

QLabel#RawJsonLabel {{
    background-color: {COLOR_BG_APP};
    color: #5a7a9a;
    font-family: Consolas, monospace;
    font-size: 9px;
    padding: 8px 10px;
}}

/* ---------------- Right dashboard (Zone 5) ---------------- */
QWidget#RightDashboard {{
    background-color: #131929;
    border-left: 1px solid {COLOR_BORDER};
}}

QFrame.StatCard {{
    background-color: #1a2035;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
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
    background-color: #2e3f6a;
    border-radius: 4px;
}}
"""
