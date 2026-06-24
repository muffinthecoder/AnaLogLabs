"""
mock_data.py — fake log data used to build and test the UI before the real
LogParser (Section 4.7.1) is implemented.

This module is the ONLY place that should contain hardcoded fake rows. When
Hiba's real parser is ready, every UI module that currently imports from here
should instead receive RawLogEntry lists produced by LogParser.parse(). Search
for "mock_data" across the codebase to find every call site that needs
swapping.

The scenario below intentionally reproduces the example used throughout the
design document and mockups: an investigator examining a suspicious sign-in
from j.smith at 192.168.4.2 on the Guest-Net, correlated across three log
sources at 08:07.
"""

from datetime import datetime, timezone

from src.models.data_classes import LogFile, NormalizedTimestamp, RawLogEntry


def _ts(hour: int, minute: int, second: int, ms: int) -> NormalizedTimestamp:
    dt = datetime(2026, 6, 1, hour, minute, second, ms * 1000, tzinfo=timezone.utc)
    return NormalizedTimestamp(utc_datetime=dt, source_tz="Asia/Dubai", milliseconds=ms)


def get_mock_log_files() -> list[LogFile]:
    """Returns the three LogFile objects shown in the mockup."""
    return [
        LogFile(file_path="/sample_logs/interactive_signin.csv", file_format="csv",
                source_label="Interactive_signin"),
        LogFile(file_path="/sample_logs/mupc_events.csv", file_format="csv",
                source_label="MUPC_events"),
        LogFile(file_path="/sample_logs/wlc_events.csv", file_format="csv",
                source_label="WLC_events"),
    ]


def get_mock_entries_interactive_signin() -> list[RawLogEntry]:
    rows = [
        (8, 1, 12, 443, "j.smith", "10.0.1.42", "Success"),
        (8, 3, 55, 112, "a.rahman", "10.0.1.87", "Failure"),
        (8, 7, 33, 9, "j.smith", "192.168.4.2", "Risky"),
        (8, 7, 34, 210, "j.smith", "192.168.4.2", "Failure"),
        (8, 7, 41, 881, "j.smith", "192.168.4.2", "Failure"),
        (8, 8, 2, 334, "j.smith", "192.168.4.2", "Success"),
        (8, 15, 44, 1, "m.ali", "10.0.2.11", "Success"),
        (8, 22, 10, 774, "r.patel", "10.0.1.55", "Success"),
        (8, 40, 3, 228, "a.rahman", "10.0.1.87", "Success"),
        (9, 11, 22, 556, "k.jones", "10.0.3.99", "Success"),
    ]
    entries = []
    for i, (h, m, s, ms, user, ip, status) in enumerate(rows):
        nts = _ts(h, m, s, ms)
        entries.append(RawLogEntry(
            source_label="Interactive_signin",
            raw_timestamp=f"2026-06-01T{h:02}:{m:02}:{s:02}.{ms:03}+04:00",
            fields={
                "timestamp": f"{h:02}:{m:02}:{s:02}.{ms:03}",
                "username": user,
                "ip_address": ip,
                "status": status,
            },
            row_index=i,
            normalized_timestamp=nts,
        ))
    return entries


def get_mock_entries_mupc_events() -> list[RawLogEntry]:
    rows = [
        (8, 1, 9, 2, "WKSTN-04", "Process create", "SYSTEM"),
        (8, 4, 21, 774, "WKSTN-04", "Net connect", "j.smith"),
        (8, 7, 30, 445, "WKSTN-04", "Cmd exec", "j.smith"),
        (8, 7, 41, 112, "WKSTN-04", "File access", "j.smith"),
        (8, 7, 58, 3, "WKSTN-04", "Reg write", "j.smith"),
        (8, 9, 14, 667, "WKSTN-11", "Process create", "SYSTEM"),
        (8, 20, 33, 119, "WKSTN-07", "Net connect", "m.ali"),
        (8, 35, 2, 884, "WKSTN-04", "Process exit", "j.smith"),
        (8, 58, 44, 220, "WKSTN-02", "File access", "r.patel"),
        (9, 10, 55, 3, "WKSTN-09", "Net connect", "k.jones"),
    ]
    entries = []
    for i, (h, m, s, ms, computer, action, account) in enumerate(rows):
        nts = _ts(h, m, s, ms)
        entries.append(RawLogEntry(
            source_label="MUPC_events",
            raw_timestamp=f"2026-06-01T{h:02}:{m:02}:{s:02}.{ms:03}+04:00",
            fields={
                "timestamp": f"{h:02}:{m:02}:{s:02}.{ms:03}",
                "computer": computer,
                "action": action,
                "account": account,
            },
            row_index=i,
            normalized_timestamp=nts,
        ))
    return entries


def get_mock_entries_wlc_events() -> list[RawLogEntry]:
    rows = [
        (8, 0, 58, 113, "10.0.1.42", "aa:bb:11:22", "WiFi-Corp"),
        (8, 3, 44, 9, "10.0.1.87", "cc:dd:33:44", "WiFi-Corp"),
        (8, 7, 28, 771, "192.168.4.2", "ee:ff:55:66", "Guest-Net"),
        (8, 7, 40, 2, "192.168.4.2", "ee:ff:55:66", "Guest-Net"),
        (8, 8, 0, 556, "192.168.4.2", "ee:ff:55:66", "Guest-Net"),
        (8, 14, 33, 882, "10.0.2.11", "11:22:aa:bb", "WiFi-Corp"),
        (8, 21, 7, 3, "10.0.1.55", "33:44:cc:dd", "WiFi-Corp"),
        (8, 39, 55, 441, "10.0.1.87", "cc:dd:33:44", "WiFi-Corp"),
        (9, 0, 14, 228, "10.0.3.99", "55:66:ee:ff", "WiFi-Corp"),
        (9, 9, 48, 774, "10.0.3.99", "55:66:ee:ff", "WiFi-Corp"),
    ]
    entries = []
    for i, (h, m, s, ms, ip, mac, interface) in enumerate(rows):
        nts = _ts(h, m, s, ms)
        entries.append(RawLogEntry(
            source_label="WLC_events",
            raw_timestamp=f"2026-06-01T{h:02}:{m:02}:{s:02}.{ms:03}+04:00",
            fields={
                "timestamp": f"{h:02}:{m:02}:{s:02}.{ms:03}",
                "source_ip": ip,
                "client_mac": mac,
                "interface": interface,
            },
            row_index=i,
            normalized_timestamp=nts,
        ))
    return entries


# Column configuration per source — TODO (Hiba): confirm against real schema
# once LogParser._map_fields() is implemented (Section 4.7.1 step 3).
SOURCE_COLUMNS = {
    "Interactive_signin": ["timestamp", "username", "ip_address", "status"],
    "MUPC_events": ["timestamp", "computer", "action", "account"],
    "WLC_events": ["timestamp", "source_ip", "client_mac", "interface"],
}

SOURCE_COLORS = {
    "Interactive_signin": "#00c4e8",
    "MUPC_events": "#57cc99",
    "WLC_events": "#ffd60a",
}

MOCK_SESSION_STATS = {
    "total_events": 19270,
    "matched": 23,
    "failures": 6,
    "correlated": 3,
}

MOCK_CORRELATED_EVENTS = [
    {"severity": "timestamp", "description": "j.smith sign-in failure \u2192 MUPC cmd exec", "time": "08:07"},
    {"severity": "timestamp", "description": "IP 192.168.4.2 on Guest-Net \u2192 sign-in attempt", "time": "08:07"},
    {"severity": "attribute", "description": "j.smith registry write post-auth", "time": "08:07"},
]
