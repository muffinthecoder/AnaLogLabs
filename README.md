# AnaLog Labs

**A standalone forensic log visualization and investigation tool for IT Security Operations Officers (ISOOs)**

> Developed by **Pentalog Tech** — ICT302 IT Professional Practice Project, Murdoch University Dubai, 2026

---

## Overview

AnaLog Labs is a desktop application that enables IT Security Operations Officers to import, synchronize, correlate, and visualize security log data from multiple sources within a single unified interface.

The tool was developed in response to the fragmented, manual process investigators currently face when analyzing security incidents across systems such as Microsoft Defender, VPN logs, and device event logs. AnaLog Labs replaces the need to open and manually align logs across separate tools by providing synchronized multi-log viewing, timestamp normalization, cross-log event correlation, and interactive timeline visualizations — all entirely offline.

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

- **Multi-file log import** — Import up to 7 CSV, XLSX, or TXT log files simultaneously
- **Timestamp normalisation** — Align timestamps across Perth (AWST UTC+8), Singapore (SGT UTC+8), and Dubai (GST UTC+4) time zones
- **Unified timeline** — View and compare events from all loaded logs in chronological order
- **Custom investigation timeframe** — Define a start and end time down to millisecond precision
- **Timeframe filtering and highlighting** — Filter and highlight events within the investigation window across all logs
- **Tab-based log management** — Each log displayed in its own tab with visual activity indicators
- **Independent movable log windows** — Drag and reposition each log panel freely
- **Side-by-side log view** — Compare activity across systems at the same point in time
- **Synchronized scrolling** — Scroll one log and all others advance to the corresponding timestamp
- **Timeline and correlation visualizations** — Charts, timelines, and linked event views
- **Raw log data display** — Inspect full untruncated event details for any entry
- **Investigation dashboard** — High-level activity overview across all loaded logs
- **Cross-log event correlation** — Identify related events across logs by shared timestamps or attributes

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ |
| UI Framework | PySide6 |
| Log Processing | Pandas / DuckDB |
| Visualizations | PyQtGraph, Matplotlib, Seaborn |
| Packaging | PyInstaller |
| Version Control | Git / GitHub |

---

**Supported file formats:** `.csv`, `.xlsx`, `.txt`

---

## Installation

> AnaLog Labs is distributed as a standalone executable. No manual dependency installation is required.


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

---

## Project Structure

```
analog-labs/
├── main.py                  # Application entry point
├── requirements.txt         # Python dependencies
├── README.md
├── .gitignore
├── src/
│   ├── parser/              # Log file import and parsing (R1)
│   ├── normaliser/          # Timestamp normalisation (R2, R3)
│   ├── filter/              # Date range filtering (R4, R5)
│   ├── correlator/          # Cross-log correlation and sync (R9, R13)
│   ├── visualiser/          # Charts, timelines, dashboard (R10, R12)
│   └── ui/                  # PySide6 interface components (R6, R7, R8, R11)
├── tests/                   # Unit and integration tests
├── docs/                    # Project documentation
│   ├── requirements_analysis.pdf
│   └── project_management_plan.pdf
├── sample_logs/             # Sample CSV log files for testing
└── assets/                  # Icons and UI assets
```

---

## Important Constraints

- **Fully offline** — The application makes no network connections of any kind
- **Read-only** — Log files are never modified, deleted, or copied by the application
- **No SIEM replacement** — AnaLog Labs is a post-incident forensic tool only; it does not generate alerts or perform real-time monitoring
- **Local data only** — All log data remains on the investigator's machine at all times

---


