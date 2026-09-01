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
    from collections.abc import Callable, Sequence

    from game_autoedit.config import Paths
    from game_autoedit.data.catalog import Catalog
    from game_autoedit.data.labels import GameLabels, Segment
    from game_autoedit.datasets.dataset import DatasetSpec
    from game_autoedit.datasets.splits import Split
    from game_autoedit.eval.decode import Decoded, DecodeSpec
    from game_autoedit.training import TrainSpec


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


def build_embeddings(args: argparse.Namespace, paths: Paths) -> int:
    """Encode every selected game once with a frozen pretrained encoder."""
    import soundfile as sf

    from game_autoedit.data.embeddings import EmbeddingStore
    from game_autoedit.encoders import EncoderSpec, build_encoder
    from game_autoedit.runs import resolve_device

    catalog = _catalog_from_args(args)
    prepared, skipped = prepare_games(catalog.games, paths)
    _report_skipped(skipped, "audio")
    if not prepared:
        print("Aucun audio en cache : lancer d'abord `build-cache`.")
        return 1

    device = resolve_device(args.device)
    spec = EncoderSpec(
        name=args.encoder, batch_size=args.batch_size, stereo=not args.mono
    )
    print(f"Chargement de l'encodeur {spec.name} sur {device}…")
    encoder = build_encoder(spec, device)

    root = paths.embeddings(spec.cache_key)
    store = EmbeddingStore.create(
        root, rate=encoder.rate, dim=encoder.dim, encoder=spec.name
    )
    print(
        f"{len(prepared)} game(s) -> {root}\n"
        f"grille {store.rate:.3f} Hz, {store.dim} dimensions"
        + (" (mid + side)" if spec.stereo else " (mono)")
        + "\n"
    )

    done, encoded_seconds = 0, 0.0
    for index, item in enumerate(prepared, start=1):
        if store.has(item.game.game_id) and not args.force:
            done += 1
            continue
        waveform, _ = sf.read(
            str(item.audio_path), dtype="float32", always_2d=spec.stereo
        )
        embeddings = encoder.encode(waveform)
        store.write(item.game.game_id, embeddings)
        done += 1
        encoded_seconds += item.duration
        print(
            f"[{index}/{len(prepared)}] game {item.game.game_id:5d}  "
            f"{embeddings.shape[0]:6d} pas  {item.duration / 60:6.1f} min"
        )

    size = sum(path.stat().st_size for path in root.glob("*.npy"))
    print(
        f"\n{done} game(s) encodés ({encoded_seconds / 3600:.1f} h cette fois), "
        f"{size / 1e9:.2f} Go"
    )
    return 0


def build_beats(args: argparse.Namespace, paths: Paths) -> int:
    """Compute and cache the onset envelope of every selected game."""
    import soundfile as sf

    from game_autoedit.data.beats import (
        DRUM_PERIOD,
        DRUM_TOLERANCE,
        ENVELOPE_RATE,
        estimate_grid,
        load_envelope,
        onset_envelope,
        save_envelope,
    )

    catalog = _catalog_from_args(args)
    prepared, skipped = prepare_games(catalog.games, paths)
    _report_skipped(skipped, "audio")
    if not prepared:
        print("Aucun audio en cache : lancer d'abord `build-cache`.")
        return 1

    root = paths.beats
    root.mkdir(parents=True, exist_ok=True)
    print(f"{len(prepared)} game(s) -> {root}\n")

    periods: list[float] = []
    for index, item in enumerate(prepared, start=1):
        game_id = item.game.game_id
        envelope = None if args.force else load_envelope(root, game_id)
        if envelope is None:
            waveform, rate = sf.read(
                str(item.audio_path), dtype="float32", always_2d=False
            )
            if waveform.ndim > 1:
                waveform = waveform.mean(axis=1)
            envelope = onset_envelope(waveform, rate)
            save_envelope(root, game_id, envelope)

        grid = estimate_grid(envelope, centre=item.duration / 2, span=30.0)
        if grid is not None:
            periods.append(grid.period)
            print(
                f"[{index}/{len(prepared)}] game {game_id:5d}  "
                f"{len(envelope) / ENVELOPE_RATE / 60:5.1f} min  "
                f"tambour {grid.period:.2f}s (force {grid.strength:.2f})"
            )
        else:
            print(f"[{index}/{len(prepared)}] game {game_id:5d}  aucune grille")

    if periods:
        ordered = sorted(periods)
        near = sum(1 for p in periods if abs(p - DRUM_PERIOD) < DRUM_TOLERANCE)
        print(
            f"\nPériode médiane {ordered[len(ordered) // 2]:.2f}s — "
            f"{near}/{len(periods)} games à {DRUM_PERIOD}s "
            f"± {DRUM_TOLERANCE}"
        )
    size = sum(path.stat().st_size for path in root.glob("*.npy"))
    print(f"{len(prepared)} enveloppe(s), {size / 1e6:.0f} Mo")
    return 0


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
        snap_fraction=args.snap_fraction,
        threshold={"in": args.threshold_in, "out": args.threshold_out},
        min_peak_distance=args.min_peak_distance,
        min_gap=args.min_gap,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        inside_veto=args.inside_veto,
        inside_weight=args.inside_weight,
        inside_smoothing=args.inside_smoothing,
    )


def _snapped(
    decoded: Decoded, game_id: int, paths: Paths, spec: DecodeSpec, *, enabled: bool
) -> list[Segment]:
    """Place the decoded boundaries on the drum grid, when asked and possible."""
    if not enabled:
        return decoded.segments

    from game_autoedit.data.beats import load_envelope
    from game_autoedit.eval.snap import snap_segments

    envelope = load_envelope(paths.beats, game_id)
    if envelope is None:
        return decoded.segments
    segments, _ = snap_segments(decoded.segments, envelope, spec)
    return segments


def _add_intervals(
    totals: dict[str, tuple[list[int], int]],
    segments: list[Segment],
    prepared: Any,
    paths: Paths,
) -> None:
    """Fold one game's beat-interval score into the running totals.

    Silently does nothing when the game has no cached onset envelope: the
    interval score is a bonus reading, not a reason to fail an evaluation.
    """
    from game_autoedit.data.beats import load_envelope
    from game_autoedit.eval.metrics import score_intervals

    envelope = load_envelope(paths.beats, prepared.game.game_id)
    if envelope is None:
        return

    for channel, predicted, expected in (
        ("in", [segment.start for segment in segments], prepared.labels.ins),
        ("out", [segment.end for segment in segments], prepared.labels.outs),
    ):
        score = score_intervals(predicted, expected, envelope, channel=channel)
        deltas, unmatched = totals[channel]
        totals[channel] = (deltas + score.deltas, unmatched + score.unmatched)


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


def _train_spec(args: argparse.Namespace) -> TrainSpec:
    """Build the optimisation settings from the CLI flags."""
    from game_autoedit.training import TrainSpec

    return TrainSpec(
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        num_workers=args.num_workers,
        loss=args.loss,
        seed=args.seed,
        patience=args.patience,
    )


def _train_on_embeddings(args: argparse.Namespace, paths: Paths, split: Split) -> int:
    """Train a small head on top of a frozen encoder's cached embeddings."""
    from game_autoedit.data.embeddings import EmbeddingStore
    from game_autoedit.datasets.embedding_dataset import (
        EmbeddingDatasetSpec,
        EmbeddingWindowDataset,
        prepare_embedding_games,
    )
    from game_autoedit.datasets.windows import SamplingSpec, WindowSpec
    from game_autoedit.models.head import EmbeddingTagger, HeadSpec
    from game_autoedit.runs import resolve_device
    from game_autoedit.training import RunSpec, TrainingInputs
    from game_autoedit.training import train as run_training

    store = EmbeddingStore.open(paths.embeddings(args.encoder))
    if store is None:
        print(
            f"Aucun cache de plongements pour '{args.encoder}' : "
            f"lancer `build-embeddings --encoder {args.encoder}`."
        )
        return 1

    train_games, skipped_train = prepare_embedding_games(split.train, store)
    val_games, skipped_val = prepare_embedding_games(split.val, store)
    _report_skipped(skipped_train, "train")
    _report_skipped(skipped_val, "val")
    if args.limit_games:
        train_games = train_games[: args.limit_games]
        val_games = val_games[: max(args.limit_games // 4, 1)]
    if not train_games or not val_games:
        print("Pas assez de games encodés pour entraîner.")
        return 1

    spec = EmbeddingDatasetSpec.for_store(
        store,
        window=WindowSpec(duration=args.window),
        sampling=SamplingSpec(
            strategy=args.sampling,
            positive_ratio=args.positive_ratio,
            jitter=args.jitter,
            density=args.density,
        ),
        tolerance=args.tolerance,
        shape=args.target_shape,
    )
    head = HeadSpec(channels=args.head_channels, dropout=args.dropout)
    run = RunSpec(
        name=args.name,
        dataset=spec,
        model=head,
        train=_train_spec(args),
        encoder=args.encoder,
    )
    device = resolve_device(args.device)
    output_dir = paths.runs / args.name
    print(
        f"Tête sur plongements {store.encoder} "
        f"({store.rate:.2f} Hz, {store.dim} dim), champ réceptif "
        f"{head.receptive_field() / store.rate:.0f}s"
    )
    print(f"Entraînement sur {device}, sortie dans {output_dir}")

    result = run_training(
        run,
        TrainingInputs(
            train_set=EmbeddingWindowDataset(train_games, store, spec, seed=args.seed),
            val_set=EmbeddingWindowDataset(val_games, store, spec, seed=args.seed + 1),
            model=EmbeddingTagger(store.dim, head),
            input_key="embeddings",
        ),
        output_dir=output_dir,
        device=device,
    )
    print(f"\nMeilleur score de sélection (AP frontières) : {result['best_score']:.4f}")
    return 0


def _train_on_waveform(args: argparse.Namespace, paths: Paths, split: Split) -> int:
    """Train the end-to-end model directly on the cached audio."""
    from game_autoedit.datasets.dataset import GameWindowDataset
    from game_autoedit.models.tcn import ModelSpec, build_model
    from game_autoedit.runs import resolve_device
    from game_autoedit.training import RunSpec, TrainingInputs
    from game_autoedit.training import train as run_training

    train_games, skipped_train = prepare_games(split.train, paths)
    val_games, skipped_val = prepare_games(split.val, paths)
    _report_skipped(skipped_train, "train")
    _report_skipped(skipped_val, "val")
    if args.limit_games:
        train_games = train_games[: args.limit_games]
        val_games = val_games[: max(args.limit_games // 4, 1)]
    if not train_games or not val_games:
        print("Aucun game entraînable : lancer d'abord `build-cache`.")
        return 1

    spec = _dataset_spec_from_args(args)
    model_spec = ModelSpec()
    run = RunSpec(
        name=args.name, dataset=spec, model=model_spec, train=_train_spec(args)
    )
    device = resolve_device(args.device)
    output_dir = paths.runs / args.name
    print(f"Entraînement sur {device}, sortie dans {output_dir}")

    result = run_training(
        run,
        TrainingInputs(
            train_set=GameWindowDataset(train_games, spec, seed=args.seed),
            val_set=GameWindowDataset(val_games, spec, seed=args.seed + 1),
            model=build_model(model_spec),
            input_key="waveform",
            steps=spec.steps_per_window(),
        ),
        output_dir=output_dir,
        device=device,
    )
    print(f"\nMeilleur score de sélection (AP frontières) : {result['best_score']:.4f}")
    return 0


def train(args: argparse.Namespace, paths: Paths) -> int:
    """Train either the end-to-end model or a head over frozen embeddings."""
    catalog = _catalog_from_args(args)
    split = _split_from_args(args, catalog)
    print(split.summary())

    if args.encoder:
        return _train_on_embeddings(args, paths, split)
    return _train_on_waveform(args, paths, split)


@dataclass
class _Predictor:
    """A loaded run bound to the games it can predict.

    Hides which of the two paths produced the run: callers ask for a game's
    curves and get them, whether they come from a single pass over cached
    embeddings or from sliding windows over the audio.
    """

    games: list[Any]
    predict: Callable[[Any], tuple[np.ndarray, np.ndarray]]


def _make_predictor(
    args: argparse.Namespace, paths: Paths, games: Sequence[Any], device: Any
) -> _Predictor | None:
    """Load the run named by `args` and bind it to the games it can read."""
    from game_autoedit.data.embeddings import EmbeddingStore
    from game_autoedit.datasets.embedding_dataset import prepare_embedding_games
    from game_autoedit.eval.inference import predict_game
    from game_autoedit.eval.whole_game import predict_whole_game
    from game_autoedit.runs import RunNotFoundError, load_run

    try:
        run = load_run(paths.runs / args.run, device)
    except RunNotFoundError as error:
        print(error)
        return None

    if run.on_embeddings:
        encoder = str(args.encoder or run.encoder)
        store = EmbeddingStore.open(paths.embeddings(encoder))
        if store is None:
            print(f"Aucun cache de plongements pour '{encoder}'.")
            return None
        prepared, skipped = prepare_embedding_games(games, store)
        _report_skipped(skipped, "plongements")

        def predict(item: Any) -> tuple[np.ndarray, np.ndarray]:
            return predict_whole_game(
                run.model,
                store,
                item.game.game_id,
                device,
                receptive_field=run.receptive_field,
            )

        return _Predictor(games=prepared, predict=predict)

    prepared_audio, skipped_audio = prepare_games(games, paths)
    _report_skipped(skipped_audio, "audio")
    spec = run.dataset
    if spec is None:
        print("Run illisible : ni encodeur ni spécification de dataset.")
        return None

    def predict_audio(item: Any) -> tuple[np.ndarray, np.ndarray]:
        return predict_game(
            run.model,
            item.audio_path,
            duration=item.duration,
            spec=spec,
            device=device,
            batch_size=8,
        )

    return _Predictor(games=prepared_audio, predict=predict_audio)


def evaluate(args: argparse.Namespace, paths: Paths) -> int:
    """Decode whole games and score them against the human edit."""
    from game_autoedit.eval.decode import decode
    from game_autoedit.eval.metrics import (
        Aggregate,
        IntervalScore,
        match_boundaries,
        score_segments,
    )
    from game_autoedit.runs import resolve_device

    device = resolve_device(args.device)
    catalog = _catalog_from_args(args)
    split = _split_from_args(args, catalog)
    predictor = _make_predictor(args, paths, getattr(split, args.part), device)
    if predictor is None:
        return 1
    games = predictor.games
    if not games:
        print(f"Aucun game exploitable dans la partition {args.part}.")
        return 1

    decode_spec = _decode_spec_from_args(args)
    aggregate = Aggregate.empty(("in", "out"))
    intervals: dict[str, tuple[list[int], int]] = {"in": ([], 0), "out": ([], 0)}
    print(f"Évaluation de {len(games)} game(s) sur {device}\n")

    for prepared in games:
        probabilities, times = predictor.predict(prepared)
        decoded = decode(probabilities, times, decode_spec)
        segments = _snapped(
            decoded, prepared.game.game_id, paths, decode_spec, enabled=args.snap
        )

        for channel, predicted, expected in (
            ("in", [s.start for s in segments], prepared.labels.ins),
            ("out", [s.end for s in segments], prepared.labels.outs),
        ):
            score = match_boundaries(
                predicted, expected, channel=channel, tolerance=args.tolerance
            )
            aggregate.add_boundaries(score)

        _add_intervals(intervals, segments, prepared, paths)

        segment_score = score_segments(
            segments,
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

    if any(deltas for deltas, _ in intervals.values()):
        print("\n  Bon intervalle de tambour (la question qui compte) :")
        for channel in ("in", "out"):
            deltas, unmatched = intervals[channel]
            print("    " + IntervalScore(channel, deltas, unmatched).line())

    games_count = max(aggregate.games, 1)
    print("  Coût de revue, par game :")
    for label, total in (
        ("points manqués (à retrouver à la main)", aggregate.missed_points),
        ("segments en trop (un clic pour supprimer)", aggregate.extra_segments),
        ("segments fusionnés (recouvrent plusieurs points)", aggregate.merged_segments),
        ("points coupés en deux", aggregate.split_points),
    ):
        print(f"    {total / games_count:5.1f}  {label}  (total {total})")
    return 0


def predict(args: argparse.Namespace, paths: Paths) -> int:
    """Generate a cut file, its probability curves and its commentary."""
    import json

    from game_autoedit.eval.decode import decode
    from game_autoedit.eval.report import build_comment
    from game_autoedit.runs import resolve_device

    device = resolve_device(args.device)
    catalog = _catalog_from_args(args)
    predictor = _make_predictor(args, paths, catalog.games, device)
    if predictor is None:
        return 1
    games = predictor.games
    if not games:
        print("Aucun game exploitable.")
        return 1

    out_dir = Path(args.out) if args.out else paths.predictions
    out_dir.mkdir(parents=True, exist_ok=True)
    decode_spec = _decode_spec_from_args(args)

    for prepared in games:
        probabilities, times = predictor.predict(prepared)
        decoded = decode(probabilities, times, decode_spec)
        game_id = prepared.game.game_id
        segments = _snapped(decoded, game_id, paths, decode_spec, enabled=args.snap)
        decoded.segments = segments

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
                model_info={"run": args.run},
            ),
        }

        curves_path = out_dir / f"game_{game_id}_curves.npz"
        curves: dict[str, Any] = {
            name: probabilities[:, index] for index, name in enumerate(CHANNELS)
        }
        curves["times"] = times.astype(np.float32)
        np.savez_compressed(curves_path, **curves)
        payload["comment"]["curves_file"] = curves_path.name
        payload["comment"]["curves_hop"] = (
            float(times[1] - times[0]) if len(times) > 1 else 0.0
        )
        if args.embed_curves:
            payload["curves"] = {
                "hop": payload["comment"]["curves_hop"],
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
