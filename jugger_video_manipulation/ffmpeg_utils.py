"""Defines utils to build ffmpeg comands."""

import functools
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from jugger_video_manipulation.cut_json_parser import Point
from jugger_video_manipulation.scoreboard import crossfade_durations, place_segments


def frame_rate(fps: float) -> str:
    """Return `fps` as the exact fraction ffmpeg filters compare on.

    `xfade` refuses two inputs whose frame rates differ, and it compares the
    fractions rather than the numbers: a rush at 60000/1001 and a still given
    `fps=59.940060` are the same rate written two ways, and it fails the whole
    render at the encoder over it. Rebuilding the fraction from the float
    gives the rate its filed form back — 59.94005994… is 60000/1001 again.
    """
    exact = Fraction(fps).limit_denominator(100000)
    return f"{exact.numerator}/{exact.denominator}"


#: The footage behind the opening card: blurred this much at 1080 lines, its
#: brightness brought down to this share, and its sound to this one. Only the
#: brightness is lowered, not the colour: a dark veil laid over the picture
#: took two thirds of the colour with it, and the field came out grey.
INTRO_BLUR_1080 = 16.0
INTRO_LUMA = 0.62
INTRO_VOLUME = 0.25

#: What a dissolve comes out as: the 4:2:0 formats the rushes and archives are
#: in, 10-bit included, so pinning never converts the picture it is given.
DISSOLVE_FORMATS = "yuvj420p|yuv420p|yuv420p10le"


def frame_bounds(point: Point, fps: float) -> str:
    """Return the `trim` bounds that keep exactly the frames `[in, out)`.

    A frame's timestamp is its index over the frame rate, so a bound written
    as `in / fps` falls *on* a frame, and floating point decides whether that
    frame is in or out. Half a frame back puts each bound between two frames,
    where no rounding can move it across one. A stabilised point needs this:
    its camera path is read frame by frame, and a point that starts one frame
    late gets every correction one frame late.
    """
    start = (int(point["in"]) - 0.5) / fps
    end = (int(point["out"]) - 0.5) / fps
    return f"start={max(start, 0.0):.6f}:end={end:.6f}"


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

    def filter_cut(
        self,
        fps: float,
        points: list[Point],
        crossfade: float = 0.0,
        video_filters: Sequence[str] | None = None,
    ) -> None:
        """Cut the video and audio inputs.

        A point whose `out` does not come after its `in` is dropped rather
        than trimmed to nothing: it would contribute no picture, and keeping
        it here would put the transitions and the scoreboard one point out of
        step with each other — `place_segments` drops it too.

        Args:
            fps: frames per second
            points: list of points to cut
            crossfade: seconds each point dissolves into the next. 0 joins
                them cleanly, which is what every render did before.
            video_filters: a filter chain per kept point, applied right after
                its trim — where its frames are numbered from zero, which is
                what a per-point stabilisation needs. One entry per point
                whose `out` comes after its `in`.
        """
        kept = [point for point in points if int(point["out"]) > int(point["in"])]
        nb_points = len(kept)
        if video_filters is not None and len(video_filters) != nb_points:
            raise ValueError(
                f"{len(video_filters)} video filter chains for {nb_points} kept points"
            )
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
        for i, point in enumerate(kept):
            t_in = point["in"] / fps
            t_out = point["out"] / fps
            extra = f",{video_filters[i]}" if video_filters else ""
            self.filter_complex.append(
                f"[v{i}_{index}]trim={frame_bounds(point, fps)},"
                f"setpts=PTS-STARTPTS{extra}[sv{i}_{index}]"
            )
            self.filter_complex.append(
                f"[a{i}_{index}]atrim={t_in}:{t_out},asetpts=PTS-STARTPTS[sa{i}_{index}]"
            )

        cut_v = [f"[sv{i}_{index}]" for i in range(nb_points)]
        cut_a = [f"[sa{i}_{index}]" for i in range(nb_points)]

        fades = crossfade_durations(kept, fps, crossfade)
        if any(fades):
            lengths = [(int(point["out"]) - int(point["in"])) / fps for point in kept]
            self.filter_dissolve(cut_v, cut_a, lengths, fades)
            return

        self.filter_concat(input_v=cut_v, input_a=cut_a)

    def filter_dissolve(
        self,
        input_v: list[str],
        input_a: list[str],
        lengths: list[float],
        fades: list[float],
    ) -> None:
        """Join cut points by dissolving each one into the next.

        `xfade` takes two streams at a time and is therefore chained: each
        transition is placed at `offset` seconds of what has already been
        joined, so the offsets are counted on a running total that shrinks by
        every transition already applied — the same arithmetic
        `place_segments` does to know where the scoreboard goes.

        Audio needs `acrossfade` rather than `xfade`, and it takes no offset:
        it always dissolves the end of its first input into the start of its
        second, which is the same instant.

        Args:
            input_v: the trimmed video streams, in order.
            input_a: the trimmed audio streams, in order.
            lengths: how long each point lasts, in seconds. The last one is
                never read — nothing is placed after it — which is what lets
                the intro join a video whose length it does not know.
            fades: the transition length at each join, `len(lengths) - 1` of
                them.
        """
        current_v, current_a = input_v[0], input_a[0]
        elapsed = lengths[0]
        for position, fade in enumerate(fades, start=1):
            index = self.index
            next_v, next_a = f"[xv{index}]", f"[xa{index}]"
            # Pinned back to 4:2:0: left to negotiate, xfade settles on 4:4:4
            # as soon as the encoder takes it, and libx264 does — the render
            # then comes out in a profile most players refuse.
            self.filter_complex.append(
                f"{current_v}{input_v[position]}xfade=transition=fade:"
                f"duration={fade:.3f}:offset={elapsed - fade:.3f},"
                f"format=pix_fmts={DISSOLVE_FORMATS}{next_v}"
            )
            self.filter_complex.append(
                f"{current_a}{input_a[position]}acrossfade=d={fade:.3f}{next_a}"
            )
            current_v, current_a = next_v, next_a
            elapsed += lengths[position] - fade

        self.out_v, self.out_a = current_v, current_a

    def filter_intro(
        self,
        card_index: int,
        silence_index: int,
        duration: float,
        fps: float,
        size: tuple[int, int],
        fade: float = 0.0,
    ) -> None:
        """Put a still card in front of the match, rather than over it.

        Overlaying the card on the opening seconds would hide the start of the
        first point, so it is joined ahead of the video instead.

        Three things the join insists on, each of which fails only once the
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
            duration: how long the card is up, transition included.
            fps: the render's frame rate.
            size: the render's frame size, which is also the size the overlays
                were drawn at.
            fade: how long the card dissolves into the match. 0 cuts straight
                to the match, which is what every render did before.

        The match starts `duration - fade` into the render, and that is what
        the caller offsets its overlay windows by.
        """
        index = self.index
        width, height = size
        card_v, card_a = f"[card_v{index}]", f"[card_a{index}]"
        video_v = f"[vid_v{index}]"

        # `fps` and `settb` on both branches: a still given a frame rate comes
        # out on its own timebase, and at a rate written as a different
        # fraction from the one the rushes carry. xfade refuses two inputs
        # that disagree on either — with a message about link parameters, once
        # the encoder has already started.
        rate = frame_rate(fps)
        self.filter_complex.append(
            f"[{card_index}:v]scale={width}:{height},setsar=1,"
            f"loop=loop=-1:size=1,fps={rate},"
            f"trim=duration={duration:.3f},setpts=PTS-STARTPTS,settb=AVTB{card_v}"
        )
        self.filter_complex.append(
            f"[{silence_index}:a]atrim=duration={duration:.3f},"
            f"asetpts=PTS-STARTPTS{card_a}"
        )
        self.filter_complex.append(
            f"{self.out_v}scale={width}:{height},setsar=1,fps={rate},settb=AVTB{video_v}"
        )
        self.out_v = video_v
        if fade > 0:
            # The card holds, then dissolves: the match is already running
            # underneath when the card finishes disappearing, which is why the
            # overlays start at `duration - fade` and not at `duration`.
            self.filter_dissolve(
                [card_v, self.out_v],
                [card_a, self.out_a],
                [duration, 0.0],
                [fade],
            )
            return
        self.filter_concat(input_v=[card_v, self.out_v], input_a=[card_a, self.out_a])

    def filter_branch(self) -> tuple[str, str]:
        """Split the current streams in two, and hand back the spare copy.

        The render goes on with one copy; the other is for something that
        needs the rushes as they were before the points are cut out of them —
        the footage behind the opening card, which comes from before the
        first point.

        Returns:
            The video and audio labels of the spare copy.
        """
        index = self.index
        main_v, main_a = f"[main_v{index}]", f"[main_a{index}]"
        spare_v, spare_a = f"[spare_v{index}]", f"[spare_a{index}]"
        self.filter_complex.append(f"{self.out_v}split=2{main_v}{spare_v}")
        self.filter_complex.append(f"{self.out_a}asplit=2{main_a}{spare_a}")
        self.out_v, self.out_a = main_v, main_a
        return spare_v, spare_a

    def filter_intro_video(  # noqa: PLR0913 — all keyword-only
        self,
        streams: tuple[str, str],
        *,
        card_index: int,
        start_frame: int,
        duration: float,
        fade: float,
        fps: float,
        size: tuple[int, int],
    ) -> None:
        """Play the seconds before the first point behind the card, then dissolve.

        The footage is the rushes' own, from `start_frame` for `duration`:
        blurred, dimmed with its colours kept, the card laid over it and its
        sound brought down.
        It runs `fade` past the first point's first frame, so the dissolve
        crosses the same instants of the match on both sides — the picture
        goes from blurred to sharp and the sound comes up, rather than two
        different moments being mixed together.

        Args:
            streams: the spare copy of the rushes, from `filter_branch`.
            card_index: ffmpeg input index of the transparent card image.
            start_frame: where the footage starts, in frames of the rushes.
            duration: how long the card is up, its dissolve included.
            fade: how long it dissolves into the first point.
            fps: the render's frame rate.
            size: the render's frame size, which the card was drawn at.
        """
        video, audio = streams
        index = self.index
        width, height = size
        rate = frame_rate(fps)
        frames = max(round(duration * fps), 1)
        start = max(start_frame - 0.5, 0.0) / fps
        end = (start_frame + frames - 0.5) / fps
        blur = max(INTRO_BLUR_1080 * height / 1080, 1.0)
        backdrop, intro_v, intro_a = (
            f"[intro_bg{index}]",
            f"[intro_v{index}]",
            f"[intro_a{index}]",
        )
        main_v = f"[vid_v{index}]"

        self.filter_complex.append(
            f"{video}trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
            f"scale={width}:{height},setsar=1,gblur=sigma={blur:.2f},"
            f"lutyuv=y=val*{INTRO_LUMA}{backdrop}"
        )
        # Laid over like any overlay: a single image, repeated for as long as
        # the footage lasts. Then the same rate and timebase as the match,
        # which xfade insists on.
        self.filter_complex.append(
            f"{backdrop}[{card_index}:v]overlay=0:0," f"fps={rate},settb=AVTB{intro_v}"
        )
        self.filter_complex.append(
            f"{audio}atrim=start={start_frame / fps:.6f}:end={(start_frame + frames) / fps:.6f},"
            f"asetpts=PTS-STARTPTS,volume={INTRO_VOLUME}{intro_a}"
        )
        self.filter_complex.append(
            f"{self.out_v}scale={width}:{height},setsar=1,fps={rate},settb=AVTB{main_v}"
        )
        self.out_v = main_v
        if fade > 0:
            self.filter_dissolve(
                [intro_v, self.out_v], [intro_a, self.out_a], [duration, 0.0], [fade]
            )
            return
        self.filter_concat(input_v=[intro_v, self.out_v], input_a=[intro_a, self.out_a])

    def filter_overlay(self, overlays: list[tuple[int, float, float]]) -> None:
        """Composite still overlays over the video, each on its own window.

        Args:
            overlays: for each overlay, the ffmpeg input index of its image and
                the seconds of the finished render it is shown between.

        Each window is closed at its start and open at its end: two boards
        that follow one another meet on a frame instead of both being painted
        on it — `between` includes both ends, and a see-through board drawn
        twice shows.

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
                f"overlay=0:0:enable='gte(t,{start:.3f})*lt(t,{end:.3f})'{node}"
            )
            current = node
        self.out_v = current

    def filter_fps(self, fps: float) -> None:
        """Pin the end of the graph to a constant frame rate.

        The intro concatenates a still with the video, and what comes out has
        no frame rate ffmpeg can put on the output stream. NVENC sizes its
        constant-quality target from that frame rate: without one it settles
        on a couple of Mbit/s and the picture breaks up, whatever `-cq` asks
        for. Ending the graph on `fps` hands it back, and costs nothing on a
        stream that is already at that rate.

        Args:
            fps: the rate the render is timed in.
        """
        src_v = self.out_v
        self.out_v = f"[fps_v{self.index}]"
        self.filter_complex.append(f"{src_v}fps={fps:f}{self.out_v}")

    def filter_scale(
        self, w: str | None = None, h: str | None = None, flags: str | None = None
    ) -> None:
        """Scale the video input.

        Args:
            w: width
            h: height use -2 to keep the aspect ratio
            flags: the scaling algorithm, `lanczos` for instance; ffmpeg's
                default when None.
        """
        src_v = self.out_v
        self.out_v = f"[scale_v{self.index}]"
        if not h:
            h = "-2"
        if w:
            algorithm = f":flags={flags}" if flags else ""
            self.filter_complex.append(f"{src_v}scale={w}:{h}{algorithm}{self.out_v}")
        else:
            self.filter_complex.append(f"{src_v}copy{self.out_v}")

    def filter_tv_range(self) -> None:
        """Bring the picture to the limited ("tv") range.

        GoPro rushes are full range (`yuvj420p`), and asking the encoder for
        `-pix_fmt yuv420p` does not convert them: the file only comes out
        tagged full range, which players and YouTube may show washed out or
        crushed. The conversion has to happen in the graph.
        """
        src_v = self.out_v
        self.out_v = f"[range_v{self.index}]"
        self.filter_complex.append(f"{src_v}scale=out_range=tv{self.out_v}")

    def get_filter_complex(self) -> str:
        """Write the filter complex comand as a str."""
        return ";".join(self.filter_complex)


@dataclass(frozen=True)
class ExtraInputs:
    """Inputs a render adds beyond its sources and its chapter metadata."""

    overlays: list[Path] = field(default_factory=list)
    silence_seconds: float | None = None


@dataclass(frozen=True)
class InputIndices:
    """Where each kind of input lands in the ffmpeg command."""

    silence: int | None
    first_overlay: int


def input_indices(
    nb_sources: int, *, has_metadata: bool, has_silence: bool
) -> InputIndices:
    """Return the input indices `ffmpeg_command_builder` will produce.

    Computing this in one place rather than at each call site is the point:
    getting it wrong points a filter at the wrong input, and ffmpeg only says
    so once it has parsed the whole graph.
    """
    cursor = nb_sources + (1 if has_metadata else 0)
    silence = cursor if has_silence else None
    return InputIndices(
        silence=silence, first_overlay=cursor + (1 if has_silence else 0)
    )


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
    extras: ExtraInputs | None = None,
    cuda: CudaUse | None = None,
) -> list[str]:
    """Build the ffmpeg command.

    Args:
        filter_complex : FilterComplexBuilder object
        input_files : list of input files
        output_file : output file path
        preset_args : dictionary of preset arguments
        chapter_metadata_path : path to metadata file
        extras : the still images to composite and, when a still is
            concatenated with the video, the silent track it needs
        cuda : which ends of the pipeline may use the GPU

    The input order is fixed and `input_indices` is the one place that knows
    it: sources, then the chapter metadata, then the silent track, then the
    overlay images. Metadata comes before the extras so `-map_metadata` keeps
    pointing at it however many images follow.
    """
    cuda = cuda or CudaUse()
    extras = extras or ExtraInputs()
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
    if extras.silence_seconds is not None:
        cmd += [
            "-f",
            "lavfi",
            "-t",
            f"{max(extras.silence_seconds, 1.0):.3f}",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
        ]
    for overlay in extras.overlays:
        cmd += ["-i", str(overlay.absolute())]
    cmd += ["-filter_complex", filter_complex.get_filter_complex()]
    cmd += ["-map", filter_complex.out_v, "-map", filter_complex.out_a]

    cmd += preset_args["video"]
    cmd += preset_args["audio"]
    cmd += ["-movflags", "+faststart"]
    if chapter_metadata_path:
        # Chapters are mapped explicitly too: left alone, ffmpeg copies them
        # from the first input that has any, and a GoPro rush can carry one.
        metadata_index = str(len(input_files))
        cmd += ["-map_metadata", metadata_index, "-map_chapters", metadata_index]
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
    crossfade: float = 0.0,
    offset: float = 0.0,
):
    """Write chapters metadata to a file.

    A chapter has to land where its point actually plays, so it is read off
    the same placement the scoreboard uses: transitions make two points share
    seconds, and an opening card pushes the whole match back.

    Args:
        points: list of points to cut
        metadata_path: path to metadata file to write on
        fps: frames per second
        crossfade: seconds each point dissolves into the next
        offset: seconds of render before the first point, an opening card
    """
    lines = [";FFMETADATA1\n"]
    for i, segment in enumerate(place_segments(points, fps, crossfade)):
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",  # on travaille en millisecondes
            f"START={int(1000 * (offset + segment.output_start))}",
            f"END={int(1000 * (offset + segment.output_end))}",
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


@functools.lru_cache(maxsize=256)
def _probe_frame_count(path: Path) -> int:
    """Return the frame count a container records for its first video stream.

    Cached: a rush does not change under the worker, and a queue page previews
    every pending render. A failure raises, and raising is not cached — a rush
    that comes back on disk is read again.

    Raises:
        ValueError: the file does not say how many frames it holds.
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_frames",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    # A GoPro lists its streams twice: the first value is the one.
    values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not values or not values[0].isdigit():
        raise ValueError(f"nombre d'images illisible pour {path}")
    return int(values[0])


def probe_frame_counts(files: Sequence[Path]) -> list[int]:
    """Return how many frames each source holds, from its container.

    The rushes are concatenated end to end, so this is what places a frame of
    the concatenation inside one rush, and what says where the last one ends.

    Raises:
        ValueError: a source does not say how many frames it holds.
    """
    return [_probe_frame_count(path) for path in files]


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
