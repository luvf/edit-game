"""Utils."""

from pathlib import Path

import moviepy.editor as mpy  # type: ignore[import-untyped]
from PIL import Image


def get_frame(video_file: Path, tc: float) -> Image.Image:
    """Get frame associated with the timecode.

    Args:
        video_file: path to video file
        tc: timecode in range 0-1
    Returns:
        pillow image object of the corresponding frame
    """
    vid = mpy.VideoFileClip(video_file)
    frame_clip = vid.duration
    time_code = int(frame_clip * tc)
    image = Image.fromarray(vid.get_frame(time_code))
    return image.resize((1920, int(1920 * (image.height / image.width))))


def get_ms_time(seconds: str | int | float) -> str:
    """Convert seconds to mm:ss format."""
    sec = int(float(seconds))
    minutes = sec // 60
    return str(minutes).zfill(2) + ":" + str(sec % 60).zfill(2)
