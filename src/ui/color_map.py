"""
color_map.py — the single source of truth for per-file colours (Section 5.3).

Every UI surface that needs a colour for a log source — heatmap row, spike-chart
series, log-window header/border, left-panel file list, and the shared legend —
reads from ONE SourceColorMap instance. There is deliberately no other colour
logic anywhere else, so a file always looks the same everywhere and the
investigator can correlate a pop-out window back to its heatmap row at a glance.

Root cause this replaces: the import path hardcoded every file to the same blue
("#4A90D9"), so all sources were visually identical in every chart.
"""

# Eight visually distinct hues — enough for the 8-window cap. Chosen to read
# clearly on the app's dark background and to stay distinguishable side by side.
_PALETTE = [
    "#00c4e8",  # cyan
    "#57cc99",  # green
    "#ffd60a",  # yellow
    "#e06060",  # red
    "#b06be0",  # purple
    "#e8933a",  # orange
    "#48d1cc",  # teal
    "#f06fae",  # pink
]


class SourceColorMap:
    """Assigns and remembers one stable base colour per source label."""

    def __init__(self):
        self._map: dict[str, str] = {}
        self._next_index = 0

    def color_for(self, source_label: str) -> str:
        """Returns the assigned colour, assigning the next palette hue the
        first time a source is seen. Assignment order is stable within a
        session so colours don't shuffle as files are added.
        """
        if source_label not in self._map:
            self._map[source_label] = _PALETTE[self._next_index % len(_PALETTE)]
            self._next_index += 1
        return self._map[source_label]

    def has(self, source_label: str) -> bool:
        return source_label in self._map

    def remove(self, source_label: str) -> None:
        """Forget a closed source. The palette index is NOT rewound, so
        remaining and future sources keep their colours rather than shifting.
        """
        self._map.pop(source_label, None)

    def as_dict(self) -> dict[str, str]:
        return dict(self._map)
