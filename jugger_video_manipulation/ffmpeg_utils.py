"""Defines utils to build ffmpeg comands."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from jugger_video_manipulation.cut_json_parser import Point


class FilterComplexBuilder:
    """Builds filter complex comands."""

    def __init__(self, nb_inputs: int):
        """Prepare the filter complex comands."""
        self.filter_complex = []
        self.inputs_v = []
        self.inputs_a = []
        self.out_v = ""
        self.out_a = ""
        self.create_inputs(nb_inputs)

    @property
    def index(self):
        """Return the index of the filter complex to have unique node names."""
        return len(self.filter_complex)

    def create_inputs(self, nb_inputs: int) -> None:
        """Create a list of inputs for video and audio.

        Args:
            nb_inputs : number of inputs
        returns:
            list for video and list for audio inputs
        """
        self.inputs_v = [f"[{i}:v:0]" for i in range(nb_inputs)]
        self.inputs_a = [f"[{i}:a:0]" for i in range(nb_inputs)]

    def filter_concat(self, input_v: list[str], input_a: list[str]) -> None:
        """Concatenate video and audio inputs.

        Args:
            input_v : list of video inputs
            input_a : list of audio inputs
        """
        nb_inputs = len(input_v)
        if len(input_v) != len(input_a):
            raise ValueError("the number  and nb_a must be equal on audio and on video")
        if len(input_v) == 0:
            raise ValueError("the number of inputs must be greater than 0")
        self.out_v = f"[cv{self.index}]"
        self.out_a = f"[ca{self.index}]"
        if nb_inputs > 1:
            concat_inputs = "".join(
                f"{v}{a}" for v, a in zip(input_v, input_a, strict=False)
            )
            self.filter_complex.append(
                f"{concat_inputs}concat=n={nb_inputs}:v=1:a=1{self.out_v}{self.out_a}"
            )

        else:
            self.filter_complex.append(f"{input_v[0]}copy{self.out_v}")
            self.filter_complex.append(f"{input_a[0]}anull{self.out_a}")

    def filter_cut(self, fps: float, points: list[Point]) -> None:
        """Cut the video and audio inputs.

        Args:
            fps: frames per second
            points: list of points to cut
        """
        nb_points = len(points)
        src_v, src_a = self.out_v, self.out_a
        index = self.index

        self.filter_complex.append(
            f"{src_v}split={nb_points}"
            + "".join(f"[v{i}_{index}]" for i in range(nb_points))
        )
        self.filter_complex.append(
            f"{src_a}asplit={nb_points}"
            + "".join(f"[a{i}_{index}]" for i in range(nb_points))
        )
        for i, point in enumerate(points):
            t_in = point["in"] / fps
            t_out = point["out"] / fps
            self.filter_complex.append(
                f"[v{i}_{index}]trim={t_in}:{t_out},setpts=PTS-STARTPTS[sv{i}_{index}]"
            )
            self.filter_complex.append(
                f"[a{i}_{index}]atrim={t_in}:{t_out},asetpts=PTS-STARTPTS[sa{i}_{index}]"
            )

        self.filter_concat(
            input_v=[f"[sv{i}_{index}]" for i in range(nb_points)],
            input_a=[f"[sa{i}_{index}]" for i in range(nb_points)],
        )

    def filter_intro(
        self,
        card_index: int,
        silence_index: int,
        duration: float,
        fps: float,
        size: tuple[int, int],
    ) -> None:
        """Put a still card in front of the match, rather than over it.

        Overlaying the card on the opening seconds would hide the start of the
        first point, so it is concatenated ahead of the video instead.

        Three things `concat` insists on, each of which fails only once the
        encoder starts, with a message about link parameters:

        - both sides must agree on size *and* pixel aspect. A proxy carries a
          SAR of 1280:1281 while a drawn card is square-pixelled, so both
          branches are scaled to `size` and forced to square pixels rather
          than trusting either to already match;
        - a still image is one frame, so it is looped and given a frame rate
          before being trimmed, or the card lasts a single frame however long
          the trim says;
        - both sides need both streams, hence the silent audio input, or the
          audio is dropped from the whole render.

        Args:
            card_index: ffmpeg input index of the card image.
            silence_index: input index of a silent audio source.
            duration: how long the card stays up, in seconds.
            fps: the render's frame rate.
            size: the render's frame size, which is also the size the overlays
                were drawn at.

        Everything the card pushes back moves by `duration`; the caller offsets
        its overlay windows by the same amount.
        """
        index = self.index
        width, height = size
        card_v, card_a = f"[card_v{index}]", f"[card_a{index}]"
        video_v = f"[vid_v{index}]"

        self.filter_complex.append(
            f"[{card_index}:v]scale={width}:{height},setsar=1,"
            f"loop=loop=-1:size=1,fps={fps:.6f},"
            f"trim=duration={duration:.3f},setpts=PTS-STARTPTS{card_v}"
        )
        self.filter_complex.append(
            f"[{silence_index}:a]atrim=duration={duration:.3f},"
            f"asetpts=PTS-STARTPTS{card_a}"
        )
        self.filter_complex.append(
            f"{self.out_v}scale={width}:{height},setsar=1{video_v}"
        )
        self.out_v = video_v
        self.filter_concat(input_v=[card_v, self.out_v], input_a=[card_a, self.out_a])

    def filter_overlay(self, overlays: list[tuple[int, float, float]]) -> None:
        """Composite still overlays over the video, each on its own window.

        Args:
            overlays: for each overlay, the ffmpeg input index of its image and
                the seconds of the finished render it is shown between.

        The images are single-frame inputs. `overlay` repeats the last frame of
        an exhausted input by default, so one PNG covers its whole window
        without being looped, and `enable` decides when it is painted at all.
        """
        if not overlays:
            return

        current = self.out_v
        for input_index, start, end in overlays:
            index = self.index
            node = f"[ov{index}]"
            self.filter_complex.append(
                f"{current}[{input_index}:v]"
                f"overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'{node}"
            )
            current = node
        self.out_v = current

    def filter_scale(self, w: str | None = None, h: str | None = None) -> None:
        """Scale the video input.

        Args:
            w: width
            h: height use -2 to keep the aspect ratio
        """
        src_v = self.out_v
        self.out_v = f"[scale_v{self.index}]"
        if not h:
            h = "-2"
        if w:
            self.filter_complex.append(f"{src_v}scale={w}:{h}{self.out_v}")
        else:
            self.filter_complex.append(f"{src_v}copy{self.out_v}")

    def get_filter_complex(self) -> str:
        """Write the filter complex comand as a str."""
        return ";".join(self.filter_complex)


@dataclass(frozen=True)
class CudaUse:
    """Which ends of the pipeline may use the GPU."""

    decode: bool = False
    encode: bool = False


def ffmpeg_command_builder(
    *,
    filter_complex: FilterComplexBuilder,
    input_files: list[Path],
    output_file: Path | None,
    preset_args: dict[str, list[str]],
    chapter_metadata_path: Path | None = None,
    overlay_files: list[Path] | None = None,
    cuda: CudaUse | None = None,
) -> list[str]:
    """Build the ffmpeg command.

    Args:
        filter_complex : FilterComplexBuilder object
        input_files : list of input files
        output_file : output file path
        preset_args : dictionary of preset arguments
        chapter_metadata_path : path to metadata file
        overlay_files : still images to composite, added after the metadata
            input so their indices never shift `-map_metadata`
        cuda : which ends of the pipeline may use the GPU
    """
    cuda = cuda or CudaUse()
    if output_file is None:
        raise ValueError("output_file must not be None")

    _validate_encode_cuda_usage(
        preset_args=preset_args,
        encode_cuda_available=cuda.encode,
    )

    cmd = ["ffmpeg"]
    cmd += _add_input_files(input_files, decode_cuda_available=cuda.decode)
    filter_complex.create_inputs(len(input_files))
    if chapter_metadata_path:
        cmd += ["-i", str(chapter_metadata_path.absolute())]
    for overlay in overlay_files or []:
        cmd += ["-i", str(overlay.absolute())]
    cmd += ["-filter_complex", filter_complex.get_filter_complex()]
    cmd += ["-map", filter_complex.out_v, "-map", filter_complex.out_a]

    cmd += preset_args["video"]
    cmd += preset_args["audio"]
    cmd += ["-movflags", "+faststart"]
    if chapter_metadata_path:
        cmd += ["-map_metadata", str(len(input_files))]
    cmd += [str(output_file.absolute()), "-y"]
    return cmd


def _validate_encode_cuda_usage(
    *,
    preset_args: dict[str, list[str]],
    encode_cuda_available: bool,
) -> None:
    """Ensure NVENC presets are not used when CUDA/NVENC is unavailable."""
    video_args = preset_args.get("video", [])
    uses_nvenc = any(arg.endswith("_nvenc") for arg in video_args)

    if uses_nvenc and not encode_cuda_available:
        raise ValueError("NVENC encoder requested but CUDA/NVENC is not available.")


@dataclass
class Chapter:
    """Define a chapter structure."""

    start_time: float
    end_time: float
    title: str


def write_chapters_metadata(
    *,
    points: list[Point],
    metadata_path: Path,
    fps: float = 60,
):
    """Write chapters metadata to a file.

    Args:
        points: list of points to cut
        fps: frames per second
        metadata_path: path to metadata file to write on
    """
    durations = [point["out"] - point["in"] for point in points]
    lines = [";FFMETADATA1\n"]
    end_ms = 0
    for i, chapter_duration in enumerate(durations):
        start_ms = end_ms
        end_ms = int(end_ms + (1000 * chapter_duration / fps))
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",  # on travaille en millisecondes
            f"START={start_ms}",
            f"END={end_ms}",
            f"title=point {i}",
            "",  # ligne vide entre chapitres
        ]

    metadata_path.write_text("\n".join(lines))


def _add_input_files(
    inputs: list[Path], *, decode_cuda_available: bool = False
) -> list[str]:
    """Add input files to the ffmpeg command."""
    cmd = []
    for f in inputs:
        if decode_cuda_available:
            cmd += ["-hwaccel", "cuda"]
        cmd += ["-i", str(f.absolute())]
    return cmd


def get_fps(video_file: Path) -> float:
    """Get the fps of a video file.

    Args:
        video_file: Path to the video file
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-select_streams",
            "v:0",  # uniquement le premier flux vidéo
            str(video_file.absolute()),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    data = json.loads(result.stdout)
    stream = data["streams"][0]

    num, den = map(int, stream["r_frame_rate"].split("/"))
    return num / den


def extract_audio(video_files: list[Path], audio_path: Path, sample_rate: int = 22050):
    """Extract audio from a video file.

    Args:
        video_files: List of video files
        audio_path: Path to save the extracted audio
        sample_rate: Sample rate for the extracted audio
    """
    cmd = ["ffmpeg"]

    for file in video_files:
        cmd += ["-i", str(file.absolute())]

    n = len(video_files)

    if n > 1:
        # Concat audio de tous les fichiers
        concat_inputs = "".join(f"[{i}:a:0]" for i in range(n))
        filter_complex = f"{concat_inputs}concat=n={n}:v=0:a=1[outa]"

        cmd += ["-filter_complex", filter_complex]
        cmd += ["-map", "[outa]"]
    else:
        cmd += ["-map", "0:a:0"]

    cmd += [
        "-c:a",
        "pcm_s16le",  # WAV non compressé → meilleur pour librosa
        "-ar",
        str(sample_rate),  # sample rate aligné avec librosa.load
        "-ac",
        "1",  # mono
        str(audio_path.absolute()),
        "-y",
    ]
    subprocess.run(cmd, check=True)


def get_chapters(video_file: Path) -> list[tuple[float, float]]:
    """Get chapters from a video file.

    Args:
        video_file: Path to the video file
    Returns:
        List of tuples containing start and end times of chapters
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_chapters",
            str(video_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    data = json.loads(result.stdout)
    chapters = data.get("chapters", [])

    if not chapters:
        return []

    return [(float(ch["start_time"]), float(ch["end_time"])) for ch in chapters]
