"""Command line entry point: ``python -m game_autoedit <command>``.

The pipeline is deliberately standalone. It reads the database and the media,
writes only into its own cache, and nothing in the web app depends on it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from game_autoedit.config import AUDIO_QUALITY, SAMPLE_RATE, Paths

if TYPE_CHECKING:
    from collections.abc import Sequence


def _add_selection_args(parser: argparse.ArgumentParser) -> None:
    """Add the game-selection flags shared by every command."""
    parser.add_argument(
        "--tournament",
        action="append",
        dest="tournaments",
        metavar="NOM",
        help="restreindre à ce tournoi (répétable)",
    )
    parser.add_argument(
        "--game",
        action="append",
        dest="game_ids",
        type=int,
        metavar="ID",
        help="restreindre à ce game (répétable)",
    )
    parser.add_argument(
        "--quality",
        default=AUDIO_QUALITY,
        help=f"qualité de la source audio (défaut: {AUDIO_QUALITY})",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m game_autoedit",
        description="Génération de fichiers de cut par apprentissage.",
    )
    parser.add_argument(
        "--cache",
        metavar="DIR",
        help="racine du cache (défaut: $GAME_AUTOEDIT_CACHE)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for register in (
        _register_data_commands,
        _register_train_commands,
    ):
        register(subparsers)

    return parser


def _register_data_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the commands that only look at data."""
    inspect = subparsers.add_parser(
        "inspect", help="état du dataset: couverture, labels, anomalies"
    )
    _add_selection_args(inspect)
    inspect.add_argument(
        "--warnings",
        action="store_true",
        help="détailler les anomalies de labels game par game",
    )
    inspect.add_argument(
        "--rejected",
        action="store_true",
        help="lister les games écartés",
    )

    cache = subparsers.add_parser(
        "build-cache", help="extraire l'audio des archives vers le cache local"
    )
    _add_selection_args(cache)
    cache.add_argument(
        "--force", action="store_true", help="ré-extraire même si déjà en cache"
    )
    cache.add_argument(
        "--sample-rate",
        type=int,
        default=SAMPLE_RATE,
        help=f"fréquence d'échantillonnage (défaut: {SAMPLE_RATE})",
    )

    subparsers.add_parser("cache-status", help="taille et contenu du cache")

    embed = subparsers.add_parser(
        "build-embeddings",
        help="encoder l'audio avec un encodeur pré-entraîné gelé (une fois)",
    )
    _add_selection_args(embed)
    embed.add_argument("--encoder", default="ast", help="encodeur gelé (défaut: ast)")
    embed.add_argument("--batch-size", type=int, default=16)
    embed.add_argument(
        "--mono",
        action="store_true",
        help="encoder un seul canal au lieu de mid + side (cache séparé)",
    )
    embed.add_argument("--force", action="store_true")
    embed.add_argument("--device")


def _register_train_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the commands that train, evaluate or predict."""
    splits = subparsers.add_parser(
        "splits", help="afficher la partition train/val/test"
    )
    _add_selection_args(splits)
    _add_split_args(splits)

    train = subparsers.add_parser("train", help="entraîner un modèle")
    _add_selection_args(train)
    _add_split_args(train)
    _add_dataset_args(train)
    train.add_argument("--name", required=True, help="nom du run")
    train.add_argument("--epochs", type=int, default=30)
    train.add_argument("--batch-size", type=int, default=8)
    train.add_argument("--lr", type=float, default=3e-4, dest="learning_rate")
    train.add_argument("--num-workers", type=int, default=4)
    train.add_argument("--loss", choices=("bce", "focal"), default="bce")
    train.add_argument(
        "--limit-games", type=int, help="ne garder que N games (mise au point)"
    )
    train.add_argument("--device", help="cuda, cpu… (défaut: cuda si disponible)")
    train.add_argument("--seed", type=int, default=0)
    train.add_argument(
        "--encoder",
        help="entraîner une tête sur les plongements de cet encodeur gelé "
        "(défaut: modèle bout-en-bout sur la forme d'onde)",
    )
    train.add_argument("--head-channels", type=int, default=128)
    train.add_argument("--dropout", type=float, default=0.2)
    train.add_argument(
        "--patience",
        type=int,
        default=0,
        help="arrêter après N epochs sans progrès (0 = désactivé)",
    )

    evaluate = subparsers.add_parser(
        "evaluate", help="décoder des games entières et scorer contre la vérité"
    )
    _add_selection_args(evaluate)
    _add_split_args(evaluate)
    _add_decode_args(evaluate)
    evaluate.add_argument("--run", required=True, help="nom du run à évaluer")
    evaluate.add_argument("--part", choices=("train", "val", "test"), default="test")
    evaluate.add_argument(
        "--tolerance",
        type=float,
        default=2.0,
        help="tolérance de match, en secondes (défaut 2.0 : la précision "
        "jugée acceptable pour un montage)",
    )
    evaluate.add_argument("--per-game", action="store_true", help="détail par game")
    evaluate.add_argument("--encoder", help="encodeur gelé du run, si applicable")
    evaluate.add_argument("--device")

    predict = subparsers.add_parser(
        "predict", help="générer un fichier de cut pour une ou plusieurs games"
    )
    _add_selection_args(predict)
    _add_decode_args(predict)
    predict.add_argument("--run", required=True)
    predict.add_argument("--out", help="dossier de sortie (défaut: cache/predictions)")
    predict.add_argument(
        "--embed-curves",
        action="store_true",
        help="inclure les courbes dans le json en plus du .npz",
    )
    predict.add_argument("--encoder", help="encodeur gelé du run, si applicable")
    predict.add_argument("--device")


def _add_split_args(parser: argparse.ArgumentParser) -> None:
    """Add the partition flags."""
    parser.add_argument(
        "--holdout-tournament",
        action="append",
        dest="holdout_tournaments",
        metavar="NOM",
        help="sortir ce tournoi du train et en faire le test (répétable)",
    )
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--test-fraction", type=float, default=0.15)
    parser.add_argument("--split-seed", type=int, default=0)
    parser.add_argument(
        "--group-by",
        choices=("game", "tournament"),
        default="game",
        help="unité de tirage de la partition",
    )


def _add_dataset_args(parser: argparse.ArgumentParser) -> None:
    """Add the dataset-construction flags, the main lever on this problem."""
    group = parser.add_argument_group("construction du dataset")
    group.add_argument("--window", type=float, default=30.0, help="durée d'une fenêtre")
    group.add_argument("--hop", type=float, default=0.08, help="pas de la grille")
    group.add_argument(
        "--tolerance",
        type=float,
        default=0.5,
        help="demi-largeur positive autour d'une frontière",
    )
    group.add_argument(
        "--target-shape",
        choices=("rect", "triangle", "gaussian"),
        default="gaussian",
    )
    group.add_argument(
        "--sampling", choices=("uniform", "boundary", "dense"), default="boundary"
    )
    group.add_argument(
        "--positive-ratio",
        type=float,
        default=0.5,
        help="part des fenêtres ancrées sur une frontière",
    )
    group.add_argument("--jitter", type=float, default=8.0)
    group.add_argument(
        "--density", type=float, default=1.0, help="fenêtres par minute de game"
    )


def _add_decode_args(parser: argparse.ArgumentParser) -> None:
    """Add the decoding thresholds."""
    group = parser.add_argument_group("décodage")
    group.add_argument("--threshold-in", type=float, default=0.50)
    group.add_argument("--threshold-out", type=float, default=0.70)
    group.add_argument("--min-peak-distance", type=float, default=3.0)
    group.add_argument(
        "--min-gap",
        type=float,
        default=30.0,
        help="temps mort minimal entre deux points ; en dessous, les deux "
        "segments sont fusionnés (0 pour désactiver)",
    )
    group.add_argument("--min-duration", type=float, default=4.0)
    group.add_argument("--max-duration", type=float, default=240.0)
    group.add_argument("--inside-veto", type=float, default=0.25)
    group.add_argument(
        "--inside-weight",
        type=float,
        default=0.30,
        help="part du score d'une frontière venant de la marche de `inside`",
    )
    group.add_argument(
        "--inside-smoothing",
        type=float,
        default=0.5,
        help="largeur du lissage de `inside`, en secondes",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    from game_autoedit.bootstrap import setup_django

    setup_django()

    paths = Paths(root=Path(args.cache)) if args.cache else Paths()

    from game_autoedit import commands

    handlers = {
        "inspect": commands.inspect,
        "build-cache": commands.build_cache,
        "cache-status": lambda _args, paths: commands.cache_status(paths),
        "build-embeddings": commands.build_embeddings,
        "splits": commands.splits,
        "train": commands.train,
        "evaluate": commands.evaluate,
        "predict": commands.predict,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.error(f"commande inconnue: {args.command}")
        return 2
    return handler(args, paths)


if __name__ == "__main__":
    sys.exit(main())
