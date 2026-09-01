"""Core models package.

Django registers an app's models by importing ``<app>.models``. With the models
split across this package, that import has to pull them in explicitly —
otherwise nothing registers them at app-loading time and they only arrive as a
side effect of something else importing them, in practice ``core/admin.py``
through the admin's autodiscovery. Any entry point that does not go through the
admin then meets half-built relations, with errors like "Related model
'core.Tournament' cannot be resolved" or "Cannot find 'cuts' on Game object".

Alphabetical order is enough here: no two of these modules import each other
at module level, so Python resolves the chain on its own.
"""

from __future__ import annotations

from core.models.cut import Cut
from core.models.game import Game
from core.models.media import TmpImage, VideoMetadata, YTVideo
from core.models.render_queue.base import RenderQueueItemBase
from core.models.render_queue.ffmpeg import (
    RenderQueueItemArchive,
    RenderQueueItemCut,
    RenderQueueItemFFMPEG,
    RenderQueueItemProxy,
)
from core.models.render_queue.gen_cut import RenderQueueItemGenCut
from core.models.tournament import Team, Tournament
from core.models.video import Video, VideoFile

__all__ = [
    "Cut",
    "Game",
    "RenderQueueItemArchive",
    "RenderQueueItemBase",
    "RenderQueueItemCut",
    "RenderQueueItemFFMPEG",
    "RenderQueueItemGenCut",
    "RenderQueueItemProxy",
    "Team",
    "TmpImage",
    "Tournament",
    "Video",
    "VideoFile",
    "VideoMetadata",
    "YTVideo",
]
