"""Cached access to everything the dashboard displays.

Every loader is keyed on plain strings and integers so Streamlit can cache it.
Models are cached as resources — loaded once per session — while curves are
cached as data, since a game's curves are a few megabytes and recomputing them
on every widget change would make the page unusable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import streamlit as st

from game_autoedit.config import Paths

if TYPE_CHECKING:
    import numpy as np

    from game_autoedit.data.catalog import Catalog, LabeledGame
    from game_autoedit.data.labels import GameLabels


def paths() -> Paths:
    """Return the cache paths."""
    return Paths()


@st.cache_resource
def _django() -> bool:
    """Configure Django once per session, and check the registry is whole.

    Django cannot re-import a model: a partial reload leaves a fresh `Game`
    class whose reverse relations were never built, and the next query fails
    deep inside the ORM with a message that says nothing about the cause. The
    check below turns that into something actionable.

    Raises:
        RuntimeError: when the model registry is half-built.
    """
    from game_autoedit.bootstrap import setup_django

    setup_django()

    from core.models.game import Game

    related = {field.name for field in Game._meta.get_fields()}  # noqa: SLF001
    if "cuts" not in related:
        message = (
            "Le registre de modèles Django est incomplet : Game n'a pas sa "
            "relation 'cuts'. Un module de core/models a été ré-importé sans "
            "les autres. Redémarrer le serveur, et vérifier que "
            ".streamlit/config.toml exclut bien 'core' de folderWatchBlacklist."
        )
        raise RuntimeError(message)
    return True


@st.cache_data(ttl=300)
def catalog() -> Catalog:
    """Return the usable games and the rejected ones."""
    _django()
    from game_autoedit.data.catalog import build_catalog

    return build_catalog()


@st.cache_data(ttl=300)
def partitions(seed: int = 0, val_fraction: float = 0.15) -> dict[int, str]:
    """Return which partition each game belongs to."""
    from game_autoedit.datasets.splits import SplitSpec, make_split

    split = make_split(catalog().games, SplitSpec(seed=seed, val_fraction=val_fraction))
    return {
        game.game_id: part
        for part in ("train", "val", "test")
        for game in getattr(split, part)
    }


@dataclass(frozen=True)
class RunInfo:
    """One training run on disk."""

    name: str
    encoder: str | None
    history: list[dict[str, Any]]
    config: dict[str, Any]

    @property
    def best(self) -> dict[str, Any] | None:
        """Return the epoch with the best selection score."""
        scored = [entry for entry in self.history if "selection_score" in entry]
        return max(scored, key=lambda e: e["selection_score"]) if scored else None


@st.cache_data(ttl=60)
def runs() -> list[RunInfo]:
    """Return every run found in the cache, newest first."""
    root = paths().runs
    if not root.exists():
        return []

    found: list[RunInfo] = []
    for directory in sorted(root.iterdir(), key=lambda p: -p.stat().st_mtime):
        if not (directory / "best.pt").exists():
            continue
        config: dict[str, Any] = {}
        history: list[dict[str, Any]] = []
        if (directory / "run.json").exists():
            config = json.loads((directory / "run.json").read_text())
        if (directory / "history.json").exists():
            history = json.loads((directory / "history.json").read_text())
        found.append(
            RunInfo(
                name=directory.name,
                encoder=config.get("encoder"),
                history=history,
                config=config,
            )
        )
    return found


@st.cache_resource
def loaded_run(name: str) -> Any:
    """Load a trained run onto the best available device."""
    _django()
    from game_autoedit.runs import load_run, resolve_device

    return load_run(paths().runs / name, resolve_device(None))


@st.cache_data(ttl=600, show_spinner="Calcul des courbes…")
def curves(run_name: str, game_id: int) -> tuple[np.ndarray, np.ndarray]:
    """Return the probability curves and their times for one game."""
    from game_autoedit.data.embeddings import EmbeddingStore
    from game_autoedit.datasets.dataset import prepare_games
    from game_autoedit.eval.inference import predict_game
    from game_autoedit.eval.whole_game import predict_whole_game
    from game_autoedit.runs import resolve_device

    run = loaded_run(run_name)
    device = resolve_device(None)

    if run.on_embeddings:
        store = EmbeddingStore.open(paths().embeddings(run.encoder))
        if store is None:
            message = f"cache de plongements '{run.encoder}' absent"
            raise FileNotFoundError(message)
        return predict_whole_game(
            run.model, store, game_id, device, receptive_field=run.receptive_field
        )

    game = game_by_id(game_id)
    prepared, _ = prepare_games([game], paths())
    if not prepared:
        message = f"audio du game {game_id} absent du cache"
        raise FileNotFoundError(message)
    return predict_game(
        run.model,
        prepared[0].audio_path,
        duration=prepared[0].duration,
        spec=run.dataset,
        device=device,
        batch_size=8,
    )


def game_by_id(game_id: int) -> LabeledGame:
    """Return one usable game by its identifier.

    Raises:
        KeyError: when the game is not in the catalog.
    """
    for game in catalog().games:
        if game.game_id == game_id:
            return game
    raise KeyError(game_id)


@st.cache_data(ttl=600)
def labels(game_id: int, duration: float | None = None) -> GameLabels:
    """Return the checked label timeline of one game."""
    from game_autoedit.data.labels import load_labels

    game = game_by_id(game_id)
    return load_labels(
        game.cut_json_path, game_id=game_id, fps=game.fps, duration=duration
    )
