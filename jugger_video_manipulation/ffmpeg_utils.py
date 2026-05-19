"""Defines utils to build ffmpeg comands."""

from pathlib import Path

from imageio.plugins import ffmpeg

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
            raise ValueError("the nember  and nb_a must be equal on audio and on video")
        if len(input_v) == 0:
            raise ValueError("the nember of inputs must be greater than 0")
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


def ffmpeg_command_builder(
    *,
    filter_complex: FilterComplexBuilder,
    input_files: list[Path],
    output_file: Path,
    preset_args: dict[str, list[str]],
    cuda_available: bool = False,
) -> list[str]:
    """Build the ffmpeg comand.

    Args:
        filter_complex : FilterComplexBuilder object
        inputs : list of input files
        preset_args : dictionary of preset arguments
        cuda_available : boolean indicating if cuda is available
        output_file : output file path
    """
    cmd = ["ffmpeg"]
    cmd += _add_input_files(input_files, cuda_available)
    cmd += ["-filter_complex", filter_complex.get_filter_complex()]
    cmd += ["-map", filter_complex.out_v, "-map", filter_complex.out_a]

    cmd += preset_args["video"]
    cmd += preset_args["audio"]
    cmd += ["-movflags", "+faststart"]
    cmd += [str(output_file.absolute()), "-y"]
    return cmd


def _add_input_files(inputs: list[Path], *, cuda_available: bool = False) -> list[str]:
    """Add input files to the ffmpeg command."""
    cmd = []
    for f in inputs:
        if cuda_available:
            cmd += ["-hwaccel", "cuda"]
        cmd += ["-i", str(f.absolute())]
    return cmd


def get_fps(filepath: str) -> float:
    """Return the video frame rate from the given filepath."""
    probe = ffmpeg.probe(filepath)
    video_stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
    num, den = map(int, video_stream["r_frame_rate"].split("/"))
    return num / den
