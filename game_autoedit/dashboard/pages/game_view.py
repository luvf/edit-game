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

# What each curve answers, shown when its toggle is hovered.
CURVE_HELP = {
    "in": "Probabilité qu'un point commence à cet instant. Le canal le plus "
    "sûr : écart médian de 0.47 s, 90 % des débuts à moins de 2 s.",
    "out": "Probabilité qu'un point se termine à cet instant. Le modèle "
    "trouve 8 fins sur 10 à moins de 2 s, mais les place mal : seulement "
    "28 % tombent à moins d'une demi-seconde.",
    "inside": "Probabilité d'être à l'intérieur d'un point. Le canal le plus "
    "facile (AP 0.95) ; c'est lui qui donne aux deux autres le contexte "
    "qui distingue une fin d'un début.",
}


def _decode_controls() -> DecodeSpec:
    """Draw the decoding controls and return the spec they describe."""
    st.sidebar.subheader("Décodage")
    threshold_in = st.sidebar.slider(
        "Seuil in",
        0.05,
        0.99,
        0.50,
        0.05,
        help="Hauteur minimale d'un pic pour retenir un début de point. "
        "Le descendre rattrape des points manqués au prix de segments "
        "inventés — et un point manqué se cherche en scrubbant, un segment "
        "en trop se supprime d'un clic. Mesuré sur la validation : "
        "0.20 → 2.1 points manqués par game, 0.90 → 4.5.",
    )
    threshold_out = st.sidebar.slider(
        "Seuil out",
        0.05,
        0.99,
        0.70,
        0.05,
        help="Hauteur minimale d'un pic pour retenir une fin de point. "
        "Contre-intuitif : le monter réduit à la fois les points manqués et "
        "les segments en trop, parce qu'une fin prématurée tronque un vrai "
        "point — un point manqué déguisé en erreur bénigne. "
        "0.30 → 4.2 points manqués par game, 0.70 → 2.3.",
    )
    min_duration = st.sidebar.slider(
        "Durée minimale (s)",
        1.0,
        30.0,
        4.0,
        1.0,
        help="Un segment plus court est rejeté. Pour comparaison, les vrais "
        "points durent 25 s en médiane et 16 s au dixième centile : "
        "au-delà de ~15 s on commence à jeter de vrais points.",
    )
    max_duration = st.sidebar.slider(
        "Durée maximale (s)",
        30.0,
        400.0,
        240.0,
        10.0,
        help="Au-delà, une fin a forcément été manquée et le segment avale "
        "plusieurs points. Le plus long point réel du dataset fait 205 s.",
    )
    inside_veto = st.sidebar.slider(
        "Veto « dans un cut »",
        0.0,
        0.9,
        0.25,
        0.05,
        help="Un segment dont la probabilité moyenne d'être dans un point "
        "reste sous ce niveau est rejeté, même si ses deux frontières sont "
        "nettes. C'est le garde-fou contre une paire de pics fortuite dans "
        "du temps mort.",
    )
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
    tolerance = st.sidebar.slider(
        "Tolérance de match (s)",
        0.25,
        5.0,
        0.5,
        0.25,
        help="Distance maximale entre une frontière prédite et la vraie pour "
        "la compter comme trouvée. Ne mesure rien en dessous de 0.5 s : les "
        "labels eux-mêmes ne valent pas mieux que ça. À ±2 s, le rappel "
        "passe de 0.48 à 0.80 sur les débuts et de 0.16 à 0.46 sur les fins.",
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
            show=_curve_toggles(),
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


def _curve_toggles() -> tuple[str, ...]:
    """Draw the per-curve toggles and return the channels to draw."""
    columns = st.columns([1, 1, 1, 6])
    shown = [
        channel
        for column, channel in zip(columns, CURVE_HELP, strict=False)
        if column.toggle(channel, value=True, help=CURVE_HELP[channel])
    ]
    return tuple(shown)


def _nearest_distances(predicted: list[float], truth: list[float]) -> np.ndarray:
    """Return, for each true boundary, the distance to the nearest prediction."""
    if not predicted or not truth:
        return np.array([])
    proposals = np.array(predicted)
    return np.array([float(np.min(np.abs(proposals - t))) for t in truth])
