"""Pictures read out of a game's video, at a low and regular rate.

The encoder looks at a few frames a second, a few hundred pixels wide: enough to
see where the players stand and how they move, which is what separates a point
from the dead time around it. ffmpeg does the decoding, the resampling to that
rate and the scaling in one pass, and hands over raw RGB.
"""

from __future__ import annotations

import subprocess
import tempfile
import threading
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


def _input_args(sources: Sequence[Path], listing: Path) -> list[str]:
    """Return the ffmpeg input arguments reading `sources` back to back.

    Several sources are a game's rushes, concatenated in order exactly as the
    archive was; the concat demuxer keeps their timestamps continuous.
    """
    if len(sources) == 1:
        return ["-i", str(sources[0])]
    # The concat format quotes with ', and escapes a quote as '\''.
    escaped = (str(path).replace("'", "'\\''") for path in sources)
    listing.write_text("".join(f"file '{path}'\n" for path in escaped))
    return ["-f", "concat", "-safe", "0", "-i", str(listing)]


def read_frames(
    sources: Sequence[Path],
    *,
    rate: float,
    width: int,
    height: int,
    batch: int = 64,
) -> Iterator[np.ndarray]:
    """Yield a game's frames, `rate` per second, in batches.

    Frame ``i`` shows the instant ``i / rate`` on the game's timeline.

    Args:
        sources: the files to read, in timeline order.
        rate: frames per second to produce.
        width: output width in pixels.
        height: output height in pixels.
        batch: frames per yielded array.

    Yields:
        ``(n, height, width, 3)`` uint8 RGB arrays, ``n <= batch``.

    Raises:
        RuntimeError: ffmpeg failed before the end of the video.
    """
    frame_bytes = width * height * 3
    with tempfile.TemporaryDirectory() as tmp:
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            *_input_args(sources, Path(tmp) / "sources.txt"),
            "-an",
            "-vf",
            f"fps={rate},scale={width}:{height}:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        assert process.stdout is not None
        try:
            while True:
                chunk = process.stdout.read(frame_bytes * batch)
                count = len(chunk) // frame_bytes
                if count:
                    yield np.frombuffer(
                        chunk[: count * frame_bytes], dtype=np.uint8
                    ).reshape(count, height, width, 3)
                if len(chunk) < frame_bytes * batch:
                    break
        finally:
            process.stdout.close()
            stderr = (
                process.stderr.read().decode(errors="replace") if process.stderr else ""
            )
            code = process.wait()
        if code != 0:
            raise RuntimeError(f"ffmpeg a échoué ({code}) : {stderr.strip()[-500:]}")


def prefetched(frames: Iterator[np.ndarray], depth: int = 4) -> Iterator[np.ndarray]:
    """Yield from `frames` while a thread keeps reading ahead.

    ffmpeg blocks as soon as its pipe is full, so read in turn with the model
    the two take turns instead of working together: the card sat at 30 % while
    decoding waited. A few batches read ahead let both run at once.
    """
    queue: Queue[np.ndarray | BaseException | None] = Queue(maxsize=depth)

    def fill() -> None:
        try:
            for batch in frames:
                queue.put(batch)
        except BaseException as error:  # -- handed to the reader
            queue.put(error)
            return
        queue.put(None)

    thread = threading.Thread(target=fill, daemon=True)
    thread.start()
    while True:
        item = queue.get()
        if item is None:
            break
        if isinstance(item, BaseException):
            raise item
        yield item
    thread.join()
