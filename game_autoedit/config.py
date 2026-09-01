"""Central configuration for the auto-edit pipeline.

Every path and knob the pipeline needs lives here so a run can be reproduced
from a single object, and so the cache layout stays stable across commands.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# The archives are concatenated GoPro rushes: real NTSC rate, never 60.
DEFAULT_FPS = 60000 / 1001

# Mono 16 kHz is what every pretrained audio encoder expects, and it is plenty
# for whistles and crowd noise. It also keeps the cache at ~32 kB/s.
SAMPLE_RATE = 16000

# The quality of the VideoFile the pipeline reads audio from. Archives are the
# only rendition rendered with a consistent audio profile.
AUDIO_QUALITY = "archive"

# Which cut wins when a game carries several: OTIO and MAN come straight from a
# real edit, VID is reconstructed by audio alignment and is the noisy one.
CUT_TYPE_PRIORITY: tuple[str, ...] = ("OTIO", "MAN", "VID", "XML", "ML", "X")

_ENV_CACHE = "GAME_AUTOEDIT_CACHE"
_DEFAULT_CACHE = Path("/mnt/video/juggerData/cache_game_edit")


def default_cache_root() -> Path:
    """Return the cache root, overridable with ``GAME_AUTOEDIT_CACHE``."""
    return Path(os.environ.get(_ENV_CACHE, _DEFAULT_CACHE))


@dataclass(frozen=True)
class Paths:
    """Where the pipeline writes everything it can rebuild.

    The whole tree is disposable: any subdirectory can be wiped and rebuilt
    from the database and the archives.
    """

    root: Path = field(default_factory=default_cache_root)

    @property
    def audio(self) -> Path:
        """16 kHz mono WAV extracted from the archives, one file per game."""
        return self.root / "audio"

    @property
    def features(self) -> Path:
        """Precomputed features, one subdirectory per feature spec."""
        return self.root / "features"

    def embeddings(self, encoder: str) -> Path:
        """Frozen-encoder embeddings, one subdirectory per encoder."""
        return self.features / encoder

    @property
    def runs(self) -> Path:
        """Training runs: checkpoints, metrics, configs."""
        return self.root / "runs"

    @property
    def predictions(self) -> Path:
        """Predicted cut files and probability curves."""
        return self.root / "predictions"

    def all_dirs(self) -> list[Path]:
        """Return every managed directory, in creation order."""
        return [self.root, self.audio, self.features, self.runs, self.predictions]

    def ensure(self) -> None:
        """Create the cache tree if it is not there yet."""
        for path in self.all_dirs():
            path.mkdir(parents=True, exist_ok=True)

    def audio_path(self, game_id: int) -> Path:
        """Return the cached audio path for a game."""
        return self.audio / f"game_{game_id}.wav"
