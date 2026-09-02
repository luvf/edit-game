"""Drawing the match overlay.

Three things are drawn: the scoreboard bar, the warning strip under it, and the
card that opens the match. Each returns an RGBA image the size of the frame,
transparent everywhere it does not paint, so ffmpeg can composite it as-is.

The bar is deliberately symmetric about its centre line. Reading outward from
there: the current score, the sets already played, the team name, the logo. The
current scores therefore sit in the same place whichever way round the teams
are, which matters because the bar flips when the teams change ends — the two
numbers a viewer is actually watching never move.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFilter, ImageFont

if TYPE_CHECKING:
    from collections.abc import Sequence

    from jugger_video_manipulation.scoreboard import BoardState

FRAME = (1920, 1080)

INK = (255, 255, 255, 255)
PANEL = (12, 14, 18, 216)
EDGE = (255, 255, 255, 38)
#: Finished sets sit back from the current score: they are context, not the
#: number being watched. The winner of each set is the brighter of its pair.
SET_WON = (255, 255, 255, 190)
SET_LOST = (255, 255, 255, 105)
RULE = (255, 255, 255, 78)
WARNING_BG = (150, 32, 32, 226)
WARNING_INK = (255, 214, 214, 255)

#: A team name on the title card is shrunk until it fits its half of the card,
#: and never below the point where it stops being a headline.
CARD_NAME_WIDTH = 640
CARD_NAME_MIN = 40


@dataclass(frozen=True)
class Team:
    """What the overlay needs to know about one team."""

    name: str
    logo: Path | None = None


@dataclass(frozen=True)
class Style:
    """Fonts, sizes and margins. One place to retheme the whole overlay."""

    display_font: Path = Path("jugger_video_manipulation/impact.ttf")
    text_font: Path = Path("/usr/share/fonts/liberation/LiberationSans-Bold.ttf")
    plain_font: Path = Path("/usr/share/fonts/liberation/LiberationSans-Regular.ttf")
    score_size: int = 44
    name_size: int = 24
    logo_size: int = 52
    #: Set numbers shrink as they pile up; a five-set match is rare but must
    #: not push the bar out of shape when it happens.
    set_sizes: tuple[int, ...] = (19, 19, 17, 16, 15)
    name_max_width: int = 260
    margin: int = 46
    radius: int = 12
    padding: int = 22
    gap: int = 18
    cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = field(
        default_factory=dict, compare=False, repr=False
    )

    def font(self, path: Path, size: int) -> ImageFont.FreeTypeFont:
        """Return a font, loading each size only once."""
        key = (str(path), size)
        if key not in self.cache:
            self.cache[key] = ImageFont.truetype(str(path), size)
        return self.cache[key]

    def set_size(self, count: int) -> int:
        """Return the type size for `count` finished sets."""
        if count <= 0:
            return self.set_sizes[0]
        return self.set_sizes[min(count, len(self.set_sizes)) - 1]


def _text_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> int:
    """Return how wide `text` renders."""
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _text_height(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> int:
    """Return how tall `text` renders."""
    box = draw.textbbox((0, 0), text, font=font)
    return box[3] - box[1]


def truncate(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    """Cut the end of a name that will not fit, marking the cut.

    The limit is in pixels rather than characters: a wide name in capitals has
    to go sooner than a narrow one, and counting characters would cut one and
    not the other.
    """
    if _text_width(draw, text, font) <= max_width:
        return text
    cut = text
    while cut and _text_width(draw, cut + "…", font) > max_width:
        cut = cut[:-1]
    return cut.rstrip() + "…"


def load_logo(path: Path | None, height: int) -> Image.Image | None:
    """Load a logo scaled to `height`, or None when there is none to load."""
    if path is None or not path.exists():
        return None
    image = Image.open(path).convert("RGBA")
    width = max(int(image.width * height / image.height), 1)
    return image.resize((width, height), Image.Resampling.LANCZOS)


@dataclass
class _Side:
    """One half of the bar, measured before anything is drawn."""

    score: str
    sets: list[tuple[str, bool]]
    name: str
    logo: Image.Image | None
    width: int
    sets_width: int


def _measure_side(
    draw: ImageDraw.ImageDraw,
    style: Style,
    *,
    score: int,
    sets: Sequence[tuple[int, bool]],
    team: Team,
    show_logos: bool,
) -> _Side:
    """Work out how wide one half of the bar needs to be."""
    score_font = style.font(style.display_font, style.score_size)
    name_font = style.font(style.text_font, style.name_size)
    set_font = style.font(style.text_font, style.set_size(len(sets)))

    name = truncate(draw, team.name, name_font, style.name_max_width)
    logo = load_logo(team.logo, style.logo_size) if show_logos else None

    sets_width = 0
    if sets:
        sets_width = max(_text_width(draw, str(v), set_font) for v, _ in sets)

    width = _text_width(draw, str(score), score_font) + style.gap
    if sets:
        width += sets_width + style.gap
    width += _text_width(draw, name, name_font)
    if logo is not None:
        width += style.gap + logo.width

    return _Side(
        score=str(score),
        sets=[(str(v), won) for v, won in sets],
        name=name,
        logo=logo,
        width=width,
        sets_width=sets_width,
    )


def _sets_for(state: BoardState, side: str) -> list[tuple[int, bool]]:
    """Return one team's finished-set scores, and whether it won each.

    A team keeps its own column, so the history follows the team across a side
    switch rather than staying put on screen.
    """
    team = state.left if side == "left" else state.right
    out: list[tuple[int, bool]] = []
    for finished in state.finished_sets:
        mine = finished.team1 if team == "team1" else finished.team2
        out.append((mine, finished.winner == team))
    return out


def draw_scoreboard(
    state: BoardState,
    teams: dict[str, Team],
    *,
    style: Style | None = None,
    position: str = "bottom",
    show_logos: bool = True,
    show_history: bool = True,
    size: tuple[int, int] = FRAME,
) -> Image.Image:
    """Draw the bar for one board state, on a transparent frame.

    Args:
        state: what the board says, already resolved to sides.
        teams: the two teams, keyed by the names used in the state.
        style: fonts and sizes; the default theme when omitted.
        position: `top` or `bottom`.
        show_logos: draw the team logos on the outside.
        show_history: draw the finished sets.
        size: the frame to draw on.

    Returns:
        An RGBA image of `size`, transparent outside the bar.
    """
    style = style or Style()
    width, height = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    sides = {
        "left": _measure_side(
            draw,
            style,
            score=state.left_score,
            sets=_sets_for(state, "left") if show_history else [],
            team=teams.get(state.left, Team(state.left)),
            show_logos=show_logos,
        ),
        "right": _measure_side(
            draw,
            style,
            score=state.right_score,
            sets=_sets_for(state, "right") if show_history else [],
            team=teams.get(state.right, Team(state.right)),
            show_logos=show_logos,
        ),
    }

    rows = max(len(sides["left"].sets), len(sides["right"].sets), 1)
    set_font = style.font(style.text_font, style.set_size(rows))
    plain_font = style.font(style.plain_font, style.set_size(rows))
    line = style.set_size(rows) + 3

    bar_height = max(74, rows * line + 20)
    half = max(sides["left"].width, sides["right"].width)
    bar_width = half * 2 + style.padding * 2 + 44

    x0 = (width - bar_width) // 2
    y0 = (height - bar_height - style.margin) if position == "bottom" else style.margin
    centre_x = width // 2
    middle_y = y0 + bar_height // 2

    draw.rounded_rectangle(
        [x0, y0, x0 + bar_width, y0 + bar_height],
        radius=style.radius,
        fill=PANEL,
        outline=EDGE,
        width=2,
    )
    draw.line([centre_x, y0 + 14, centre_x, y0 + bar_height - 14], fill=RULE, width=2)

    score_font = style.font(style.display_font, style.score_size)
    name_font = style.font(style.text_font, style.name_size)

    for key, direction in (("left", -1), ("right", 1)):
        side = sides[key]
        cursor = centre_x + direction * 22

        score_width = _text_width(draw, side.score, score_font)
        draw.text(
            (
                cursor - score_width if direction < 0 else cursor,
                middle_y - _text_height(draw, side.score, score_font) / 2 - 8,
            ),
            side.score,
            font=score_font,
            fill=INK,
        )
        cursor += direction * (score_width + style.gap)

        if side.sets:
            top = middle_y - (len(side.sets) * line) / 2
            for index, (value, won) in enumerate(side.sets):
                font = set_font if won else plain_font
                value_width = _text_width(draw, value, font)
                # Right-align each column against the centre, so the digits
                # stack cleanly whether they are one or two wide.
                x = (
                    cursor - value_width
                    if direction < 0
                    else cursor + (side.sets_width - value_width)
                )
                draw.text(
                    (x, top + index * line),
                    value,
                    font=font,
                    fill=SET_WON if won else SET_LOST,
                )
            cursor += direction * (side.sets_width + style.gap)

        name_width = _text_width(draw, side.name, name_font)
        draw.text(
            (
                cursor - name_width if direction < 0 else cursor,
                middle_y - _text_height(draw, side.name, name_font) / 2 - 3,
            ),
            side.name,
            font=name_font,
            fill=INK,
        )
        cursor += direction * (name_width + style.gap)

        if side.logo is not None:
            layer.paste(
                side.logo,
                (
                    int(cursor - side.logo.width) if direction < 0 else int(cursor),
                    middle_y - side.logo.height // 2,
                ),
                side.logo,
            )

    return layer


def draw_warning(
    kind: str,
    text: str,
    *,
    style: Style | None = None,
    position: str = "bottom",
    bar_height: int = 74,
    size: tuple[int, int] = FRAME,
) -> Image.Image:
    """Draw the warning strip, on a transparent frame.

    It sits just inside the scoreboard, on whichever edge the bar is on, so the
    two stack instead of competing for the same band of picture.

    Args:
        kind: the warning type, shown small and in capitals.
        text: the free text, shown large.
        style: fonts and sizes.
        position: where the scoreboard is, so the strip can tuck against it.
        bar_height: how tall the scoreboard is, for the same reason.
        size: the frame to draw on.

    Returns:
        An RGBA image of `size`, transparent outside the strip.
    """
    style = style or Style()
    width, height = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    kind_font = style.font(style.text_font, 20)
    text_font = style.font(style.text_font, 27)
    label = kind.upper()

    kind_width = _text_width(draw, label, kind_font)
    text_width = _text_width(draw, text, text_font)
    strip_width = kind_width + text_width + 88
    strip_height = 50

    x0 = (width - strip_width) // 2
    if position == "bottom":
        y0 = height - style.margin - bar_height - 14 - strip_height
    else:
        y0 = style.margin + bar_height + 14

    draw.rounded_rectangle(
        [x0, y0, x0 + strip_width, y0 + strip_height],
        radius=9,
        fill=WARNING_BG,
        outline=EDGE,
        width=2,
    )
    draw.text(
        (x0 + 24, y0 + strip_height / 2 - 12), label, font=kind_font, fill=WARNING_INK
    )
    rule_x = x0 + 24 + kind_width + 20
    draw.line([rule_x, y0 + 13, rule_x, y0 + strip_height - 13], fill=RULE, width=2)
    draw.text((rule_x + 20, y0 + strip_height / 2 - 16), text, font=text_font, fill=INK)
    return layer


@dataclass(frozen=True)
class CardText:
    """The words on the opening card, beyond the team names."""

    tournament: str = ""
    stage: str = ""
    condition: str = ""


def draw_title_card(
    team1: Team,
    team2: Team,
    text: CardText | None = None,
    *,
    background: Image.Image | None = None,
    style: Style | None = None,
    size: tuple[int, int] = FRAME,
) -> Image.Image:
    """Draw the card that opens the match.

    Over the first frame, blurred and darkened, rather than a flat colour: the
    card then belongs to the match it introduces — the venue, the light and the
    sky stay readable behind it.

    Args:
        team1: the team drawn on the left.
        team2: the team drawn on the right.
        text: tournament, stage and winning condition.
        background: a frame to blur behind the card; a flat ground when None.
        style: fonts and sizes.
        size: the frame to draw on.

    Returns:
        An opaque RGB-over-RGBA image of `size`.
    """
    style = style or Style()
    text = text or CardText()
    width, height = size

    if background is not None:
        card = (
            background.convert("RGB").resize(size).filter(ImageFilter.GaussianBlur(26))
        )
        card = Image.alpha_composite(
            card.convert("RGBA"), Image.new("RGBA", size, (8, 10, 14, 168))
        )
    else:
        card = Image.new("RGBA", size, (10, 12, 16, 255))

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    tournament_font = style.font(style.text_font, 32)
    meta_font = style.font(style.text_font, 24)
    versus_font = style.font(style.display_font, 52)

    if text.tournament:
        label = text.tournament.upper()
        draw.text(
            ((width - _text_width(draw, label, tournament_font)) / 2, 176),
            label,
            font=tournament_font,
            fill=(255, 255, 255, 205),
        )
    if text.stage:
        label = text.stage.upper()
        draw.text(
            ((width - _text_width(draw, label, meta_font)) / 2, 224),
            label,
            font=meta_font,
            fill=SET_LOST,
        )

    for direction, team in ((-1, team1), (1, team2)):
        centre = width // 2 + direction * 390
        logo = load_logo(team.logo, 250)
        if logo is not None:
            layer.paste(logo, (centre - logo.width // 2, 350), logo)

        label = team.name.upper()
        point_size = 84
        while (
            point_size > CARD_NAME_MIN
            and _text_width(draw, label, style.font(style.display_font, point_size))
            > CARD_NAME_WIDTH
        ):
            point_size -= 4
        name_font = style.font(style.display_font, point_size)
        draw.text(
            (centre - _text_width(draw, label, name_font) / 2, 650),
            label,
            font=name_font,
            fill=INK,
        )

    draw.text(
        ((width - _text_width(draw, "VS", versus_font)) / 2, 452),
        "VS",
        font=versus_font,
        fill=(255, 255, 255, 160),
    )

    if text.condition:
        label = text.condition.upper()
        draw.line([width / 2 - 150, 790, width / 2 + 150, 790], fill=RULE, width=2)
        draw.text(
            ((width - _text_width(draw, label, meta_font)) / 2, 812),
            label,
            font=meta_font,
            fill=(255, 255, 255, 190),
        )

    return Image.alpha_composite(card, layer)
