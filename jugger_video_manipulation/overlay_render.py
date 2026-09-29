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

import colorsys
import hashlib
import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFilter, ImageFont

if TYPE_CHECKING:
    from collections.abc import Sequence

    from jugger_video_manipulation.scoreboard import BoardState

FRAME = (1920, 1080)

#: How much larger than the theme's own sizes the scoreboard and warnings
#: are drawn. The opening card keeps its size.
OVERLAY_SCALE = 1.2

INK = (255, 255, 255, 255)
#: Grey rather than black, and see-through: the bar sits on the match
#: instead of covering it.
PANEL = (40, 43, 48, 200)
EDGE = (255, 255, 255, 38)
#: Finished sets sit back from the current score: they are context, not the
#: number being watched. The winner of each set is the brighter of its pair.
SET_WON = (255, 255, 255, 190)
SET_LOST = (255, 255, 255, 105)
RULE = (255, 255, 255, 78)
#: Still red enough to read as a warning, greyed and see-through like the bar.
WARNING_BG = (128, 62, 62, 160)
WARNING_INK = (255, 214, 214, 255)

#: A team name on the title card is shrunk until it fits its half of the card,
#: and never below the point where it stops being a headline.
CARD_NAME_WIDTH = 640
CARD_NAME_MIN = 40

#: Below this, a scale factor is not worth redrawing the whole theme for.
SCALE_EPSILON = 0.01


@dataclass(frozen=True)
class Team:
    """What the overlay needs to know about one team.

    Attributes:
        name: what is written.
        logo: the team's own logo; None draws a generated one instead.
        short_name: what the generated logo takes its initials from, when
            the team has one.
    """

    name: str
    logo: Path | None = None
    short_name: str = ""


@dataclass(frozen=True)
class Style:
    """Fonts, sizes and margins. One place to retheme the whole overlay."""

    display_font: Path = Path("jugger_video_manipulation/impact.ttf")
    text_font: Path = Path("/usr/share/fonts/liberation/LiberationSans-Bold.ttf")
    plain_font: Path = Path("/usr/share/fonts/liberation/LiberationSans-Regular.ttf")
    score_size: int = 36
    name_size: int = 20
    logo_size: int = 42
    #: Set numbers shrink as they pile up; a five-set match is rare but must
    #: not push the bar out of shape when it happens.
    set_sizes: tuple[int, ...] = (16, 16, 15, 14, 13)
    name_max_width: int = 210
    margin: int = 38
    radius: int = 10
    padding: int = 18
    gap: int = 15
    #: Half the gutter the centre rule sits in, and the floor under the bar's
    #: height: a one-set bar is as tall as this whatever the type does.
    centre_gap: int = 18
    bar_height: int = 60
    warning_kind_size: int = 16
    warning_text_size: int = 22
    warning_height: int = 42
    cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = field(
        default_factory=dict, compare=False, repr=False
    )

    def scaled(self, factor: float) -> Style:
        """Return the same theme, drawn for a frame `factor` times 1080p high.

        Every measurement here is in pixels of a 1080p frame. A proxy render is
        smaller, and a bar drawn at full size on it would swallow the picture:
        the overlay has to shrink with the frame it lands on, exactly as the
        opening card already does.
        """
        if abs(factor - 1.0) < SCALE_EPSILON:
            return self

        def at(value: int) -> int:
            return max(1, round(value * factor))

        return replace(
            self,
            score_size=at(self.score_size),
            name_size=at(self.name_size),
            logo_size=at(self.logo_size),
            set_sizes=tuple(at(size) for size in self.set_sizes),
            name_max_width=at(self.name_max_width),
            margin=at(self.margin),
            radius=at(self.radius),
            padding=at(self.padding),
            gap=at(self.gap),
            centre_gap=at(self.centre_gap),
            bar_height=at(self.bar_height),
            warning_kind_size=at(self.warning_kind_size),
            warning_text_size=at(self.warning_text_size),
            warning_height=at(self.warning_height),
            # Les tailles changent : le cache de polices ne se transporte pas.
            cache={},
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


#: A short name this long or shorter is already an abbreviation, drawn whole.
KEEP_WHOLE = 3


def _initials(name: str) -> str:
    """Return up to two letters that stand for a name."""
    words = [word for word in re.split(r"[\s\-_'\u2019.!]+", name) if word]
    if not words:
        return "?"
    if len(words) == 1:
        # A short name of three letters is already the abbreviation: keep it.
        word = words[0]
        return word.upper() if len(word) <= KEEP_WHOLE else word[:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _name_colour(name: str) -> tuple[int, int, int]:
    """Pick a colour from a name: the same name always gets the same one."""
    digest = hashlib.sha1(name.strip().casefold().encode("utf-8")).digest()
    red, green, blue = colorsys.hls_to_rgb(digest[0] / 255, 0.42, 0.55)
    return round(red * 255), round(green * 255), round(blue * 255)


def generated_logo(name: str, height: int, style: Style | None = None) -> Image.Image:
    """Draw a logo for a team that has none: its initials on a coloured disc.

    Drawn four times larger and scaled down, so the edge of the disc and the
    letters come out smooth at the few dozen pixels a scoreboard gives them.
    The colour comes from the name, so a team keeps its colour from one
    render to the next.
    """
    style = style or Style()
    size = max(height, 8)
    big = size * 4
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        [0, 0, big - 1, big - 1],
        fill=(*_name_colour(name), 255),
        outline=(255, 255, 255, 235),
        width=max(big // 24, 1),
    )
    label = _initials(name)
    # Two letters fill the disc at 46 % of its size; three are shrunk until
    # they fit inside it with a margin.
    point_size = max(int(big * 0.46), 8)
    font = style.font(style.display_font, point_size)
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    while right - left > big * 0.7 and point_size > 8:  # noqa: PLR2004
        point_size -= max(big // 50, 1)
        font = style.font(style.display_font, point_size)
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    draw.text(
        ((big - (right - left)) / 2 - left, (big - (bottom - top)) / 2 - top),
        label,
        font=font,
        fill=INK,
    )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def team_logo(team: Team, height: int, style: Style | None = None) -> Image.Image:
    """Return the team's own logo at `height`, or a generated one if it has none."""
    return load_logo(team.logo, height) or generated_logo(
        team.short_name or team.name, height, style
    )


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
    logo = team_logo(team, style.logo_size, style) if show_logos else None

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


@dataclass(frozen=True)
class BarLayout:
    """The bar's measurements, fixed for a whole match.

    Measured once over every state the board will show, so the bar keeps one
    size from the first point to the last: a score going from 9 to 10, a set
    closing, the teams changing ends — nothing makes it grow, shrink or shift
    its names. The room a two-digit score or the set history will need is
    kept from the start.

    Attributes:
        half: width of each half of the bar, the widest either side needs.
        rows: set rows the history column is sized for.
        score_width: the widest score of the match.
        sets_width: the widest finished-set score; 0 when no set closes.
    """

    half: int
    rows: int
    score_width: int
    sets_width: int


def scoreboard_layout(
    states: Sequence[BoardState],
    teams: dict[str, Team],
    *,
    style: Style | None = None,
    show_logos: bool = True,
    show_history: bool = True,
    size: tuple[int, int] = FRAME,
) -> BarLayout:
    """Measure the bar for every state of a match at once.

    Args:
        states: every state the board will show.
        teams: the two teams, keyed by the names used in the states.
        style: fonts and sizes, as `draw_scoreboard` receives them.
        show_logos: whether logos take room.
        show_history: whether finished sets take room.
        size: the frame the bar is drawn on.

    Returns:
        The measurements to draw every state with.
    """
    style = (style or Style()).scaled(OVERLAY_SCALE * size[1] / FRAME[1])
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    score_font = style.font(style.display_font, style.score_size)
    name_font = style.font(style.text_font, style.name_size)

    rows = 1
    if show_history:
        rows = max([len(state.finished_sets) for state in states] + [1])
    set_font = style.font(style.text_font, style.set_size(rows))

    score_width = max(
        (
            math.ceil(_text_width(draw, str(score), score_font))
            for state in states
            for score in (state.left_score, state.right_score)
        ),
        default=0,
    )
    sets_width = 0
    if show_history:
        sets_width = max(
            (
                math.ceil(_text_width(draw, str(value), set_font))
                for state in states
                for finished in state.finished_sets
                for value in (finished.team1, finished.team2)
            ),
            default=0,
        )

    team_width = 0
    for key in {key for state in states for key in (state.left, state.right)}:
        team = teams.get(key, Team(key))
        name = truncate(draw, team.name, name_font, style.name_max_width)
        width = math.ceil(_text_width(draw, name, name_font))
        if show_logos:
            width += style.gap + team_logo(team, style.logo_size, style).width
        team_width = max(team_width, width)

    half = score_width + style.gap + team_width
    if sets_width:
        half += sets_width + style.gap
    return BarLayout(
        half=half, rows=rows, score_width=score_width, sets_width=sets_width
    )


def draw_scoreboard(  # noqa: PLR0913 — display options, all keyword-only
    state: BoardState,
    teams: dict[str, Team],
    *,
    style: Style | None = None,
    position: str = "bottom",
    show_logos: bool = True,
    show_history: bool = True,
    size: tuple[int, int] = FRAME,
    layout: BarLayout | None = None,
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
        layout: the match's measurements, from `scoreboard_layout`. Every
            state of a match must be drawn with the same one, or the bar
            changes size between points; left out, it is measured on this
            state alone.

    Returns:
        An RGBA image of `size`, transparent outside the bar.
    """
    layout = layout or scoreboard_layout(
        [state],
        teams,
        style=style,
        show_logos=show_logos,
        show_history=show_history,
        size=size,
    )
    style = (style or Style()).scaled(OVERLAY_SCALE * size[1] / FRAME[1])
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

    rows = layout.rows
    set_font = style.font(style.text_font, style.set_size(rows))
    plain_font = style.font(style.plain_font, style.set_size(rows))
    line = round(style.set_size(rows) * 1.16)

    bar_height = max(style.bar_height, rows * line + style.gap)
    half = layout.half
    bar_width = half * 2 + style.padding * 2 + style.centre_gap * 2

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
    inset = bar_height // 5
    draw.line(
        [centre_x, y0 + inset, centre_x, y0 + bar_height - inset], fill=RULE, width=2
    )

    score_font = style.font(style.display_font, style.score_size)
    name_font = style.font(style.text_font, style.name_size)

    for key, direction in (("left", -1), ("right", 1)):
        side = sides[key]
        cursor = centre_x + direction * style.centre_gap

        score_width = _text_width(draw, side.score, score_font)
        draw.text(
            (
                cursor - score_width if direction < 0 else cursor,
                middle_y
                - _text_height(draw, side.score, score_font) / 2
                - style.score_size / 5,
            ),
            side.score,
            font=score_font,
            fill=INK,
        )
        # The slot of the widest score of the match: a second digit takes
        # room kept for it, and nothing further out moves.
        cursor += direction * (layout.score_width + style.gap)

        if layout.sets_width:
            top = middle_y - (len(side.sets) * line) / 2
            for index, (value, won) in enumerate(side.sets):
                font = set_font if won else plain_font
                value_width = _text_width(draw, value, font)
                # Right-align each column against the centre, so the digits
                # stack cleanly whether they are one or two wide.
                x = (
                    cursor - value_width
                    if direction < 0
                    else cursor + (layout.sets_width - value_width)
                )
                draw.text(
                    (x, top + index * line),
                    value,
                    font=font,
                    fill=SET_WON if won else SET_LOST,
                )
            cursor += direction * (layout.sets_width + style.gap)

        name_width = _text_width(draw, side.name, name_font)
        draw.text(
            (
                cursor - name_width if direction < 0 else cursor,
                middle_y
                - _text_height(draw, side.name, name_font) / 2
                - style.name_size / 7,
            ),
            side.name,
            font=name_font,
            fill=INK,
        )

        if side.logo is not None:
            # Against the end of the bar rather than after the name: the two
            # logos then sit at the same distance from the middle whatever the
            # names measure, and the bar reads as two symmetrical halves.
            edge = (
                x0 + style.padding
                if direction < 0
                else x0 + bar_width - style.padding - side.logo.width
            )
            layer.paste(
                side.logo,
                (int(edge), middle_y - side.logo.height // 2),
                side.logo,
            )

    return layer


def draw_warning(
    kind: str,
    text: str,
    *,
    style: Style | None = None,
    position: str = "bottom",
    bar_height: int | None = None,
    row: int = 0,
    size: tuple[int, int] = FRAME,
) -> Image.Image:
    """Draw the warning strip, on a transparent frame.

    It sits at the top of the picture, where the action rarely is, whatever
    edge the scoreboard took. A board that is up there too pushes it down just
    under the bar, so the two never share a band of picture.

    Args:
        kind: the warning type, shown small and in capitals.
        text: the free text, shown large.
        style: fonts and sizes.
        position: where the scoreboard is; only `top` concerns the strip,
            which then starts under the bar rather than at the margin.
        bar_height: how tall the scoreboard is, for the same reason; the
            theme's own bar height when omitted.
        row: which slot down from the top the strip takes. Row 0 is the
            highest; each row after that is one strip lower, which is how two
            warnings shown at the same time stay readable instead of printing
            over each other.
        size: the frame to draw on.

    Returns:
        An RGBA image of `size`, transparent outside the strip.
    """
    style = (style or Style()).scaled(OVERLAY_SCALE * size[1] / FRAME[1])
    width = size[0]
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    kind_font = style.font(style.text_font, style.warning_kind_size)
    text_font = style.font(style.text_font, style.warning_text_size)
    label = kind.upper()

    bar = style.bar_height if bar_height is None else bar_height
    kind_width = _text_width(draw, label, kind_font)
    text_width = _text_width(draw, text, text_font)
    strip_width = kind_width + text_width + style.padding * 4
    strip_height = style.warning_height
    stack_gap = style.gap - 3

    x0 = (width - strip_width) // 2
    # The first row is as high as the picture allows; the rest pile downwards.
    top = style.margin + (bar + stack_gap if position == "top" else 0)
    y0 = top + row * (strip_height + stack_gap)

    draw.rounded_rectangle(
        [x0, y0, x0 + strip_width, y0 + strip_height],
        radius=style.radius - 1,
        fill=WARNING_BG,
        outline=EDGE,
        width=2,
    )
    pad = style.padding + 2
    draw.text(
        (x0 + pad, y0 + strip_height / 2 - style.warning_kind_size * 0.62),
        label,
        font=kind_font,
        fill=WARNING_INK,
    )
    rule_x = x0 + pad + kind_width + style.gap
    inset = strip_height // 4
    draw.line(
        [rule_x, y0 + inset, rule_x, y0 + strip_height - inset], fill=RULE, width=2
    )
    draw.text(
        (rule_x + style.gap, y0 + strip_height / 2 - style.warning_text_size * 0.72),
        text,
        font=text_font,
        fill=INK,
    )
    return layer


@dataclass(frozen=True)
class CardText:
    """The words on the opening card, beyond the team names.

    Two lines only, both meant for a viewer: where the match is played, and
    what it takes to win it. The cut's own name never appears — it is an
    internal label, chosen to find the file again, not to be read on screen.
    """

    tournament: str = ""
    condition: str = ""


def draw_title_card(
    team1: Team,
    team2: Team,
    text: CardText | None = None,
    *,
    background: Image.Image | None = None,
    style: Style | None = None,
    size: tuple[int, int] = FRAME,
    transparent: bool = False,
) -> Image.Image:
    """Draw the card that opens the match.

    Over the first frame, blurred and darkened, rather than a flat colour: the
    card then belongs to the match it introduces — the venue, the light and the
    sky stay readable behind it.

    Args:
        team1: the team drawn on the left.
        team2: the team drawn on the right.
        text: tournament and winning condition.
        background: a frame to blur behind the card; a flat ground when None.
        style: fonts and sizes.
        size: the frame to draw on.
        transparent: draw the words and logos alone, on nothing, for the
            render to lay over the blurred match itself.

    Returns:
        An RGBA image of `size`: opaque, or transparent around the words.
    """
    style = style or Style()
    text = text or CardText()
    width, height = size
    # The card is laid out for a 1080-tall frame and scaled from there, so a
    # proxy render gets the same composition rather than the same pixel
    # offsets — which would put the logos off the bottom of the picture.
    k = height / 1080

    if background is not None:
        blur = max(int(26 * k), 1)
        card = (
            background.convert("RGB")
            .resize(size)
            .filter(ImageFilter.GaussianBlur(blur))
        )
        card = Image.alpha_composite(
            card.convert("RGBA"), Image.new("RGBA", size, (8, 10, 14, 168))
        )
    else:
        card = Image.new("RGBA", size, (10, 12, 16, 255))

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    tournament_font = style.font(style.text_font, max(int(32 * k), 8))
    meta_font = style.font(style.text_font, max(int(24 * k), 7))
    versus_font = style.font(style.display_font, max(int(52 * k), 10))

    if text.tournament:
        label = text.tournament.upper()
        draw.text(
            ((width - _text_width(draw, label, tournament_font)) / 2, 176 * k),
            label,
            font=tournament_font,
            fill=(255, 255, 255, 205),
        )

    for direction, team in ((-1, team1), (1, team2)):
        centre = width // 2 + int(direction * 390 * k)
        logo = team_logo(team, max(int(250 * k), 16), style)
        if logo is not None:
            layer.paste(logo, (centre - logo.width // 2, int(350 * k)), logo)

        label = team.name.upper()
        point_size = max(int(84 * k), CARD_NAME_MIN)
        limit = CARD_NAME_WIDTH * k
        while (
            point_size > CARD_NAME_MIN * k
            and _text_width(draw, label, style.font(style.display_font, point_size))
            > limit
        ):
            point_size -= max(int(4 * k), 1)
        name_font = style.font(style.display_font, max(point_size, 8))
        draw.text(
            (centre - _text_width(draw, label, name_font) / 2, 650 * k),
            label,
            font=name_font,
            fill=INK,
        )

    draw.text(
        ((width - _text_width(draw, "VS", versus_font)) / 2, 452 * k),
        "VS",
        font=versus_font,
        fill=(255, 255, 255, 160),
    )

    if text.condition:
        label = text.condition.upper()
        draw.line(
            [width / 2 - 150 * k, 790 * k, width / 2 + 150 * k, 790 * k],
            fill=RULE,
            width=max(int(2 * k), 1),
        )
        draw.text(
            ((width - _text_width(draw, label, meta_font)) / 2, 812 * k),
            label,
            font=meta_font,
            fill=(255, 255, 255, 190),
        )

    if transparent:
        return layer
    return Image.alpha_composite(card, layer)
