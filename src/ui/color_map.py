"""
Owned by: Fatima

color_map.py — the single source of truth for per-file colours (Section 5.3).

Every UI surface that needs a colour for a log source — heatmap row, spike-chart
series, log-window header/border, left-panel file list, and the shared legend —
reads from ONE SourceColorMap instance. There is deliberately no other colour
logic anywhere else, so a file always looks the same everywhere and the
investigator can correlate a pop-out window back to its heatmap row at a glance.

"""

# Eight visually distinct hues — enough for the 8-window cap. Chosen to read
# clearly on the app's dark background and to stay distinguishable side by side.
# First four are the approved SOC palette (warm/cool split); the remaining four
# extend it for additional sources while keeping the same design language.
_PALETTE = [
    "#2e8fff",  # blue      — Application
    "#1fd1c0",  # teal      — Interactive sign-in
    "#ffab2e",  # amber     — Auth details
    "#ff4fa3",  # pink      — MSISignIns
    "#8f7fff",  # violet
    "#7ee787",  # lime
    "#4fc3f7",  # sky
    "#ff8a65",  # coral
]

# Reserved exclusively for flagged / correlated events — never assigned to a
# source, so a glowing element always reads unambiguously as "flagged", never
# as "which file this is from".
FLAG_GLOW_COLOR = "#ffffff"


class SourceColorMap:
    """Assigns and remembers one stable base colour per source label."""

    def __init__(self, palette: list[str] | None = None):
        self._map: dict[str, str] = {}
        self._index_map: dict[str, int] = {}  # source_label -> palette slot,
        # kept separately from _map so set_palette() can recolor every
        # existing source by re-resolving its slot against the new palette,
        # instead of losing the assignment order on a theme switch.
        self._next_index = 0
        self._palette = list(palette) if palette else list(_PALETTE)

    def color_for(self, source_label: str) -> str:
        """Returns the assigned colour, assigning the next palette hue the
        first time a source is seen. Assignment order is stable within a
        session so colours don't shuffle as files are added.
        """
        if source_label not in self._map:
            slot = self._next_index % len(self._palette)
            self._index_map[source_label] = slot
            self._map[source_label] = self._palette[slot]
            self._next_index += 1
        return self._map[source_label]

    def has(self, source_label: str) -> bool:
        return source_label in self._map

    def remove(self, source_label: str) -> None:
        """Forget a closed source. The palette index is NOT rewound, so
        remaining and future sources keep their colours rather than shifting.
        """
        self._map.pop(source_label, None)
        self._index_map.pop(source_label, None)

    def as_dict(self) -> dict[str, str]:
        return dict(self._map)

    def set_palette(self, palette: list[str]) -> None:
        """Switches the active palette (Section: theme switching) and
        recolors every already-assigned source by its ORIGINAL slot index,
        so a theme change changes hues without reshuffling which source
        matches which position/legend entry.
        """
        self._palette = list(palette)
        for source_label, slot in self._index_map.items():
            self._map[source_label] = self._palette[slot % len(self._palette)]