"""Cut JSON parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

Point = TypedDict(
    "Point",
    {"in": int, "out": int, "point": Literal["left", "right", "nopoint"] | None},
)

Side = Literal["left", "right"]


class MatchEvent(TypedDict):
    """Something that changes how the score is read, without being drawn.

    A side switch swaps which team the `left` and `right` of a point refer to;
    a set end banks the current score and starts the next set. Neither draws
    anything, which is why they live here and not in `overlays` — encoding a
    switch as a Warning would mean matching on text meant for the screen.
    """

    type: Literal["side_switch", "set_end"]
    tc: int


class ScoreboardDisplay(TypedDict):
    """How the bar is drawn."""

    position: NotRequired[Literal["top", "bottom"]]
    logos: NotRequired[bool]
    history: NotRequired[bool]


class TitleCardDisplay(TypedDict):
    """How the opening card is drawn."""

    background: NotRequired[Literal["blur", "flat"]]
    length: NotRequired[int]


class Display(TypedDict):
    """Editing choices, as opposed to what happened in the match."""

    scoreboard: NotRequired[ScoreboardDisplay]
    title_card: NotRequired[TitleCardDisplay]


class GameInfoOverlay(TypedDict):
    """What the match is, and the card that opens it.

    Expected on every cut. `team1` is the team on the left at kick-off, which
    is what tells the scoreboard whose point a `left` is — the ordering is not
    cosmetic, and the editor flips it with one button.

    `sets_to_win` decides how the board reads and when the match is over;
    `condition` stays free text for everything the number does not capture.
    """

    type: Literal["GameInfo"]
    team1: str
    team2: str
    condition: str
    sets_to_win: NotRequired[int]


class SideSwitchOverlay(TypedDict):
    """The teams change ends.

    Draws nothing: it swaps which team the `left` of a point refers to. It
    lives among the overlays because that is where they are edited — one list
    of things that happen at a timecode — but it carries its own type rather
    than being a Warning with "switch side" written in it, so the renderer
    never has to read text meant for the screen.
    """

    type: Literal["SideSwitch"]
    tc: int


class SetEndOverlay(TypedDict):
    """A set is over: bank the score and start the next one at zero."""

    type: Literal["SetEnd"]
    tc: int


class WarningOverlay(TypedDict):
    """Overlay structure for warnings."""

    type: Literal["Warning"]
    warning_type: str
    text: str
    tc: int
    length: NotRequired[int]


Overlay = GameInfoOverlay | WarningOverlay | SideSwitchOverlay | SetEndOverlay

#: What `GameInfo` used to be called. Files written before the rename still
#: parse, so nothing has to be migrated by hand.
GAME_INFO_TYPES = ("GameInfo", "TeamIntroduction")

#: The events that change how the score reads, as opposed to what is drawn.
SCORE_EVENTS = ("SideSwitch", "SetEnd")


def _as_int(value: Any) -> int | None:
    """Return `value` as an int, or None when it is not one."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
            data: dict[str, Any] = json.load(f)
        return data

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

    @staticmethod
    def _parse_warning(item: dict[str, Any]) -> WarningOverlay:
        """Parse one warning entry."""
        overlay: WarningOverlay = {
            "type": "Warning",
            "warning_type": str(item.get("warning_type", "")),
            "text": str(item.get("text", "")),
            "tc": _as_int(item.get("tc")) or 0,
        }
        length = _as_int(item.get("length"))
        if length is not None:
            overlay["length"] = length
        return overlay

    @staticmethod
    def _parse_game_info(item: dict[str, Any]) -> GameInfoOverlay:
        """Parse the match's own block, under either of its names."""
        info: GameInfoOverlay = {
            "type": "GameInfo",
            "team1": str(item.get("team1", "")),
            "team2": str(item.get("team2", "")),
            "condition": str(item.get("condition", "")),
        }
        sets_to_win = _as_int(item.get("sets_to_win"))
        if sets_to_win is not None:
            info["sets_to_win"] = sets_to_win
        return info

    def parse_overlays(self, raw: dict[str, Any]) -> list[Overlay]:
        """Parse overlay entries from raw JSON data.

        Args:
            raw: raw JSON data containing overlay entries
        Returns:
            parsed list of overlays
        """
        parsed: list[Overlay] = []
        for item in raw.get("overlays") or []:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind in SCORE_EVENTS:
                tc = _as_int(item.get("tc"))
                if tc is not None:
                    parsed.append({"type": kind, "tc": tc})
            elif kind in GAME_INFO_TYPES:
                parsed.append(self._parse_game_info(item))
            elif kind == "Warning":
                parsed.append(self._parse_warning(item))
        return parsed

    @staticmethod
    def _parse_scoreboard(block: Any) -> ScoreboardDisplay:
        """Parse the scoreboard options of a display block."""
        if not isinstance(block, dict):
            return {}
        parsed: ScoreboardDisplay = {}
        if block.get("position") in ("top", "bottom"):
            parsed["position"] = block["position"]
        for key in ("logos", "history"):
            if isinstance(block.get(key), bool):
                parsed[key] = block[key]
        return parsed

    @staticmethod
    def _parse_title_card(block: Any) -> TitleCardDisplay:
        """Parse the title-card options of a display block."""
        if not isinstance(block, dict):
            return {}
        parsed: TitleCardDisplay = {}
        if block.get("background") in ("blur", "flat"):
            parsed["background"] = block["background"]
        length = _as_int(block.get("length"))
        if length is not None:
            parsed["length"] = length
        return parsed

    def parse_display(self, raw: dict[str, Any]) -> Display:
        """Parse the display block: editing choices, not match facts.

        Args:
            raw: raw JSON data
        Returns:
            the parsed display options, empty when the block is absent
        """
        block = raw.get("display")
        if not isinstance(block, dict):
            return {}

        display: Display = {}
        bar = self._parse_scoreboard(block.get("scoreboard"))
        if bar:
            display["scoreboard"] = bar
        card = self._parse_title_card(block.get("title_card"))
        if card:
            display["title_card"] = card
        return display

    def parse(self) -> tuple[list[Point], list[Overlay]]:
        """Parse points and overlays from the configured JSON file.

        Returns:
            tuple of parsed points and overlays
        """
        raw = self.load()
        return self.parse_points(raw), self.parse_overlays(raw)

    def parse_all(self) -> tuple[list[Point], list[Overlay], Display]:
        """Parse every block in one read.

        Returns:
            points, overlays and display options
        """
        raw = self.load()
        return (
            self.parse_points(raw),
            self.parse_overlays(raw),
            self.parse_display(raw),
        )
