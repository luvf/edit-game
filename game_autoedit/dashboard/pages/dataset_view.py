"""What the database offers, and what it holds back."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from game_autoedit.dashboard import loading
from game_autoedit.data.labels import SIDES


def render() -> None:
    """Draw the dataset overview."""
    st.title("Dataset")
    catalog = loading.catalog()
    partitions = loading.partitions()

    with_sides = [
        game for game in catalog.games if loading.labels(game.game_id).has_sides
    ]
    columns = st.columns(5)
    columns[0].metric("Games exploitables", len(catalog.games))
    columns[1].metric("Écartés", len(catalog.rejected))
    columns[2].metric("Tournois", len(catalog.tournaments()))
    columns[4].metric(
        "Games avec camp",
        len(with_sides),
        help="Games dont le cut dit, pour au moins un point, quel camp l'a "
        "gagné (gauche ou droite de l'image). Seuls ceux-là apprennent la "
        "sortie « camp ». Un cut ML n'est retenu que s'il en porte : c'est la "
        "trace d'une relecture humaine.",
    )
    columns[3].metric(
        "Partition",
        f"{sum(1 for p in partitions.values() if p == 'train')} / "
        f"{sum(1 for p in partitions.values() if p == 'val')} / "
        f"{sum(1 for p in partitions.values() if p == 'test')}",
        help="train / validation / test",
    )

    rows = []
    total_kept = 0.0
    total_duration = 0.0
    for game in catalog.games:
        labels = loading.labels(game.game_id)
        duration = labels.segments[-1].end if labels.segments else 0.0
        total_kept += labels.kept_seconds
        total_duration += duration
        rows.append(
            {
                "game": game.game_id,
                "nom": game.name,
                "tournoi": game.tournament,
                "partition": partitions.get(game.game_id, "?"),
                "cut": game.cut_type,
                "points": len(labels.segments),
                "avec camp": sum(
                    1 for segment in labels.segments if segment.point in SIDES
                ),
                "gardé (min)": round(labels.kept_seconds / 60, 1),
                "durée cut médiane (s)": round(
                    float(
                        pd.Series(
                            [segment.duration for segment in labels.segments]
                        ).median()
                    ),
                    1,
                )
                if labels.segments
                else 0.0,
                "anomalies": len(labels.warnings),
            }
        )

    if rows:
        frame = pd.DataFrame(rows)
        st.subheader("Par game")
        st.dataframe(frame, width="stretch", hide_index=True)

        left, right = st.columns(2)
        with left:
            st.subheader("Points par game")
            st.bar_chart(frame["points"].value_counts().sort_index())
        with right:
            st.subheader("Games par tournoi")
            st.bar_chart(frame["tournoi"].value_counts())
    else:
        st.warning(
            "Aucun game exploitable : il faut une archive sur le disque et un "
            "fichier de cut non vide. Voir les motifs d'exclusion ci-dessous."
        )

    if catalog.rejected:
        st.subheader("Games écartés")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "game": rejection.game_id,
                        "tournoi": rejection.tournament,
                        "motif": rejection.reason,
                    }
                    for rejection in catalog.rejected
                ]
            ),
            width="stretch",
            hide_index=True,
        )
