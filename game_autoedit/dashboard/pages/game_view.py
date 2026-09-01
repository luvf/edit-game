"""The game viewer: curves, cuts, and where the two disagree."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import streamlit as st

from game_autoedit.dashboard import loading
from game_autoedit.dashboard.plots import game_figure
from game_autoedit.eval.decode import DecodeSpec, decode
from game_autoedit.eval.metrics import match_boundaries, score_segments

if TYPE_CHECKING:
    from game_autoedit.eval.metrics import BoundaryScore, SegmentScore

PARTITION_LABEL = {
    "train": "entraînement",
    "val": "validation",
    "test": "TEST — jamais utilisé pour régler quoi que ce soit",
}


def _decode_controls() -> DecodeSpec:
    """Draw the decoding controls and return the spec they describe."""
    st.sidebar.subheader("Décodage")
    threshold_in = st.sidebar.slider("Seuil in", 0.05, 0.99, 0.50, 0.05)
    threshold_out = st.sidebar.slider("Seuil out", 0.05, 0.99, 0.70, 0.05)
    min_duration = st.sidebar.slider("Durée minimale (s)", 1.0, 30.0, 4.0, 1.0)
    max_duration = st.sidebar.slider("Durée maximale (s)", 30.0, 400.0, 240.0, 10.0)
    inside_veto = st.sidebar.slider("Veto « dans un cut »", 0.0, 0.9, 0.25, 0.05)
    return DecodeSpec(
        threshold={"in": threshold_in, "out": threshold_out},
        min_duration=min_duration,
        max_duration=max_duration,
        inside_veto=inside_veto,
    )


def _game_picker(partitions: dict[int, str]) -> int | None:
    """Draw the game selector and return the chosen game id."""
    games = loading.catalog().games
    if not games:
        st.sidebar.warning("Aucun game exploitable dans le catalogue.")
        return None
    tournaments = sorted({game.tournament for game in games})
    chosen = st.sidebar.selectbox(
        "Tournoi", ["tous", *tournaments], key="tournament_filter"
    )
    if chosen != "tous":
        games = [game for game in games if game.tournament == chosen]

    parts = st.sidebar.multiselect(
        "Partition", ["train", "val", "test"], default=["val"]
    )
    if parts:
        games = [game for game in games if partitions.get(game.game_id) in parts]
    if not games:
        st.sidebar.warning("Aucun game avec ces filtres.")
        return None

    labelled = {
        f"{game.game_id} — {game.name[:40]} ({partitions.get(game.game_id, '?')})": game.game_id
        for game in games
    }
    return labelled[st.sidebar.selectbox("Game", list(labelled))]


def _cost_row(score: SegmentScore, boundary: dict[str, BoundaryScore]) -> None:
    """Draw the repair-cost metrics."""
    cells: list[tuple[str, str, str]] = [
        ("Points manqués", str(score.missed_points), "à retrouver en scrubbant"),
        ("Segments en trop", str(score.extra_segments), "un clic pour supprimer"),
        ("Fusionnés", str(score.merged_segments), "recouvrent plusieurs points"),
        ("Coupés en deux", str(score.split_points), "à recoller"),
        ("IoU", f"{score.iou:.3f}", "recouvrement temporel"),
        (
            "Rappel in / out",
            f"{boundary['in'].recall:.2f} / {boundary['out'].recall:.2f}",
            "frontières retrouvées dans la tolérance",
        ),
    ]
    for column, (label, value, help_text) in zip(
        st.columns(len(cells)), cells, strict=True
    ):
        column.metric(label, value, help=help_text)


def render() -> None:
    """Draw the game viewer."""
    st.title("Game")

    available = loading.runs()
    if not available:
        st.info("Aucun run entraîné. Lancer `python -m game_autoedit train`.")
        return

    run_name = st.sidebar.selectbox("Run", [run.name for run in available])
    partitions = loading.partitions()
    game_id = _game_picker(partitions)
    if game_id is None:
        return

    part = partitions.get(game_id, "?")
    if part == "test":
        st.warning(
            "Ce game est dans le jeu de **test**. Le regarder pour choisir un "
            "réglage le transforme en jeu de validation : les chiffres finaux "
            "ne voudront plus rien dire."
        )
    else:
        st.caption(f"Partition : {PARTITION_LABEL.get(part, part)}")

    decode_spec = _decode_controls()
    tolerance = st.sidebar.slider("Tolérance de match (s)", 0.25, 5.0, 0.5, 0.25)
    show = st.sidebar.multiselect(
        "Courbes affichées", ["in", "out", "inside"], default=["in", "out", "inside"]
    )

    try:
        probabilities, times = loading.curves(run_name, game_id)
    except (FileNotFoundError, KeyError) as error:
        st.error(f"Impossible de calculer les courbes : {error}")
        return

    duration = float(times[-1]) if len(times) else 0.0
    truth = loading.labels(game_id, duration)
    decoded = decode(probabilities, times, decode_spec)

    score = score_segments(decoded.segments, truth.segments, duration=duration)
    boundary = {
        "in": match_boundaries(
            [segment.start for segment in decoded.segments],
            truth.ins,
            channel="in",
            tolerance=tolerance,
        ),
        "out": match_boundaries(
            [segment.end for segment in decoded.segments],
            truth.outs,
            channel="out",
            tolerance=tolerance,
        ),
    }
    _cost_row(score, boundary)

    st.plotly_chart(
        game_figure(
            times,
            probabilities,
            truth,
            decoded.segments,
            decode_spec,
            show=tuple(show),
        ),
        width="stretch",
    )
    st.caption(
        f"{len(truth.segments)} points dans le montage humain, "
        f"{len(decoded.segments)} proposés — durée {duration / 60:.1f} min. "
        "Les pointillés marquent les seuils de déclenchement."
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Écarts de placement")
        for channel, key in (("in", "ins"), ("out", "outs")):
            distances = _nearest_distances(
                [
                    segment.start if channel == "in" else segment.end
                    for segment in decoded.segments
                ],
                getattr(truth, key),
            )
            if distances.size:
                st.write(
                    f"**{channel}** — médiane {np.median(distances):.2f} s, "
                    f"{100 * (distances <= 1.0).mean():.0f} % à moins d'une seconde"
                )
    with right:
        st.subheader("À vérifier")
        if decoded.dropped:
            st.write("\n".join(f"- {reason}" for reason in decoded.dropped[:12]))
        else:
            st.write("Rien de rejeté par le décodeur.")


def _nearest_distances(predicted: list[float], truth: list[float]) -> np.ndarray:
    """Return, for each true boundary, the distance to the nearest prediction."""
    if not predicted or not truth:
        return np.array([])
    proposals = np.array(predicted)
    return np.array([float(np.min(np.abs(proposals - t))) for t in truth])
