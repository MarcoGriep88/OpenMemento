"""Movie-wide editing templates, independent of analysis and frame rate."""
from dataclasses import dataclass
import math


# Stable identifiers are persisted in movie projects; labels belong to the UI.
EDITING_TEMPLATES = {
    "random": ("Zufällige Übergänge", None),
    "cut": ("Klassisch · Cut", None),
    "crossfade": ("Sanft · Crossfade", "fade"),
    "blurfade": ("Weich · Blurfade", "hblur"),
    "black": ("Ruhig · Schwarzblende", "fadeblack"),
    "zoom": ("Dynamisch · Zoom hinein", "zoomin"),
}


@dataclass(frozen=True, slots=True)
class EditingStyle:
    template: str = "cut"
    transition_seconds: float = 0.6

    def validate(self):
        if not isinstance(self.template, str) or self.template not in EDITING_TEMPLATES:
            raise ValueError("Unbekannte Schnittvorlage.")
        if (type(self.transition_seconds) not in (int, float)
                or not math.isfinite(self.transition_seconds)
                or not 0.1 <= self.transition_seconds <= 2):
            raise ValueError("Die Übergangsdauer muss zwischen 0,1 und 2 Sekunden liegen.")

    def transition(self, index):
        if self.template == "random":
            # A stable pseudo-random choice keeps preview, export and cache identical.
            import hashlib
            choices = ("fade", "hblur", "fadeblack", "zoomin")
            return choices[hashlib.sha256(f"memento-v2:{index}".encode()).digest()[0] % len(choices)]
        return EDITING_TEMPLATES[self.template][1]

    def overlaps(self, durations):
        """Reserve at most half of each neighbor, including very short clips."""
        if self.template == "cut":
            return [0.0] * max(0, len(durations) - 1)
        return [min(self.transition_seconds, left / 2, right / 2)
                for left, right in zip(durations, durations[1:])]

    def overlap_frames(self, frames, fps):
        if self.template == "cut":
            return [0] * max(0, len(frames) - 1)
        return [min(round(self.transition_seconds * fps), left // 2, right // 2)
                for left, right in zip(frames, frames[1:])]
