"""Tests for core.models.render_queue.ml_cut.RenderQueueItemMlCut."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from core.models.cut import Cut
from core.models.render_queue.base import RenderQueueItemBase
from core.models.render_queue.ml_cut import RenderQueueItemMlCut


@pytest.fixture()
def ml_cut(game):
    """An empty ML cut, as the endpoint creates it before queueing."""
    return Cut.objects.create(game=game, name="Proposition ML", type_cut="ML")


@pytest.fixture()
def proposal_writer():
    """Return a fake `_run_subprocess` that writes what the model would."""

    def _make(game_id: int, *, points: int = 2, curves: bool = True):
        def _fake(command: list[str]) -> None:
            out_dir = Path(command[command.index("--out") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "points": [
                    {"in": 100 * i, "out": 100 * i + 50, "point": "nopoint"}
                    for i in range(points)
                ],
                "overlays": [],
                "comment": {"stats": {"kept": 120.0}, "review": [{"at": 12.0}]},
            }
            (out_dir / f"game_{game_id}_cut.json").write_text(json.dumps(payload))
            if curves:
                np.savez_compressed(
                    out_dir / f"game_{game_id}_curves.npz",
                    **{name: np.zeros(4, dtype=np.float32) for name in ("in", "out")},
                )

        return _fake

    return _make


class TestCommand:
    def test_runs_the_pipeline_in_the_project_interpreter(self, ml_cut):
        item = RenderQueueItemMlCut.objects.create(cut=ml_cut, run_name="a_run")

        command = item.build_command(Path("/tmp/out"))

        assert command[:4] == [sys.executable, "-m", "game_autoedit", "propose"]
        assert command[command.index("--game") + 1] == str(ml_cut.game_id)
        assert command[command.index("--cut") + 1] == str(ml_cut.pk)
        assert command[command.index("--run") + 1] == "a_run"
        assert command[command.index("--out") + 1] == "/tmp/out"

    def test_falls_back_to_the_configured_run(self, ml_cut, settings):
        settings.AUTOEDIT_RUN = "configured_run"
        item = RenderQueueItemMlCut.objects.create(cut=ml_cut)

        assert item.effective_run == "configured_run"
        assert (
            item.build_command(Path("/tmp"))[
                item.build_command(Path("/tmp")).index("--run") + 1
            ]
            == "configured_run"
        )

    def test_snapping_is_passed_explicitly(self, ml_cut):
        item = RenderQueueItemMlCut.objects.create(cut=ml_cut, snap=False)

        assert "--no-snap" in item.build_command(Path("/tmp"))
        assert "--snap" not in item.build_command(Path("/tmp"))


class TestExecute:
    def test_attaches_the_proposed_cut_and_its_curves(
        self, ml_cut, proposal_writer, monkeypatch
    ):
        item = RenderQueueItemMlCut.objects.create(cut=ml_cut)
        monkeypatch.setattr(
            RenderQueueItemMlCut,
            "_run_subprocess",
            lambda self, command: proposal_writer(ml_cut.game_id)(command),
        )

        item.run()

        ml_cut.refresh_from_db()
        assert len(ml_cut.get_json()["points"]) == 2
        assert ml_cut.has_curves
        assert ml_cut.curves_file.name.endswith(".npz")
        item.refresh_from_db()
        assert "2 segments" in item.report
        assert "1 point(s) à vérifier" in item.report

    def test_a_cut_without_curves_still_lands(
        self, ml_cut, proposal_writer, monkeypatch
    ):
        item = RenderQueueItemMlCut.objects.create(cut=ml_cut)
        monkeypatch.setattr(
            RenderQueueItemMlCut,
            "_run_subprocess",
            lambda self, command: proposal_writer(ml_cut.game_id, curves=False)(
                command
            ),
        )

        item.run()

        ml_cut.refresh_from_db()
        assert len(ml_cut.get_json()["points"]) == 2
        assert not ml_cut.has_curves

    def test_a_silent_failure_is_reported(self, ml_cut, monkeypatch):
        item = RenderQueueItemMlCut.objects.create(cut=ml_cut)
        monkeypatch.setattr(
            RenderQueueItemMlCut, "_run_subprocess", lambda self, command: None
        )

        with pytest.raises(RuntimeError, match="aucun cut produit"):
            item.run()

    def test_the_working_directory_is_cleaned_up(
        self, ml_cut, proposal_writer, monkeypatch, settings, tmp_path
    ):
        settings.BASE_DIR = tmp_path
        item = RenderQueueItemMlCut.objects.create(cut=ml_cut)
        monkeypatch.setattr(
            RenderQueueItemMlCut,
            "_run_subprocess",
            lambda self, command: proposal_writer(ml_cut.game_id)(command),
        )

        item.run()

        assert not list((tmp_path / "tmp").glob("ml_cut_*"))


class TestResolution:
    def test_the_base_row_resolves_back_to_the_concrete_item(self, ml_cut):
        item = RenderQueueItemMlCut.objects.create(cut=ml_cut)

        base_item = RenderQueueItemBase.objects.get(pk=item.pk)

        assert base_item.job_type == RenderQueueItemBase.JobType.ML_CUT
        assert base_item.cut == ml_cut
        assert base_item.game == ml_cut.game
        assert isinstance(base_item.concrete(), RenderQueueItemMlCut)
