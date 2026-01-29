"""Cut JSON parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

Point = TypedDict(
    "Point",
    {"in": int, "out": int, "point": Literal["left", "right", "nopoint"] | None},
)


class TeamIntroductionOverlay(TypedDict):
    """Overlay structure for team introduction."""

    type: Literal["TeamIntroduction"]
    team1: str
    team2: str
    condition: str


class WarningOverlay(TypedDict):
    """Overlay structure for warnings."""

    type: Literal["Warning"]
    warning_type: str
    text: str
    tc: int
    length: NotRequired[int]


Overlay = TeamIntroductionOverlay | WarningOverlay


class CutJsonParser:
    """Parse cut JSON payloads."""

    def __init__(self, cut_json_path: str | Path) -> None:
        """Initialize the parser with a cut JSON file path.

        Args:
            cut_json_path: path to the cut JSON file
        """
        self.cut_json_path = Path(cut_json_path)

    def load(self) -> dict[str, Any]:
        """Load raw cut JSON data or return empty defaults.

        Returns:
            raw JSON data with "points" and "overlays" keys
        """
        if not self.cut_json_path.exists():
            return {"points": [], "overlays": []}
        with self.cut_json_path.open() as f:
            return json.load(f)

    def parse_points(self, raw: dict[str, Any]) -> list[Point]:
        """Parse point ranges from raw JSON data.

        Args:
            raw: raw JSON data containing point entries
        Returns:
            parsed list of points
        """
        points = raw.get("points") or []
        parsed: list[Point] = []
        for item in points:
            if not isinstance(item, dict):
                continue
            try:
                in_frame = int(item.get("in", 0))
                out_frame = int(item.get("out", 0))
            except (TypeError, ValueError):
                continue
            point = item.get("point")
            if point not in ("left", "right", "nopoint"):
                point = None
            parsed.append({"in": in_frame, "out": out_frame, "point": point})
        return parsed

    def parse_overlays(self, raw: dict[str, Any]) -> list[Overlay]:
        """Parse overlay entries from raw JSON data.

        Args:
            raw: raw JSON data containing overlay entries
        Returns:
            parsed list of overlays
        """
        overlays = raw.get("overlays") or []
        parsed: list[Overlay] = []
        for item in overlays:
            if not isinstance(item, dict):
                continue
            overlay_type = item.get("type")
            if overlay_type == "TeamIntroduction":
                parsed.append(
                    {
                        "type": "TeamIntroduction",
                        "team1": str(item.get("team1", "")),
                        "team2": str(item.get("team2", "")),
                        "condition": str(item.get("condition", "")),
                    }
                )
            elif overlay_type == "Warning":
                try:
                    tc_value = int(item.get("tc", 0))
                except (TypeError, ValueError):
                    tc_value = 0
                length_value = item.get("length")
                if length_value is not None:
                    try:
                        length_value = int(length_value)
                    except (TypeError, ValueError):
                        length_value = None
                overlay: WarningOverlay = {
                    "type": "Warning",
                    "warning_type": str(item.get("warning_type", "")),
                    "text": str(item.get("text", "")),
                    "tc": tc_value,
                }
                if length_value is not None:
                    overlay["length"] = length_value
                parsed.append(overlay)
        return parsed

    def parse(self) -> tuple[list[Point], list[Overlay]]:
        """Parse points and overlays from the configured JSON file.

        Returns:
            tuple of parsed points and overlays
        """
        raw = self.load()
        return self.parse_points(raw), self.parse_overlays(raw)
