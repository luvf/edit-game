"""Training runs: what was tried, and what it gave."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from game_autoedit.dashboard import loading
from game_autoedit.dashboard.plots import history_figure


def _summary_row(run: loading.RunInfo) -> dict[str, object]:
    """Return one line of the comparison table."""
    best = run.best or {}
    train = run.config.get("train", {})
    dataset = run.config.get("dataset", {})
    return {
        "run": run.name,
        "encodeur": run.encoder or "bout-en-bout",
        "epochs": len(run.history),
        "meilleure epoch": best.get("epoch"),
        "score sélection": round(best.get("selection_score", float("nan")), 4),
        "AP in": round(best.get("ap_in", float("nan")), 3),
        "AP out": round(best.get("ap_out", float("nan")), 3),
        "AP inside": round(best.get("ap_inside", float("nan")), 3),
        "val loss": round(best.get("val_loss", float("nan")), 4),
        "tirage": dataset.get("sampling", {}).get("strategy"),
        "fenêtre (s)": dataset.get("window", {}).get("duration"),
        "tolérance (s)": dataset.get("target", {}).get("tolerance"),
        "loss": train.get("loss"),
    }


def render() -> None:
    """Draw the runs comparison."""
    st.title("Runs")
    available = loading.runs()
    if not available:
        st.info("Aucun run entraîné. Lancer `python -m game_autoedit train`.")
        return

    st.subheader("Comparaison")
    st.dataframe(
        pd.DataFrame([_summary_row(run) for run in available]),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Le score de sélection est l'AP moyenne des canaux in et out : c'est "
        "sur lui que le meilleur checkpoint est retenu, pas sur la val loss, "
        "qui diverge bien avant que les frontières cessent de progresser."
    )

    chosen = st.selectbox("Détail du run", [run.name for run in available])
    run = next(item for item in available if item.name == chosen)

    if run.history:
        st.plotly_chart(history_figure(run.history), width="stretch")
        st.dataframe(pd.DataFrame(run.history), width="stretch", hide_index=True)
    with st.expander("Configuration complète"):
        st.json(run.config)
