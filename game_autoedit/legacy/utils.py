from collections.abc import Iterable
from pathlib import Path

import ffmpeg


def generate_proxy(
    files: Iterable[Path],
    target_file: Path,
    target_height: int = 360,
    quality: int = 23,
) -> None:
    """Generate a proxy video by concatenating multiple input videos, rescaling,
    and encoding with a CRF-based quality.

    - Concatenates inputs using the concat filter (expects compatible streams).
    - Rescales video to target_height while preserving aspect ratio (even width).
    - Encodes with H.264 using CRF for quality control.

    Parameters:
      files: Ordered iterable of input video paths to concatenate.
      target_file: Output file path for the generated proxy.
      target_height: Target height in pixels for resizing.
      quality: CRF value (0–51, lower is better quality; 23 is default).

    Raises:
      ValueError: If inputs are invalid or files do not exist.
      RuntimeError: If FFmpeg pipeline fails.
    """
    files = [Path(f) for f in files]
    if not files:
        raise ValueError("`files` ne peut pas être vide.")
    for f in files:
        if not f.exists():
            raise ValueError(f"Fichier introuvable: {f}")

    target_file = Path(target_file)
    target_file.parent.mkdir(parents=True, exist_ok=True)

    inputs = [ffmpeg.input(str(f)) for f in files]
    # Hypothèse: toutes les vidéos sont compatibles (codec, fps, résolution, pix_fmt, layout audio)
    # Si une piste audio manque, on concatène vidéo seule
    # Remarque: ffmpeg-python expose toujours .audio/.video; on considère l’audio présent si la 1re entrée a une piste
    probe_has_audio = True
    try:
        # On sonde le premier fichier pour vérifier la présence d'une piste audio
        probe = ffmpeg.probe(str(files[0]))
        probe_has_audio = any(
            s.get("codec_type") == "audio" for s in probe.get("streams", [])
        )
    except Exception:
        # Si la sonde échoue, on tente quand même et on laisse FFmpeg gérer
        probe_has_audio = True

    has_audio = probe_has_audio

    # Concat brut (sans scale/format) puis normalisation sur la sortie vidéo
    concat_inputs = []
    for inp in inputs:
        concat_inputs.append(inp.video)
        if has_audio:
            concat_inputs.append(inp.audio)

    concat = ffmpeg.filter(
        concat_inputs, "concat", n=len(inputs), v=1, a=1 if has_audio else 0
    )
    # Utiliser .stream(index) plutôt que l’indexation par [] qui lève TypeError
    # v_concat = concat.stream(0)
    # a_concat = concat.stream(1) if has_audio else None

    # Scale/format appliqués une seule fois après concat
    v_out = concat.filter("scale", "-2", str(int(target_height))).filter(
        "format", "yuv420p"
    )

    out_kwargs = {
        "vcodec": "libx264",
        "crf": int(quality),
        "preset": "medium",
        "pix_fmt": "yuv420p",
    }
    if has_audio:
        out_kwargs |= {"acodec": "aac", "b:a": "128k"}
    if target_file.suffix.lower() == ".mp4":
        out_kwargs |= {"movflags": "+faststart"}

    try:
        (
            ffmpeg.output(v_out, str(target_file), **out_kwargs)
            .global_args("-y")
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as e:
        msg = (
            e.stderr.decode("utf-8", "ignore") if getattr(e, "stderr", None) else str(e)
        )
        raise RuntimeError(f"Echec FFmpeg: {msg}") from e


def _probe_video_params(path: Path) -> tuple[float, int, int]:
    """Retourne (fps, width, height) de la vidéo via ffprobe."""
    try:
        probe = ffmpeg.probe(str(path))
    except ffmpeg.Error as e:
        stderr = (
            e.stderr.decode("utf-8", errors="ignore")
            if hasattr(e, "stderr") and isinstance(e.stderr, (bytes, bytearray))
            else str(e)
        )
        raise RuntimeError(f"ffprobe a échoué: {stderr}") from e

    vstream = next(
        (s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if not vstream:
        raise RuntimeError("Aucun flux vidéo détecté")

    # FPS
    rate = vstream.get("avg_frame_rate") or vstream.get("r_frame_rate")
    fps: float | None = None
    if rate and rate != "0/0":
        try:
            num, den = rate.split("/")
            n, d = int(num), int(den)
            if d != 0:
                fps = n / d
        except Exception:
            fps = None
    if fps is None:
        # fallback grossier
        nb_frames = vstream.get("nb_frames")
        duration = vstream.get("duration")
        try:
            if nb_frames and duration and float(duration) > 0:
                fps = int(nb_frames) / float(duration)
        except Exception:
            fps = None
    if fps is None or fps <= 0:
        fps = 25.0  # valeur par défaut sûre

    width = int(vstream.get("width") or 0)
    height = int(vstream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise RuntimeError("Dimensions vidéo introuvables")

    return fps, width, height


def generate_video_preview(
    source_file: Path,
    target_file: Path,
    cuts: Iterable[tuple[int, int]],
    time_mode: "FRAME" | "SECOND" = "FRAME",
) -> None:
    """Generate a preview vidéo by cutting source_file according to cuts (frame_in, frame_out) pairs.

    - Each cut is defined as half-open frames: [frame_in, frame_out), i.e., frame_out is excluded.
    - Converts frames to timestamps using fps.
    - Concatenates segments via the concat filter.
    - Rescales to target_height (keeps aspect ratio, even width).
    - Encodes using H.264 (CRF).

    Parameters:
      source_file: Source video path.
      target_file: Output file path.
      cuts: Iterable of (frame_in, frame_out) pairs.

    Raises:
      ValueError: If inputs are invalid.
    RuntimeError: If the FFmpeg pipeline fails.
    """
    source_file = Path(source_file)
    if not source_file.exists():
        raise ValueError(f"Fichier source introuvable: {source_file}")

    # Récupère FPS et dimensions de la source
    fps, src_w, src_h = _probe_video_params(source_file)

    # Normalise cuts
    norm_cuts: list[tuple[int, int]] = []
    for i, o in cuts:
        if i < 0 or o < 0:
            raise ValueError(f"Frames négatives interdites: {(i, o)}")
        if o <= i:
            continue
        norm_cuts.append((i, o))
    if not norm_cuts:
        raise ValueError("Aucun cut valide fourni")

    # Frames -> secondes (half-open)
    if time_mode == "FRAME":
        norm_cuts = [(i / fps, (o - i) / fps) for i, o in norm_cuts]
    elif time_mode == "SECOND":
        pass
    else:
        raise ValueError(f"Mode de temps invalide: {time_mode}")
    segments = [(i / fps, (o - i) / fps) for i, o in norm_cuts]

    try:
        inp = ffmpeg.input(str(source_file))
        streams = []
        pts = "PTS-STARTPTS"
        for start_s, end_s in segments:
            v = inp.video.trim(start=start_s, end=end_s).setpts(pts)
            # Remplacer les méthodes inexistantes .atrim/.asetpts par des filtres audio
            a = inp.audio.filter("atrim", start=start_s, end=end_s).filter(
                "asetpts", pts
            )
            streams.extend([v, a])

        concat = ffmpeg.concat(*streams, n=len(segments), v=1, a=1)
        output = ffmpeg.output(
            concat, filename=str(target_file), format="mp4"
        ).overwrite_output()
        output.run()

    except ffmpeg.Error as e:
        stderr = (
            e.stderr.decode("utf-8", errors="ignore")
            if hasattr(e, "stderr") and isinstance(e.stderr, (bytes, bytearray))
            else str(e)
        )
        raise RuntimeError(f"FFmpeg a échoué: {stderr}") from e


if __name__ == "__main__":
    base = Path("/mnt/video/juggerData/tournois/2025_09_20_DARM/rushs/")
    generate_video_preview(
        source_file=base / "GX011022.MP4",
        target_file="out_2.mp4",
        cuts=[(100, 2000), (2100, 4000)],
    )
    """generate_proxy(
        [base / "GX011022.MP4", base / "GX021022.MP4", base / "GX031022.MP4"],
        "out.mp4",
        target_height=360,
        quality=23,
    )"""
    print("finished")
