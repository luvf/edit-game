"""Utils."""

import os
from pathlib import Path

import ffmpeg  # type: ignore[import-untyped]
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


def get_chapters(vid_path: Path) -> list[dict[str, str]]:
    """Get chapters from the video file."""
    metadata = ffmpeg.probe(vid_path, show_chapters=None)
    chapters = []
    for m in metadata["chapters"]:
        chapter = {
            "start": get_ms_time(m["start_time"]),
            "end": get_ms_time(m["end_time"]),
        }
        chapters.append(chapter)
    return chapters


def get_ms_time(seconds: str | int | float) -> str:
    """Convert seconds to mm:ss format."""
    sec = int(float(seconds))
    minutes = sec // 60
    return str(minutes).zfill(2) + ":" + str(sec % 60).zfill(2)


def gen_proxy(
    input_dir: Path,
    video_files: list[Path],
    out_filename: Path,
    tmp_dir: Path = Path("game_edit/previews"),
) -> Path:
    """Generate a proxy video from a list of video files.

    source_vdeo = mpy.VideoFileClip(os.path.join(video_dir, video_files[0]))

    Args:
        input_dir: path to the video files
        video_files: list of video files
        out_filename: name of the output file
        tmp_dir: dir where to write the proyed video
    Returns:
        out_file path of the proxy video
    """
    out_file = tmp_dir / out_filename
    tmp_txt = Path("game_edit/tmp") / Path("tmp_source.txt")
    with tmp_txt.open("w") as f:
        f.writelines(
            ["file '" + str((input_dir / v).absolute()) + "'\n" for v in video_files]
        )
    ffmpeg_str = f"ffmpeg -y -f concat -safe 0 -i {tmp_txt} -preset fast -crf 32  -vf scale=640x360 ç -ar {16000} {out_file}"

    os.system(ffmpeg_str)

    return out_file


def generate_preview(
    input_dir: Path,
    video_files: list[Path],
    out_filename: Path,
    tmp_dir: Path = Path("game_edit/previews"),
) -> Path:
    """Generate a preview video from a list of video files.

    Args:
        input_dir: path to the video files
        video_files: list of video files
        out_filename: name of the output file
        tmp_dir: dir where to write the proyed video

    Returns:
        out_file path of the proxy video

    """
    out_file = tmp_dir / out_filename

    input_files = [ffmpeg.input(str((input_dir / v).absolute())) for v in video_files]
    stream = ffmpeg.concat(*input_files).filter("scale", 640, -1)

    stream = ffmpeg.output(
        stream,
        out_file,
        preset="fast",
        crf=32,
    ).overwrite_output()
    stream.run()

    return out_file
