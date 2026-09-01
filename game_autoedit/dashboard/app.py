"""Dashboard entry point.

Run with ``make autoedit-dashboard`` or::

    uv run streamlit run game_autoedit/dashboard/app.py
"""

from __future__ import annotations

import streamlit as st

from game_autoedit.dashboard.pages import dataset_view, game_view, runs_view

st.set_page_config(
    page_title="game_autoedit",
    page_icon="✂️",
    layout="wide",
    initial_sidebar_state="expanded",
)

SCREENS = {
    "Game": game_view.render,
    "Runs": runs_view.render,
    "Dataset": dataset_view.render,
}

st.sidebar.title("game_autoedit")
screen = st.sidebar.radio("Écran", list(SCREENS), label_visibility="collapsed")

if st.sidebar.button(
    "Recharger les données",
    help="Vide les caches : à faire après avoir réencodé, réentraîné, ou "
    "changé le code qui lit la base. Sans ça, l'écran peut montrer l'état "
    "du dataset tel qu'il était au démarrage du serveur.",
):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()

st.sidebar.divider()
SCREENS[screen]()
