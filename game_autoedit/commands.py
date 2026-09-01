"""Implementations behind the CLI subcommands.

Each one prints a report meant to be read in a terminal while iterating; none
of them writes to the database.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from game_autoedit.data.audio import audio_info, build_audio_cache, probe_duration
from game_autoedit.data.catalog import build_catalog
from game_autoedit.data.labels import load_labels
from game_autoedit.datasets.dataset import prepare_games
from game_autoedit.datasets.targets import CHANNELS

if TYPE_CHECKING:
    import argparse

    from game_autoedit.config import Paths
    from game_autoedit.data.catalog import Catalog
    from game_autoedit.data.labels import GameLabels
    from game_autoedit.datasets.dataset import DatasetSpec, PreparedGame
    from game_autoedit.datasets.splits import Split
    from game_autoedit.eval.decode import DecodeSpec


def _catalog_from_args(args: argparse.Namespace) -> Catalog:
    """Build the catalog described by the shared selection flags."""
    return build_catalog(
        quality=args.quality,
        tournaments=args.tournaments,
        game_ids=args.game_ids,
    )


def _print_coverage(catalog: Catalog) -> None:
    """Print how many games are usable, and per tournament."""
    usable = len(catalog.games)
    held_back = len(catalog.rejected)
    print(f"Games exploitables : {usable}  (écartés : {held_back})")
    print(f"Tournois couverts  : {len(catalog.tournaments())}")

    if catalog.rejected:
        print("\nMotifs d'exclusion :")
        for reason, count in sorted(
            catalog.rejection_counts().items(), key=lambda item: -item[1]
        ):
            print(f"  {count:4d}  {reason}")

    print("\nRépartition par tournoi :")
    grouped = catalog.by_tournament()
    for name in sorted(grouped, key=lambda key: -len(grouped[key])):
        types = sorted({game.cut_type for game in grouped[name]})
        print(f"  {len(grouped[name]):4d}  {name}  [{', '.join(types)}]")


def _describe(values: list[float], unit: str, digits: int = 1) -> str:
    """Return a one-line summary of a distribution."""
    if not values:
        return "aucune valeur"
    ordered = sorted(values)
    fmt = f".{digits}f"
    return (
        f"médiane {statistics.median(ordered):{fmt}}{unit}  "
        f"p10 {ordered[len(ordered) // 10]:{fmt}}{unit}  "
        f"p90 {ordered[9 * len(ordered) // 10]:{fmt}}{unit}  "
        f"min {ordered[0]:{fmt}}{unit}  max {ordered[-1]:{fmt}}{unit}"
    )


@dataclass
class _LabelStats:
    """Running totals over the label files of a catalog."""

    segment_durations: list[float] = field(default_factory=list)
    gap_durations: list[float] = field(default_factory=list)
    per_game_counts: list[float] = field(default_factory=list)
    kept_ratios: list[float] = field(default_factory=list)
    warned: list[tuple[int, list[str]]] = field(default_factory=list)
    empty: list[int] = field(default_factory=list)
    total_kept: float = 0.0
    total_span: float = 0.0
    unknown_duration: int = 0

    def add(self, game_id: int, labels: GameLabels, duration: float | None) -> None:
        """Fold one game's labels into the totals."""
        if duration is None:
            self.unknown_duration += 1
        if labels.warnings:
            self.warned.append((game_id, labels.warnings))
        if not labels.segments:
            self.empty.append(game_id)
            return

        self.segment_durations.extend(segment.duration for segment in labels.segments)
        self.gap_durations.extend(labels.gaps())
        self.per_game_counts.append(len(labels.segments))
        self.total_kept += labels.kept_seconds
        if duration:
            self.total_span += duration
            self.kept_ratios.append(labels.kept_seconds / duration)

    def report(self) -> None:
        """Print the distributions the totals describe."""
        print(f"\nDurée totale         : {self.total_span / 3600:.1f} h")
        print(f"Dont gardé (cuts)    : {self.total_kept / 3600:.1f} h")
        if self.kept_ratios:
            print(f"Ratio gardé par game : {_describe(self.kept_ratios, '', digits=3)}")
        print(f"Cuts par game        : {_describe(self.per_game_counts, '')}")
        print(f"Durée des cuts       : {_describe(self.segment_durations, 's')}")
        print(f"Temps mort entre cuts: {_describe(self.gap_durations, 's')}")
        print(f"Frontières totales   : {2 * len(self.segment_durations)} (in + out)")
        if self.unknown_duration:
            print(f"Durée média inconnue : {self.unknown_duration} game(s)")
        if self.empty:
            print(
                f"\nGames sans aucun cut : {len(self.empty)} -> inutilisables\n"
                f"  {', '.join(str(game_id) for game_id in self.empty)}"
            )


def _collect_label_stats(catalog: Catalog, paths: Paths) -> _LabelStats:
    """Read every cut file of the catalog and fold it into the totals."""
    stats = _LabelStats()
    for game in catalog.games:
        cached = audio_info(paths.audio_path(game.game_id))
        duration = cached.duration if cached else probe_duration(game.audio_source)
        labels = load_labels(
            game.cut_json_path,
            game_id=game.game_id,
            fps=game.fps,
            duration=duration,
        )
        stats.add(game.game_id, labels, duration)
    return stats


def inspect(args: argparse.Namespace, paths: Paths) -> int:
    """Report dataset coverage, label statistics and anomalies."""
    catalog = _catalog_from_args(args)
    _print_coverage(catalog)

    if args.rejected and catalog.rejected:
        print("\nGames écartés :")
        for rejection in catalog.rejected:
            print(
                f"  {rejection.game_id:5d}  {rejection.tournament[:32]:32s}  "
                f"{rejection.reason}"
            )

    if not catalog.games:
        return 0

    print("\nLecture des fichiers de cut…")
    stats = _collect_label_stats(catalog, paths)
    stats.report()

    print(f"\nGames avec anomalies : {len(stats.warned)}")
    if args.warnings:
        for game_id, warnings in stats.warned:
            print(f"\n  game {game_id}")
            for warning in warnings:
                print(f"    - {warning}")
    elif stats.warned:
        print("  (relancer avec --warnings pour le détail)")

    return 0


def build_cache(args: argparse.Namespace, paths: Paths) -> int:
    """Extract the audio of every selected game into the local cache."""
    catalog = _catalog_from_args(args)
    paths.ensure()
    total = len(catalog.games)
    print(f"{total} game(s) à traiter vers {paths.audio}")

    done = 0
    failed: list[tuple[int, str]] = []
    cached_seconds = 0.0
    for index, (game, cached, error) in enumerate(
        build_audio_cache(
            catalog.games,
            cache_dir=paths.audio,
            sample_rate=args.sample_rate,
            force=args.force,
        ),
        start=1,
    ):
        if error is not None:
            failed.append((game.game_id, error))
            print(f"[{index}/{total}] ÉCHEC game {game.game_id}: {error}")
            continue
        if cached is None:
            continue
        done += 1
        cached_seconds += cached.duration
        print(
            f"[{index}/{total}] game {game.game_id:5d}  "
            f"{cached.duration / 60:6.1f} min  {game.name[:40]}"
        )

    print(f"\n{done} game(s) en cache, {cached_seconds / 3600:.1f} h d'audio")
    if failed:
        print(f"{len(failed)} échec(s) :")
        for game_id, error in failed:
            print(f"  game {game_id}: {error}")
    return 1 if failed else 0


def cache_status(paths: Paths) -> int:
    """Report what the cache holds and how much room it takes."""
    if not paths.root.exists():
        print(f"Cache absent : {paths.root}")
        return 0

    print(f"Cache : {paths.root}")
    for directory in paths.all_dirs()[1:]:
        if not directory.exists():
            print(f"  {directory.name:12s}  absent")
            continue
        files = [path for path in directory.rglob("*") if path.is_file()]
        size = sum(path.stat().st_size for path in files)
        print(
            f"  {directory.name:12s}  {len(files):5d} fichier(s)  {size / 1e9:6.2f} Go"
        )
    return 0


def _split_from_args(args: argparse.Namespace, catalog: Catalog) -> Split:
    """Build the partition described by the split flags."""
    from game_autoedit.datasets.splits import SplitSpec, make_split

    spec = SplitSpec(
        val_fraction=args.val_fraction,
        test_fraction=args.test_fraction,
        seed=args.split_seed,
        group_by=args.group_by,
        holdout_tournaments=tuple(args.holdout_tournaments or ()),
    )
    return make_split(catalog.games, spec)


def _dataset_spec_from_args(args: argparse.Namespace) -> DatasetSpec:
    """Build the dataset spec described by the construction flags."""
    from game_autoedit.datasets.dataset import DatasetSpec
    from game_autoedit.datasets.targets import TargetSpec
    from game_autoedit.datasets.windows import SamplingSpec, WindowSpec

    return DatasetSpec(
        window=WindowSpec(duration=args.window),
        sampling=SamplingSpec(
            strategy=args.sampling,
            positive_ratio=args.positive_ratio,
            jitter=args.jitter,
            density=args.density,
        ),
        target=TargetSpec(
            hop=args.hop, tolerance=args.tolerance, shape=args.target_shape
        ),
    )


def _decode_spec_from_args(args: argparse.Namespace) -> DecodeSpec:
    """Build the decoding spec described by the threshold flags."""
    from game_autoedit.eval.decode import DecodeSpec

    return DecodeSpec(
        threshold={"in": args.threshold_in, "out": args.threshold_out},
        min_peak_distance=args.min_peak_distance,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        inside_veto=args.inside_veto,
    )


def _report_skipped(skipped: list[tuple[int, str]], label: str) -> None:
    """Print why some games could not be used."""
    if not skipped:
        return
    reasons: dict[str, int] = {}
    for _, reason in skipped:
        reasons[reason] = reasons.get(reason, 0) + 1
    detail = ", ".join(f"{count} {reason}" for reason, count in reasons.items())
    print(f"  {label} : {len(skipped)} game(s) écarté(s) ({detail})")


def splits(args: argparse.Namespace, paths: Paths) -> int:
    """Print the partition the other commands would use."""
    catalog = _catalog_from_args(args)
    split = _split_from_args(args, catalog)
    print(split.summary())
    for part in ("train", "val", "test"):
        games = getattr(split, part)
        print(f"\n{part} ({len(games)} games)")
        for tournament in split.tournaments(part):
            count = sum(1 for game in games if game.tournament == tournament)
            print(f"  {count:4d}  {tournament}")

    prepared, skipped = prepare_games(catalog.games, paths)
    print(f"\nAudio en cache : {len(prepared)}/{len(catalog.games)}")
    _report_skipped(skipped, "cache")
    return 0


def train(args: argparse.Namespace, paths: Paths) -> int:
    """Train a model and store it under the cache's run directory."""
    from game_autoedit.models.tcn import ModelSpec
    from game_autoedit.runs import resolve_device
    from game_autoedit.training import RunSpec, TrainSpec
    from game_autoedit.training import train as run_training

    catalog = _catalog_from_args(args)
    split = _split_from_args(args, catalog)
    print(split.summary())

    train_games, skipped_train = prepare_games(split.train, paths)
    val_games, skipped_val = prepare_games(split.val, paths)
    _report_skipped(skipped_train, "train")
    _report_skipped(skipped_val, "val")

    if args.limit_games:
        train_games = train_games[: args.limit_games]
        val_games = val_games[: max(args.limit_games // 4, 1)]

    if not train_games:
        print("Aucun game entraînable : lancer d'abord `build-cache`.")
        return 1
    if not val_games:
        print("Aucun game de validation en cache : élargir le cache ou --val-fraction.")
        return 1

    run = RunSpec(
        name=args.name,
        dataset=_dataset_spec_from_args(args),
        model=ModelSpec(),
        train=TrainSpec(
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            num_workers=args.num_workers,
            loss=args.loss,
            seed=args.seed,
        ),
    )
    device = resolve_device(args.device)
    output_dir = paths.runs / args.name
    print(f"Entraînement sur {device}, sortie dans {output_dir}")

    result = run_training(
        run,
        train_games=train_games,
        val_games=val_games,
        output_dir=output_dir,
        device=device,
    )
    print(f"\nMeilleur score de sélection (AP frontières) : {result['best_score']:.4f}")
    return 0


def _predict_curves(
    model: object,
    prepared: PreparedGame,
    spec: DatasetSpec,
    device: object,
) -> tuple[np.ndarray, np.ndarray]:
    """Run the model over one full game."""
    from game_autoedit.eval.inference import predict_game

    return predict_game(
        model,  # type: ignore[arg-type]
        prepared.audio_path,
        duration=prepared.duration,
        spec=spec,
        device=device,  # type: ignore[arg-type]
        batch_size=8,
    )


def evaluate(args: argparse.Namespace, paths: Paths) -> int:
    """Decode whole games and score them against the human edit."""
    from game_autoedit.eval.decode import decode
    from game_autoedit.eval.metrics import (
        Aggregate,
        match_boundaries,
        score_segments,
    )
    from game_autoedit.runs import RunNotFoundError, load_run, resolve_device

    device = resolve_device(args.device)
    try:
        model, spec, _ = load_run(paths.runs / args.run, device)
    except RunNotFoundError as error:
        print(error)
        return 1

    catalog = _catalog_from_args(args)
    split = _split_from_args(args, catalog)
    games, skipped = prepare_games(getattr(split, args.part), paths)
    _report_skipped(skipped, args.part)
    if not games:
        print(f"Aucun game exploitable dans la partition {args.part}.")
        return 1

    decode_spec = _decode_spec_from_args(args)
    aggregate = Aggregate.empty(("in", "out"))
    print(f"Évaluation de {len(games)} game(s) sur {device}\n")

    for prepared in games:
        probabilities, times = _predict_curves(model, prepared, spec, device)
        decoded = decode(probabilities, times, decode_spec)

        for channel, predicted, expected in (
            ("in", [s.start for s in decoded.segments], prepared.labels.ins),
            ("out", [s.end for s in decoded.segments], prepared.labels.outs),
        ):
            score = match_boundaries(
                predicted, expected, channel=channel, tolerance=args.tolerance
            )
            aggregate.add_boundaries(score)

        segment_score = score_segments(
            decoded.segments,
            prepared.labels.segments,
            duration=prepared.duration,
        )
        aggregate.add_segments(segment_score)

        if args.per_game:
            print(f"game {prepared.game.game_id:5d}  {segment_score.line()}")

    print(f"\nGlobal sur {aggregate.games} game(s), tolérance ±{args.tolerance}s")
    for channel in ("in", "out"):
        print("  " + aggregate.boundary_score(channel).line())
    print(f"  IoU temporel   : {aggregate.iou:.3f}")
    print(
        f"  Coût de revue  : {aggregate.missed_points} point(s) manqué(s), "
        f"{aggregate.extra_segments} segment(s) en trop "
        f"({aggregate.missed_points / max(aggregate.games, 1):.1f} et "
        f"{aggregate.extra_segments / max(aggregate.games, 1):.1f} par game)"
    )
    return 0


def predict(args: argparse.Namespace, paths: Paths) -> int:
    """Generate a cut file, its probability curves and its commentary."""
    import json

    from game_autoedit.eval.decode import decode
    from game_autoedit.eval.report import build_comment
    from game_autoedit.runs import RunNotFoundError, load_run, resolve_device

    device = resolve_device(args.device)
    try:
        model, spec, run_payload = load_run(paths.runs / args.run, device)
    except RunNotFoundError as error:
        print(error)
        return 1

    catalog = _catalog_from_args(args)
    games, skipped = prepare_games(catalog.games, paths)
    _report_skipped(skipped, "prédiction")
    if not games:
        print("Aucun game exploitable.")
        return 1

    out_dir = Path(args.out) if args.out else paths.predictions
    out_dir.mkdir(parents=True, exist_ok=True)
    decode_spec = _decode_spec_from_args(args)

    for prepared in games:
        probabilities, times = _predict_curves(model, prepared, spec, device)
        decoded = decode(probabilities, times, decode_spec)

        game_id = prepared.game.game_id
        fps = prepared.game.fps
        payload: dict[str, Any] = {
            "points": [
                {
                    "in": int(round(segment.start * fps)),
                    "out": int(round(segment.end * fps)),
                    "point": "nopoint",
                }
                for segment in decoded.segments
            ],
            "overlays": [],
            "comment": build_comment(
                decoded,
                duration=prepared.duration,
                fps=fps,
                decode_spec=decode_spec,
                model_info={"run": args.run, "epoch": run_payload.get("epoch")},
            ),
        }

        curves_path = out_dir / f"game_{game_id}_curves.npz"
        curves: dict[str, Any] = {
            name: probabilities[:, index] for index, name in enumerate(CHANNELS)
        }
        curves["times"] = times.astype(np.float32)
        np.savez_compressed(curves_path, **curves)
        payload["comment"]["curves_file"] = curves_path.name
        payload["comment"]["curves_hop"] = spec.target.hop
        if args.embed_curves:
            payload["curves"] = {
                "hop": spec.target.hop,
                **{
                    name: [round(float(v), 4) for v in probabilities[:, index]]
                    for index, name in enumerate(CHANNELS)
                },
            }

        cut_path = out_dir / f"game_{game_id}_cut.json"
        cut_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

        review = len(payload["comment"]["review"])
        print(
            f"game {game_id:5d}  {len(decoded.segments):3d} segments  "
            f"{payload['comment']['stats']['kept'] / 60:6.1f} min gardées  "
            f"{review} point(s) à vérifier  -> {cut_path.name}"
        )

    return 0
