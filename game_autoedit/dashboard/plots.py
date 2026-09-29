"""The figures the dashboard draws.

The game view is the point of the whole thing: the three probability curves
along the game, the segments a human kept, the segments the model proposes, and
where the two disagree — all on one time axis you can zoom into.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go

from game_autoedit.datasets.targets import CHANNEL_INDEX

if TYPE_CHECKING:
    import numpy as np

    from game_autoedit.data.labels import GameLabels, Segment
    from game_autoedit.eval.decode import DecodeSpec

COLOURS = {"in": "#2E86DE", "out": "#E55039", "inside": "#8395A7"}

# How a side reads on a segment bar: the picture's left or right.
SIDE_MARK = {"left": "G", "right": "D"}
SIDE_NAME = {"left": "gauche", "right": "droite"}
TRUTH = "#10AC84"
PREDICTED = "#EE5A24"


def _segments_band(
    figure: go.Figure,
    segments: list[Segment],
    row: float,
    colour: str,
    name: str,
    sides: list[tuple[str, float]] | None = None,
) -> None:
    """Draw one row of segment bars, each marked with who won it when known.

    `sides` is the model's guess and its confidence, one per segment; without
    it, a segment shows the side its cut records, if any.
    """
    for index, segment in enumerate(segments):
        side, confidence = sides[index] if sides is not None else (segment.point, None)
        won = (
            f"<br>gagné à {SIDE_NAME[side]}"
            + (f" (confiance {confidence:.0%})" if confidence is not None else "")
            if side in SIDE_NAME
            else ""
        )
        figure.add_trace(
            go.Scatter(
                x=[segment.start, segment.end],
                y=[row, row],
                mode="lines",
                line={"color": colour, "width": 14},
                name=name,
                legendgroup=name,
                showlegend=index == 0,
                hovertemplate=(
                    f"{name}<br>%{{x:.1f}}s "
                    f"(durée {segment.duration:.0f}s){won}<extra></extra>"
                ),
            )
        )
        if side in SIDE_MARK:
            figure.add_annotation(
                x=(segment.start + segment.end) / 2,
                y=row,
                text=SIDE_MARK[side] + ("?" if sides is not None else ""),
                showarrow=False,
                font={"size": 10, "color": "white"},
            )


def game_figure(
    times: np.ndarray,
    probabilities: np.ndarray,
    truth: GameLabels,
    predicted: list[Segment],
    decode_spec: DecodeSpec,
    *,
    show: tuple[str, ...] = ("in", "out", "inside"),
    sides: list[tuple[str, float]] | None = None,
) -> go.Figure:
    """Build the game view.

    Args:
        times: the centre time of every step.
        probabilities: ``(steps, 3)`` in channel order.
        truth: the cut a human actually made.
        predicted: the segments the decoder produced.
        decode_spec: the triggers in force, drawn as reference lines.
        show: which channels to draw.
        sides: the side the run's classifier gives each predicted segment.

    Returns:
        A figure with the curves on top and the two cuts underneath.
    """
    figure = go.Figure()

    for channel in show:
        figure.add_trace(
            go.Scattergl(
                x=times,
                y=probabilities[:, CHANNEL_INDEX[channel]],
                mode="lines",
                name=channel,
                line={"color": COLOURS[channel], "width": 1.2},
                hovertemplate=f"{channel} %{{y:.2f}} à %{{x:.1f}}s<extra></extra>",
            )
        )

    for channel in show:
        if channel == "inside":
            continue
        figure.add_hline(
            y=decode_spec.threshold.get(channel, 0.5),
            line={"color": COLOURS[channel], "width": 1, "dash": "dot"},
            opacity=0.5,
        )

    _segments_band(figure, truth.segments, -0.12, TRUTH, "vérité")
    _segments_band(figure, predicted, -0.25, PREDICTED, "prédit", sides)

    figure.update_layout(
        height=460,
        margin={"l": 40, "r": 20, "t": 30, "b": 40},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.1},
        xaxis={"title": "temps (s)", "rangeslider": {"visible": True}},
        yaxis={"title": "probabilité", "range": [-0.35, 1.05]},
    )
    return figure


def history_figure(history: list[dict[str, float]]) -> go.Figure:
    """Plot a run's training history: losses on the left, AP on the right."""
    figure = go.Figure()
    epochs = [entry["epoch"] for entry in history]

    for key, name, colour in (
        ("train_loss", "loss train", "#8395A7"),
        ("val_loss", "loss val", "#576574"),
    ):
        figure.add_trace(
            go.Scatter(
                x=epochs,
                y=[entry.get(key) for entry in history],
                name=name,
                line={"color": colour},
            )
        )

    for channel in ("in", "out", "inside"):
        figure.add_trace(
            go.Scatter(
                x=epochs,
                y=[entry.get(f"ap_{channel}") for entry in history],
                name=f"AP {channel}",
                yaxis="y2",
                line={"color": COLOURS[channel], "dash": "dash"},
            )
        )

    figure.update_layout(
        height=380,
        margin={"l": 40, "r": 40, "t": 30, "b": 40},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.15},
        xaxis={"title": "epoch"},
        yaxis={"title": "loss"},
        yaxis2={"title": "AP", "overlaying": "y", "side": "right", "range": [0, 1]},
    )
    return figure
