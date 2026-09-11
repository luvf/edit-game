"""The one entry point the web application calls.

Everything else in `game_autoedit` is a laboratory: commands that print, a
dashboard, runs that get compared. This module is the opposite — a single
function that takes a game and gives back a cut proposal, so `core` never has
to know how any of it works, and so the day the pipeline changes shape the app
does not move.

It is called in a subprocess by the render queue, never in the web process:
loading a checkpoint pulls torch and, on a GPU box, holds VRAM for as long as
the process lives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from game_autoedit.config import AUDIO_QUALITY, SAMPLE_RATE, Paths
from game_autoedit.data.audio import build_audio_cache
from game_autoedit.data.catalog import UnusableGameError, predictable_game
from game_autoedit.datasets.targets import CHANNELS

if TYPE_CHECKING:
    from pathlib import Path

    from game_autoedit.data.catalog import LabeledGame
    from game_autoedit.eval.decode import DecodeSpec


@dataclass(frozen=True)
class ProposalOptions:
    """How to run the model, as opposed to what to run it on.

    Attributes:
        decode_spec: thresholds and rules turning curves into segments. The
            measured defaults when left out.
        device: cuda, cpu… ; the best available when left out.
        quality: which VideoFile quality to read audio from. The archive is
            the only rendition with a consistent audio profile, which is what
            the model was trained on.
        snap: place the starts on the drum grid.
    """

    decode_spec: DecodeSpec | None = None
    device: str | None = None
    quality: str = AUDIO_QUALITY
    snap: bool = True


@dataclass(frozen=True)
class Proposal:
    """What a run produced for one game."""

    game_id: int
    run: str
    cut_path: Path
    curves_path: Path
    segments: int
    kept_seconds: float
    review: int

    def summary(self) -> str:
        """Return a one-line report, for a queue item to store as metadata."""
        return (
            f"game {self.game_id} — {self.segments} segments, "
            f"{self.kept_seconds / 60:.1f} min gardées, "
            f"{self.review} point(s) à vérifier ({self.run})"
        )


def _ensure_audio(game: LabeledGame, paths: Paths) -> float:
    """Extract this game's audio into the cache if it is not there yet.

    Returns:
        The track duration in seconds.

    Raises:
        UnusableGameError: the archive could not be read.
    """
    paths.ensure()
    for _game, cached, error in build_audio_cache(
        [game], cache_dir=paths.audio, sample_rate=SAMPLE_RATE
    ):
        if error is not None:
            raise UnusableGameError(f"extraction audio impossible : {error}")
        if cached is not None:
            return cached.duration
    raise UnusableGameError("extraction audio impossible : aucune sortie")


def _ensure_embeddings(game_id: int, paths: Paths, encoder: str, device: Any) -> Any:
    """Return the embedding store for `encoder`, encoding this game if needed.

    The encoder itself is only built when something is missing: loading AST
    costs seconds and a slab of VRAM, and a game proposed twice pays it once.

    Raises:
        UnusableGameError: the cache does not exist and cannot be created.
    """
    import soundfile as sf

    from game_autoedit.data.embeddings import EmbeddingStore
    from game_autoedit.encoders import EncoderSpec, build_encoder

    # The cache key carries the mid/side suffix; the encoder name does not.
    spec = EncoderSpec(name=encoder.removesuffix("_ms"), stereo=encoder.endswith("_ms"))
    root = paths.embeddings(encoder)
    store = EmbeddingStore.open(root)
    if store is not None and store.has(game_id):
        return store

    built = build_encoder(spec, device)
    if store is None:
        store = EmbeddingStore.create(
            root, rate=built.rate, dim=built.dim, encoder=spec.name
        )
    waveform, _ = sf.read(
        str(paths.audio_path(game_id)), dtype="float32", always_2d=spec.stereo
    )
    store.write(game_id, built.encode(waveform))
    return store


def _ensure_envelope(game_id: int, paths: Paths) -> np.ndarray | None:
    """Return this game's onset envelope, computing it if it is not cached."""
    import soundfile as sf

    from game_autoedit.data.beats import load_envelope, onset_envelope, save_envelope

    envelope = load_envelope(paths.beats, game_id)
    if envelope is not None:
        return envelope

    audio_path = paths.audio_path(game_id)
    if not audio_path.exists():
        return None
    waveform, rate = sf.read(str(audio_path), dtype="float32", always_2d=False)
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)
    envelope = onset_envelope(waveform, rate)
    paths.beats.mkdir(parents=True, exist_ok=True)
    save_envelope(paths.beats, game_id, envelope)
    return envelope


def _predict(
    game: LabeledGame, duration: float, run_name: str, paths: Paths, device: Any
) -> tuple[np.ndarray, np.ndarray]:
    """Run the model over the whole game.

    Returns:
        ``(steps, 3)`` probabilities and the ``(steps,)`` centre times.

    Raises:
        UnusableGameError: the run cannot be loaded or read.
    """
    from game_autoedit.eval.inference import predict_game
    from game_autoedit.eval.whole_game import predict_whole_game
    from game_autoedit.runs import RunNotFoundError, load_run

    try:
        run = load_run(paths.runs / run_name, device)
    except RunNotFoundError as error:
        raise UnusableGameError(str(error)) from error

    if run.on_embeddings:
        encoder = str(run.encoder)
        store = _ensure_embeddings(game.game_id, paths, encoder, device)
        return predict_whole_game(
            run.model,
            store,
            game.game_id,
            device,
            receptive_field=run.receptive_field,
        )

    if run.dataset is None:
        raise UnusableGameError(
            f"run '{run_name}' illisible : ni encodeur ni spécification de dataset"
        )
    return predict_game(
        run.model,
        paths.audio_path(game.game_id),
        duration=duration,
        spec=run.dataset,
        device=device,
        batch_size=8,
    )


def _cut_payload(
    decoded: Any,
    *,
    duration: float,
    fps: float,
    spec: DecodeSpec,
    model_info: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the cut file a decoding produced.

    Shared by the first proposal and every re-decoding after it, so a cut
    tuned six months later carries exactly the same shape as a fresh one.
    """
    from game_autoedit.eval.report import build_comment

    return {
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
            duration=duration,
            fps=fps,
            decode_spec=spec,
            model_info=model_info,
        ),
    }


def read_curves(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read a curves file back into the array the decoder expects.

    Returns:
        ``(steps, 3)`` probabilities in channel order, and the centre times.

    Raises:
        UnusableGameError: the file is unreadable or carries no channel.
    """
    try:
        with np.load(path) as archive:
            stored = {name: archive[name] for name in archive.files}
    except (OSError, ValueError, EOFError) as error:
        raise UnusableGameError(f"courbes illisibles : {error}") from error

    missing = [name for name in CHANNELS if name not in stored]
    if missing:
        raise UnusableGameError(f"canaux absents des courbes : {', '.join(missing)}")

    probabilities = np.stack(
        [np.asarray(stored[name], dtype=np.float32) for name in CHANNELS], axis=1
    )
    times = np.asarray(
        stored.get("times", np.arange(probabilities.shape[0], dtype=np.float32)),
        dtype=np.float64,
    )
    return probabilities, times


@dataclass(frozen=True)
class Decoding:
    """A cut re-derived from stored curves, and whether it could be snapped."""

    payload: dict[str, Any]
    segments: int
    snapped: bool


def redecode(
    curves_path: Path,
    *,
    fps: float,
    game_id: int,
    decode_spec: DecodeSpec | None = None,
    paths: Paths | None = None,
    snap: bool = True,
    model_info: dict[str, Any] | None = None,
) -> Decoding:
    """Turn stored curves into a cut again, with other thresholds.

    This is the cheap half of the pipeline: no model, no GPU, no audio — a
    pass of numpy over a file that is already on disk. Turning a threshold is
    therefore something a person can do while watching the result, which is
    the whole reason decoding was kept out of the model.

    Snapping is the one part that needs more than the curves: the onset
    envelope lives in the disposable cache, and when it has been wiped the
    boundaries are returned unsnapped rather than recomputed here — rebuilding
    it means decoding the archive, which belongs in a queue job. The result
    says which of the two happened.

    Args:
        curves_path: the ``.npz`` attached to the cut.
        fps: the frame rate the cut's points are expressed in.
        game_id: whose onset envelope to look for.
        decode_spec: the thresholds to apply; the measured defaults otherwise.
        paths: the cache to read the envelope from.
        snap: place the starts on the drum grid, when the envelope is there.
        model_info: provenance to carry into the comment.

    Returns:
        The cut payload, and whether the boundaries were snapped.

    Raises:
        UnusableGameError: the curves cannot be read.
    """
    from game_autoedit.data.beats import load_envelope
    from game_autoedit.eval.decode import DecodeSpec, decode
    from game_autoedit.eval.snap import snap_segments

    paths = paths or Paths()
    spec = decode_spec or DecodeSpec()
    probabilities, times = read_curves(curves_path)

    decoded = decode(probabilities, times, spec)
    snapped = False
    if snap:
        envelope = load_envelope(paths.beats, game_id)
        if envelope is not None:
            decoded.segments, _ = snap_segments(decoded.segments, envelope, spec)
            snapped = True

    hop = float(times[1] - times[0]) if len(times) > 1 else 0.0
    duration = float(times[-1]) + hop / 2 if times.size else 0.0
    payload = _cut_payload(
        decoded,
        duration=duration,
        fps=fps,
        spec=spec,
        model_info={**(model_info or {}), "redecoded": True, "snapped": snapped},
    )
    payload["comment"]["curves_file"] = curves_path.name
    payload["comment"]["curves_hop"] = hop
    return Decoding(payload=payload, segments=len(decoded.segments), snapped=snapped)


def generate_cut(
    game_id: int,
    *,
    run: str,
    out_dir: Path,
    cut_id: int | None = None,
    paths: Paths | None = None,
    options: ProposalOptions | None = None,
) -> Proposal:
    """Propose a cut for one game, and write it next to its curves.

    Everything the model needs is built on demand: a game that has never been
    seen costs its audio extraction and one encoder pass, a game already in
    the cache costs neither.

    Args:
        game_id: the game to propose a cut for.
        run: name of the training run to use.
        out_dir: where the cut file and the curves are written.
        cut_id: the cut the proposal belongs to, recorded in the comment.
        paths: the cache to read and write; the default cache otherwise.
        options: how to run the model; the measured defaults otherwise.

    Returns:
        What was produced, and where.

    Raises:
        UnusableGameError: the game carries no readable audio, or the run
            cannot be read.
    """
    from game_autoedit.eval.decode import DecodeSpec, decode
    from game_autoedit.eval.snap import snap_segments
    from game_autoedit.runs import resolve_device

    paths = paths or Paths()
    options = options or ProposalOptions()
    spec = options.decode_spec or DecodeSpec()
    game = predictable_game(game_id, cut_id=cut_id, quality=options.quality)

    duration = _ensure_audio(game, paths)
    device = resolve_device(options.device)
    probabilities, times = _predict(game, duration, run, paths, device)

    decoded = decode(probabilities, times, spec)
    if options.snap:
        envelope = _ensure_envelope(game_id, paths)
        if envelope is not None:
            decoded.segments, _ = snap_segments(decoded.segments, envelope, spec)

    fps = game.fps
    payload = _cut_payload(
        decoded,
        duration=duration,
        fps=fps,
        spec=spec,
        model_info={"run": run, "cut_id": cut_id, "quality": game.quality},
    )
    comment = payload["comment"]

    out_dir.mkdir(parents=True, exist_ok=True)
    curves_path = out_dir / f"game_{game_id}_curves.npz"
    curves: dict[str, Any] = {
        name: probabilities[:, index].astype(np.float32)
        for index, name in enumerate(CHANNELS)
    }
    curves["times"] = times.astype(np.float32)
    np.savez_compressed(curves_path, **curves)
    comment["curves_file"] = curves_path.name
    comment["curves_hop"] = float(times[1] - times[0]) if len(times) > 1 else 0.0

    cut_path = out_dir / f"game_{game_id}_cut.json"
    cut_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    return Proposal(
        game_id=game_id,
        run=run,
        cut_path=cut_path,
        curves_path=curves_path,
        segments=len(decoded.segments),
        kept_seconds=float(comment["stats"]["kept"]),
        review=len(comment["review"]),
    )
