"""FFmpeg-backed render queue items: shared encoder logic + Cut/Proxy jobs."""

from __future__ import annotations

import contextlib
import functools
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, ClassVar

from django.db import models

from core.models.render_queue.base import RenderQueueItemBase
from core.models.video import VideoFile
from edit_game import settings
from jugger_video_manipulation.cut_json_parser import CutJsonParser
from jugger_video_manipulation.ffmpeg_utils import (
    FilterComplexBuilder,
    ffmpeg_command_builder,
    get_fps,
    write_chapters_metadata,
)


@functools.cache
def _cuda_device_initialises(ffmpeg_path: str) -> bool:
    """Run a no-op ffmpeg whose only job is to create a CUDA device.

    Decodes nothing (`-frames:v 0`), so it costs a process spawn and answers
    the one question that matters: does CUDA come up on this machine, now.

    Cached per process: `_is_cuda_available` is consulted several times per
    queued job, and a driver that starts or stops working takes a reboot --
    which restarts the worker, and re-probes.
    """
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-init_hw_device",
                "cuda:0",
                "-f",
                "lavfi",
                "-i",
                "nullsrc",
                "-frames:v",
                "0",
                "-f",
                "null",
                "-",
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return result.returncode == 0


class RenderQueueItemFFMPEG(RenderQueueItemBase):
    """Concrete base for ffmpeg-driven jobs; treat `build_command` as abstract."""

    PRESET_ARGS_GPU: ClassVar[dict[str, dict[str, list[str]]]] = {
        "low": {
            "scale": ["854", "-2"],
            "video": [
                "-c:v",
                "h264_nvenc",
                "-cq",
                "35",
                "-preset",
                "p4",
            ],
            "audio": ["-c:a", "aac", "-b:a", "96k"],
        },
        "medium": {
            "scale": ["1280", "-2"],
            "video": ["-c:v", "hevc_nvenc", "-cq", "32", "-preset", "p4"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
        "high": {
            "video": ["-c:v", "hevc_nvenc", "-cq", "18", "-preset", "p4"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
    }
    PRESET_ARGS_CPU: ClassVar[dict[str, dict[str, list[str]]]] = {
        "low": {
            "scale": ["640", "-2"],
            "video": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "35"],
            "audio": ["-c:a", "aac", "-b:a", "96"],
        },
        "medium": {
            "video": ["-c:v", "libx264", "-preset", "medium", "-crf", "23"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
        "high": {
            "video": ["-c:v", "libx264", "-preset", "slow", "-crf", "20"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
        "low_av1": {
            "scale": ["854", "-2"],
            "video": ["-c:v", "libsvtav1", "-crf", "61", "-preset", "6"],
            "audio": ["-c:a", "aac", "-b:a", "96k"],
        },
        "medium_av1": {
            "video": ["-c:v", "libsvtav1", "-crf", "55", "-preset", "6"],
            "audio": ["-c:a", "aac", "-b:a", "160k"],
        },
        "high_av1": {
            "video": ["-c:v", "libsvtav1", "-crf", "24", "-preset", "6"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
    }

    preset = models.CharField(max_length=10, default="medium")
    output_filename = models.CharField(max_length=255, blank=True, default="")
    command = models.TextField(blank=True, default="")
    tmp_concat_file = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_ffmpeg"

    @staticmethod
    @functools.lru_cache(maxsize=1024)
    def _probe_video_stream_entry(file_path: Path, entry: str) -> str | None:
        """Return one `stream=<entry>` value of the first video stream.

        Cached: a media file's resolution does not change under us, and
        previewing a queue page probes every source of every pending item.

        Only the first line is kept, and that matters: a GoPro MP4 exposes two
        groups of streams, so `-select_streams v:0` matches twice and ffprobe
        prints the value once per match. Reading the whole output gave
        the height twice over, which `int()` refused, so it came back as an unknown
        height, which silently skipped the downscale — leaving 4K archives at
        40 GB an hour.

        None when ffprobe can't read the file or reports nothing.
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    f"stream={entry}",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(file_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, OSError):
            return None

        for line in result.stdout.splitlines():
            value = line.strip()
            if value:
                return value
        return None

    @classmethod
    def _source_has_av1_video(cls, file_path: Path) -> bool:
        """Return True when the source file contains an AV1 video stream."""
        codec_name = cls._probe_video_stream_entry(file_path, "codec_name")
        return codec_name is not None and codec_name.lower() == "av1"

    @classmethod
    def _source_video_height(cls, file_path: Path) -> int | None:
        """Return the height of the first video stream, None when unreadable."""
        height = cls._probe_video_stream_entry(file_path, "height")
        if height is None:
            return None
        try:
            return int(height)
        except ValueError:
            return None

    def _can_use_cuda_for_decode(self, source_files: list[Path]) -> bool:
        """Return True when CUDA can safely be used for decoding all sources."""
        if not self._is_cuda_available():
            return False

        return not any(
            self._source_has_av1_video(source_file) for source_file in source_files
        )

    def _can_use_cuda_for_encode(self) -> bool:
        """Return True when CUDA can be used for NVENC encoding."""
        return self._is_cuda_available()

    @staticmethod
    def _is_cuda_available() -> bool:
        """Tell whether CUDA can actually be initialised right now.

        `ffmpeg -hwaccels` only lists what the binary was *built* with, so it
        keeps reporting cuda long after the driver stopped working — after an
        NVIDIA upgrade without a reboot, for instance, where the kernel module
        and the userspace libraries disagree. Trusting it makes the render
        fail outright with CUDA_ERROR_SYSTEM_DRIVER_MISMATCH; actually
        creating a device is the only answer that matches what ffmpeg will do
        during the render, and it lets the job fall back to CPU decoding.
        """
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return False
        return _cuda_device_initialises(ffmpeg_path)

    @property
    def command_parameters(self) -> str:
        """Return the command this item will run.

        For an item that has not run yet, the stored command is only whatever
        was built the last time something asked — possibly by older code, since
        `_execute` rebuilds the command before running it. Displaying that as
        if it were the command to be executed is worse than showing nothing: a
        queue full of items built before the downscale fix went on showing a
        command with no rescale, while the render itself would have applied
        one.

        The preview is built against the stored output filename rather than
        `final_output_path`, which creates rows and touches the disk.
        """
        if self.status in {self.Status.CREATED, self.Status.WAITING}:
            with contextlib.suppress(Exception):
                preview = self.build_command(
                    output_file=Path(self.output_filename or "output.mp4")
                )
                return " ".join(preview)
        return self.command

    @property
    def metadata(self) -> str:
        """Return metadata for this queue item, if any."""
        return self.preset

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Fill output_filename from the renderable when missing."""
        if not self.output_filename:
            with contextlib.suppress(Exception):
                self.output_filename = self.final_output_path.name
        super().save(*args, **kwargs)

    @property
    def final_output_path(self) -> Path:
        """Return the final path where the rendered file must be written."""
        raise NotImplementedError("Use a concrete ffmpeg queue item type.")

    def build_command(
        self,
        chapter_metadata_tmp_path: Path | None = None,
        output_file: Path | None = None,
    ) -> list[str]:
        """Build the ffmpeg command for this queue item."""
        raise NotImplementedError("Use a concrete ffmpeg queue item type.")

    def _execute(self) -> None:
        """Build the ffmpeg command, persist it, then run it."""
        tmp_dir = Path(Path(settings.BASE_DIR) / "tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)

        tmp_output_path = tmp_dir / f"{uuid.uuid4()}.mp4"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as template_file:
            metadata_path = Path(template_file.name)

        try:
            command = self.build_command(
                chapter_metadata_tmp_path=metadata_path,
                output_file=tmp_output_path,
            )

            update_fields: list[str] = ["command"]
            if self.output_filename:
                update_fields.append("output_filename")
            self.command = " ".join(command)
            self.save(update_fields=update_fields)

            self._run_subprocess(command)

            actual_metadata = self._probe_file(tmp_output_path)
            expected_metadata = self._expected_metadata()

            validation_errors = self._validation_errors(actual_metadata)
            if validation_errors:
                raise ValueError(
                    f"expected : {expected_metadata}... got {actual_metadata}. "
                    f"Validation errors: {', '.join(validation_errors)}"
                )

            final_path = self.final_output_path
            final_path.parent.mkdir(parents=True, exist_ok=True)

            self._move_into_place(tmp_output_path, final_path)

        finally:
            metadata_path.unlink(missing_ok=True)
            tmp_output_path.unlink(missing_ok=True)

    @staticmethod
    def _move_into_place(tmp_path: Path, final_path: Path) -> None:
        """Move the rendered file to its final path.

        tmp_path and final_path can live on different filesystems (e.g. a
        local tmp dir and a network mount), so a plain rename isn't possible.
        Instead, copy to a staging file in final_path's own directory, then
        atomically rename it over final_path. This never truncates/opens
        final_path itself, so an existing file there (e.g. still open for
        reading elsewhere) is only ever swapped out atomically, never
        corrupted mid-write.
        """
        staging_path = final_path.with_name(
            f".{final_path.name}.tmp-{uuid.uuid4().hex}"
        )
        try:
            shutil.copyfile(str(tmp_path), str(staging_path))
            staging_path.replace(final_path)
        finally:
            staging_path.unlink(missing_ok=True)

    def _probe_file(self, file_path: Path) -> Any:
        """Return ffprobe metadata as a dict."""
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(file_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def _expected_metadata(self) -> dict[str, str]:
        """Return the expected metadata for the generated file."""
        return {
            "preset": self.preset,
        }

    def _validation_errors(self, actual_metadata: dict[str, Any]) -> list[str]:
        """Return the list of validation errors for the generated file."""
        errors: list[str] = []
        minimal_clip_lengh = 5
        format_info = actual_metadata.get("format") or {}
        streams = actual_metadata.get("streams") or []

        format_name = str(format_info.get("format_name", "")).lower()
        if "mp4" not in format_name:
            errors.append(f"format attendu mp4, obtenu {format_name or 'inconnu'}")

        try:
            duration = float(format_info.get("duration", 0))
        except (TypeError, ValueError):
            duration = 0
        if duration <= minimal_clip_lengh:
            errors.append(f"durée attendue > 5s, obtenue {duration}s")

        has_video = any(stream.get("codec_type") == "video" for stream in streams)
        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)

        if not has_video:
            errors.append("aucune piste vidéo détectée")
        if not has_audio:
            errors.append("aucune piste audio détectée")

        return errors

    def _preset_args(
        self, source_files: list[Path] | None = None
    ) -> dict[str, list[str]]:
        """Return ffmpeg args for the selected preset.

        `source_files` lets a subclass adapt the args to what it is about to
        encode; it is unused here.
        """
        _ = source_files
        default_preset_cpu = next(iter(self.PRESET_ARGS_CPU.keys()))
        cpu_preset_args = self.PRESET_ARGS_CPU.get(
            self.preset,
            self.PRESET_ARGS_CPU[default_preset_cpu],
        )

        if not self._is_cuda_available():
            return cpu_preset_args

        return self.PRESET_ARGS_GPU.get(self.preset, cpu_preset_args)

    def delete(
        self,
        using: Any | None = None,
        keep_parents: bool = False,  # noqa: FBT001, FBT002
    ) -> tuple[int, dict[str, int]]:
        """Delete the queue item and its tmp concat file, if any."""
        if self.tmp_concat_file:
            concat_path = Path(self.tmp_concat_file)
            with contextlib.suppress(OSError):
                concat_path.unlink()
        return super().delete(using=using, keep_parents=keep_parents)


class RenderQueueItemCut(RenderQueueItemFFMPEG):
    """Queue item for cut renders."""

    cut = models.ForeignKey("core.Cut", on_delete=models.CASCADE)

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_cut"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches cut renders."""
        self.job_type = self.JobType.CUT_RENDER
        super().save(*args, **kwargs)

    @property
    def final_output_path(self) -> Path:
        """Return the final output path for this cut render."""
        self.cut.ensure_video()
        video = self.cut.rendered_video

        video_file, _ = VideoFile.objects.get_or_create(
            video=video,
            quality=self.preset,
            format=VideoFile.Format.MP4,
        )
        final_path = video_file.expected_path()
        video_file.set_real_path(final_path)
        return final_path

    def build_command(
        self,
        chapter_metadata_tmp_path: Path | None = None,
        output_file: Path | None = None,
    ) -> list[str]:
        """Build the ffmpeg command for cut renders.

        First concatenate the input files
        Second split the concatenated file into in-out segments
        Last encode the split file with the selected preset.

        Args:
            chapter_metadata_tmp_path: Path to the temporary metadata file, if any.
            output_file: Path to the output file, if any.

        Return:
            The ffmpeg command for subprocess.
        """
        game = self.cut.game
        out_file = output_file or self.final_output_path
        out_file.parent.mkdir(parents=True, exist_ok=True)

        points, _ = CutJsonParser(self.cut.json_file.path).parse()

        preset_args = self._preset_args()

        source_files = game.get_source_files()
        nb_files = len(source_files)

        fps = get_fps(source_files[0])

        filter_complex = FilterComplexBuilder(nb_files)
        filter_complex.filter_concat(filter_complex.inputs_v, filter_complex.inputs_a)
        filter_complex.filter_cut(fps, points)

        scale = preset_args.get("scale")
        if scale:
            w, h = scale
            filter_complex.filter_scale(w, h)

        if chapter_metadata_tmp_path:
            write_chapters_metadata(
                points=points,
                metadata_path=chapter_metadata_tmp_path,
                fps=fps,
            )

        cmd = ffmpeg_command_builder(
            filter_complex=filter_complex,
            input_files=source_files,
            output_file=out_file,
            chapter_metadata_path=chapter_metadata_tmp_path,
            preset_args=preset_args,
            decode_cuda_available=self._can_use_cuda_for_decode(source_files),
            encode_cuda_available=self._can_use_cuda_for_encode(),
        )
        self.command = " ".join(cmd)
        return cmd


class RenderQueueItemGameRender(RenderQueueItemFFMPEG):
    """Queue item for proxy renders."""

    game = models.ForeignKey("core.Game", on_delete=models.CASCADE)

    class Meta:
        """Model metadata."""

        abstract = True

    @property
    def final_output_path(self) -> Path:
        """Return the final output path for this cut render."""
        self.game.ensure_video()
        video = self.game.video_proxy
        video_file, _ = VideoFile.objects.get_or_create(
            video=video,
            quality=self.preset,
            format=VideoFile.Format.MP4,
        )
        final_path = video_file.expected_path()
        video_file.set_real_path(final_path)
        return final_path

    def get_source_files(self) -> list[Path]:
        """Return the source files to consider for encoding.

        If an archive video is set and exists, it will be used as the only source file.
        """
        return self.game.get_source_files()

    def build_command(
        self,
        chapter_metadata_tmp_path: Path | None = None,
        output_file: Path | None = None,
    ) -> list[str]:
        """Build the ffmpeg command for proxy renders.

        concatenate the source files
        and encode them with the selected preset.

        Args:
            chapter_metadata_tmp_path: Path to the temporary metadata file, if any.
            output_file: Path to the output file, if any.

        Returns:
            list of parameters arg for ffmpeg
        """
        _ = chapter_metadata_tmp_path

        out_file = output_file or self.final_output_path
        out_file.parent.mkdir(parents=True, exist_ok=True)

        source_files = self.get_source_files()
        nb_files = len(source_files)

        preset_args = self._preset_args(source_files)

        filter_complex = FilterComplexBuilder(nb_files)
        filter_complex.filter_concat(filter_complex.inputs_v, filter_complex.inputs_a)

        scale = preset_args.get("scale")
        if scale:
            w, h = scale
            filter_complex.filter_scale(w, h)

        cmd = ffmpeg_command_builder(
            filter_complex=filter_complex,
            input_files=source_files,
            output_file=out_file,
            preset_args=preset_args,
            decode_cuda_available=self._can_use_cuda_for_decode(source_files),
            encode_cuda_available=self._can_use_cuda_for_encode(),
        )

        self.command = " ".join(cmd)
        return cmd


class RenderQueueItemProxy(RenderQueueItemGameRender):
    """Queue item for proxy renders."""

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_proxy"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches proxy renders."""
        self.job_type = self.JobType.GAME_PROXY
        super().save(*args, **kwargs)

    @property
    def final_output_path(self) -> Path:
        """Return the final output path for this proxy render."""
        self.game.ensure_video()
        video = self.game.video_proxy
        video_file, _ = VideoFile.objects.get_or_create(
            video=video,
            quality=self.preset,
            format=VideoFile.Format.MP4,
        )
        final_path = video_file.expected_path()
        video_file.set_real_path(final_path)
        return final_path


class RenderQueueItemArchive(RenderQueueItemGameRender):
    """Queue item for archive renders."""

    DEFAULT_PRESET = "archive"

    PRESET_ARGS_GPU: ClassVar[dict[str, dict[str, list[str]]]] = {}

    PRESET_ARGS_CPU: ClassVar[dict[str, dict[str, list[str]]]] = {
        "archive": {
            "video": ["-c:v", "libsvtav1", "-crf", "28", "-preset", "6"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
    }

    #: Archives are normalised to 1080p. A taller source is downscaled and
    #: encoded at :attr:`DOWNSCALE_CRF`; measured on GoPro 4K60 rushes, that
    #: lands at ~18% of the source size for VMAF ~91 against the 1080p
    #: reference. Keeping 4K instead costs 2 to 4 times as much for detail
    #: the cut renders never use.
    #:
    #: A source at or below this height is left alone and keeps the preset's
    #: own CRF: scaling it up would inflate the archive to no benefit.
    MAX_SOURCE_HEIGHT = 1080
    DOWNSCALE_CRF = "34"

    def _preset_args(
        self, source_files: list[Path] | None = None
    ) -> dict[str, list[str]]:
        """Return CPU-only ffmpeg args for archive presets.

        Sources taller than :attr:`MAX_SOURCE_HEIGHT` are downscaled to it and
        re-encoded at :attr:`DOWNSCALE_CRF`.
        """
        preset_args = self.PRESET_ARGS_CPU.get(
            self.preset,
            self.PRESET_ARGS_CPU[self.DEFAULT_PRESET],
        )

        if not self._sources_need_downscale(source_files):
            return preset_args

        return {
            **preset_args,
            # Height-driven so a non-16:9 source is capped the same way.
            "scale": ["-2", str(self.MAX_SOURCE_HEIGHT)],
            "video": self._with_crf(preset_args["video"], self.DOWNSCALE_CRF),
        }

    @classmethod
    def _sources_need_downscale(cls, source_files: list[Path] | None) -> bool:
        """Tell whether the sources are taller than the archive target.

        The tallest source decides: the inputs are concatenated into a single
        output, so the archive is encoded at that resolution anyway. An
        unreadable source is treated as not needing a downscale, which keeps
        the preset's own args rather than guessing.
        """
        if not source_files:
            return False

        heights = [
            height
            for height in (
                cls._source_video_height(source_file) for source_file in source_files
            )
            if height is not None
        ]

        return bool(heights) and max(heights) > cls.MAX_SOURCE_HEIGHT

    @staticmethod
    def _with_crf(video_args: list[str], crf: str) -> list[str]:
        """Return `video_args` with its `-crf` value replaced by `crf`."""
        if "-crf" not in video_args:
            return video_args

        args = list(video_args)
        args[args.index("-crf") + 1] = crf
        return args

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_archive"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Set archive default preset when no preset is explicitly provided."""
        if not args and "preset" not in kwargs:
            kwargs["preset"] = self.DEFAULT_PRESET
        super().__init__(*args, **kwargs)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches archive renders."""
        self.job_type = self.JobType.GAME_ARCHIVE

        super().save(*args, **kwargs)

    def get_source_files(self) -> list[Path]:
        """Return the source files to consider for encoding.

        If an archive video is set and exists, it will be used as the only source file.
        """
        return self.game.get_source_files(force_rush=True)

    @property
    def final_output_path(self) -> Path:
        """Return the final output path for this archive render."""
        self.game.ensure_archive_video()
        video = self.game.ensure_archive_video()
        video_file, _ = VideoFile.objects.get_or_create(
            video=video,
            quality=self.preset,
            format=VideoFile.Format.MP4,
        )
        final_path = video_file.expected_path()
        video_file.set_real_path(final_path)
        return final_path
