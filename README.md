# AnaLog Labs

**A standalone forensic log visualization and investigation tool for IT Security Operations Officers (ISOOs)**

> Developed by **Pentalog Tech** — ICT302 IT Professional Practice Project, Murdoch University Dubai, 2026

---

## Overview

AnaLog Labs is an offline desktop application that enables IT Security Operations Officers to import, normalise, filter, and visualise security log data from multiple sources within a single unified interface.

The tool was developed in response to the fragmented, manual process investigators currently face when analysing security incidents across systems such as Microsoft Defender, VPN logs, and device event logs. AnaLog Labs replaces the need to open and manually align logs across separate tools by providing multi-log viewing, timestamp normalisation, timeframe-based filtering, and interactive visualisations — all entirely offline. Correlation of events across logs is performed manually by the investigator, supported by a shared timeline, filtering, flagging, and the dashboard visualisations.

---

## Team

| Name | Role |
|---|---|
| Fatima Faisal | Project Manager & Programming |
| Syeda Minal Haque | Communications Officer, Documentation & UI/UX |
| Hiba Zubairi | Software Coordinator & Programming |
| Syeda Noor Zainab | System Analyst, Design & Documentation |
| Pooja Vishnu Gurnani | Programming & Testing |

**Supervisor:** Sameena Javaid  
**Clients:** Peter Cole (UC of ICT302), Mike Groeneweg (Active Lead of Multiple ISOOs)

---

## Features

- **Multi-file log import** — Import CSV, XLSX, or TXT log files and view up to 8 log windows simultaneously
- **Timestamp normalisation** — Convert timestamps across nine supported time zones: UTC, Perth (AWST, UTC+8), Adelaide, Darwin, Brisbane, Sydney, Melbourne, Dubai (GST, UTC+4), and Singapore (SGT, UTC+8) — with correct daylight-saving handling for the zones that observe it (Sydney, Melbourne, Adelaide). Imported logs are assumed to be Perth local time by default unless the timestamp carries its own zone
- **Display time-zone selection** — Choose the investigation display time zone at import, or change it mid-session with all timestamps re-rendering instantly
- **Unified timeline** — View and compare events from all loaded logs against a common time reference
- **Custom investigation timeframe** — Define a start and end time down to millisecond precision, with a small automatic offset so boundary events are not missed
- **Timeframe filtering and highlighting** — Highlight events within the investigation window across all logs; non-matching events remain visible but de-emphasised
- **Tab-based log management** — Each log listed in the sidebar with match / inactive / active visual states
- **Independent, movable log windows** — Drag, resize, pop out, and dock each log panel freely, including across multiple monitors
- **Side-by-side log view** — Compare activity across systems at the same point in time
- **Synchronized scrolling** — Optionally scroll all log windows together to the corresponding timestamp
- **Interactive visualisations** — Activity heatmap, spike chart, and entity bubble chart, with hover detail
- **Raw log data display** — Inspect full, untruncated event details and the raw record for any entry
- **Investigation dashboard** — High-level activity overview across all loaded logs
- **Manual event flagging & session notes** — Flag events of interest and record investigation notes, with export
- **Switchable visual themes** — Original, Dark, and Light themes

> **Note:** Automatic cross-log correlation by shared attributes (originally R13) was descoped after Client Meeting 3 and is not implemented. Correlation is performed manually by the investigator using the timeframe, flagging, and visualisation features.

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ |
| UI Framework | PySide6 |
| Log Processing | pandas, openpyxl |
| Time-zone Handling | pytz, tzlocal |
| Visualisations | PyQtGraph (with custom QPainter widgets) |
| Version Control | Git / GitHub |

**Supported file formats:** `.csv`, `.xlsx`, `.txt`

---

## Installation

### Run from source
```bash
# 1. Clone the repository
git clone https://github.com/your-org/analog-labs.git
cd analog-labs

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the application
python main.py
```

**Dependencies** (`requirements.txt`): PySide6, openpyxl, pytz, pandas, pyqtgraph, tzlocal

---

## Project Structure

```
analog-labs/
├── main.py                      # Application entry point
├── requirements.txt             # Python dependencies
├── README.md
├── src/
│   ├── parser/                  # Log file import and parsing — CSV, TXT, XLSX (R1)
│   ├── normaliser/              # Timestamp normalisation and time-zone mapping (R2, R3)
│   ├── filter/                  # Investigation timeframe filtering (R4, R5)
│   ├── correlator/              # Unified timeline merge (R2) and synchronized scrolling (R9)
│   ├── visualiser/              # Heatmap, spike chart, bubble chart, timeline (R10, R12)
│   ├── models/                  # Data classes and table models
│   └── ui/                      # PySide6 interface components (R6, R7, R8, R11, R12)
├── sample_logs/                 # Sample log files for testing
└── docs/                        # Project documentation
```

---

## Important Constraints

- **Fully offline** — The application makes no network connections of any kind
- **Read-only** — Log files are never modified, deleted, or copied by the application
- **No SIEM replacement** — AnaLog Labs is a post-incident forensic tool only; it does not generate alerts or perform real-time monitoring
- **Local data only** — All log data remains on the investigator's machine at all times
- **No persistence** — All loaded data is held in memory and discarded when the application closes
