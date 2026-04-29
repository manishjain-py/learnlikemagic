"""Unit tests for the topic-pipeline DAG.

Phase 1 acceptance: the DAG is acyclic, every stage has a launch + status
callable, and `topo_sort()` matches the order the legacy `PIPELINE_LAYERS`
constant produced.
"""
from __future__ import annotations

import pytest

from book_ingestion_v2.dag.topic_pipeline_dag import DAG, STAGES
from book_ingestion_v2.dag.types import (
    Stage,
    StageScope,
    TopicPipelineDAG,
)


# Frozen image of the topic pipeline order. The two Baatcheet audio stages
# were promoted out of the manual admin button into the DAG (sibling tree
# under `baatcheet_dialogue`), so the legacy run sequence is preserved
# verbatim for the variant A path while baatcheet now has its own
# review→synthesis subtree.
_LEGACY_PIPELINE_ORDER: list[str] = [
    "explanations",
    "baatcheet_dialogue",
    "baatcheet_visuals",
    "baatcheet_audio_review",
    "baatcheet_audio_synthesis",
    "visuals",
    "check_ins",
    "practice_bank",
    "audio_review",
    "audio_synthesis",
]


class TestTopicPipelineDAGStructure:
    def test_topo_sort_matches_legacy_pipeline_layers_order(self):
        ordered = [s.id for s in DAG.topo_sort()]
        assert ordered == _LEGACY_PIPELINE_ORDER

    def test_validate_acyclic_passes(self):
        DAG.validate_acyclic()

    def test_every_stage_has_callable_launch_and_status(self):
        for stage in DAG.stages:
            assert callable(stage.launch), f"{stage.id} launch is not callable"
            assert callable(stage.status_check), (
                f"{stage.id} status_check is not callable"
            )

    def test_every_dependency_references_a_known_stage(self):
        ids = {s.id for s in DAG.stages}
        for stage in DAG.stages:
            for dep in stage.depends_on:
                assert dep in ids, (
                    f"{stage.id} depends on unknown stage {dep!r}"
                )

    def test_all_topic_scope(self):
        for stage in DAG.stages:
            assert stage.scope == StageScope.TOPIC, (
                f"{stage.id} scope must be TOPIC for v1"
            )

    def test_no_duplicate_stage_ids(self):
        ids = [s.id for s in DAG.stages]
        assert len(ids) == len(set(ids))

    def test_get_returns_stage_by_id(self):
        s = DAG.get("explanations")
        assert s.id == "explanations"

    def test_to_json_includes_every_stage(self):
        payload = DAG.to_json()
        assert {s["id"] for s in payload["stages"]} == {s.id for s in DAG.stages}
        for entry in payload["stages"]:
            assert entry["scope"] == "topic"
            assert "depends_on" in entry
            assert "label" in entry


class TestStageDependencies:
    """Locks the dep edges that auto-cascade (Phase 3) will rely on."""

    def test_explanations_is_root(self):
        assert DAG.get("explanations").depends_on == ()

    def test_baatcheet_visuals_depends_on_dialogue(self):
        assert "baatcheet_dialogue" in DAG.get("baatcheet_visuals").depends_on

    def test_audio_synthesis_depends_on_review_only(self):
        # `baatcheet_dialogue` is a soft join, not a hard dep — see the
        # docstring in stages/audio_synthesis.py. Modelling it as a hard
        # dep would break Phase 3 cascade staleness (a dialogue regen
        # would mark synthesis fully stale even though variant-A MP3s are
        # unchanged).
        assert DAG.get("audio_synthesis").depends_on == ("audio_review",)

    def test_audio_synthesis_not_a_descendant_of_dialogue(self):
        # If this fails, the soft-vs-hard dep distinction has been lost.
        assert "audio_synthesis" not in DAG.descendants("baatcheet_dialogue")

    def test_explanations_descendants_cover_every_other_stage(self):
        descendants = DAG.descendants("explanations")
        all_ids = {s.id for s in DAG.stages} - {"explanations"}
        assert descendants == all_ids


class TestTopologicalProperties:
    """Generic DAG invariants — apply to any DAG instance, not just ours."""

    def test_topo_sort_detects_cycle(self):
        a = Stage(
            id="a",
            scope=StageScope.TOPIC,
            label="A",
            depends_on=("b",),
            launch=lambda *args, **kw: "",
            status_check=lambda ctx: None,
        )
        b = Stage(
            id="b",
            scope=StageScope.TOPIC,
            label="B",
            depends_on=("a",),
            launch=lambda *args, **kw: "",
            status_check=lambda ctx: None,
        )
        with pytest.raises(ValueError, match="cycle"):
            TopicPipelineDAG([a, b]).validate_acyclic()

    def test_constructor_rejects_duplicate_ids(self):
        s = Stage(
            id="x",
            scope=StageScope.TOPIC,
            label="X",
            depends_on=(),
            launch=lambda *args, **kw: "",
            status_check=lambda ctx: None,
        )
        with pytest.raises(ValueError, match="Duplicate"):
            TopicPipelineDAG([s, s])

    def test_constructor_rejects_unknown_dep(self):
        s = Stage(
            id="x",
            scope=StageScope.TOPIC,
            label="X",
            depends_on=("nope",),
            launch=lambda *args, **kw: "",
            status_check=lambda ctx: None,
        )
        with pytest.raises(ValueError, match="unknown stage"):
            TopicPipelineDAG([s])

    def test_ready_nodes_excludes_done_and_running(self):
        a = Stage(
            id="a",
            scope=StageScope.TOPIC,
            label="A",
            depends_on=(),
            launch=lambda *args, **kw: "",
            status_check=lambda ctx: None,
        )
        b = Stage(
            id="b",
            scope=StageScope.TOPIC,
            label="B",
            depends_on=("a",),
            launch=lambda *args, **kw: "",
            status_check=lambda ctx: None,
        )
        dag = TopicPipelineDAG([a, b])
        # a done → b becomes ready; a stays excluded (already done)
        ready = dag.ready_nodes({"a": "done", "b": "ready"})
        assert [s.id for s in ready] == ["b"]
        # a running → nothing ready
        ready = dag.ready_nodes({"a": "running"})
        assert ready == []


class TestLauncherMap:
    def test_launcher_map_matches_dag(self):
        from book_ingestion_v2.dag.launcher_map import LAUNCHER_BY_STAGE

        assert set(LAUNCHER_BY_STAGE.keys()) == {s.id for s in DAG.stages}
        for sid, fn in LAUNCHER_BY_STAGE.items():
            assert fn is DAG.get(sid).launch

    def test_legacy_import_path_still_works(self):
        # Back-compat: `from ...stage_launchers import LAUNCHER_BY_STAGE`
        # is the documented path. The PEP 562 shim in stage_launchers.py
        # forwards to dag.launcher_map.LAUNCHER_BY_STAGE — same dict.
        from book_ingestion_v2.dag.launcher_map import (
            LAUNCHER_BY_STAGE as canonical,
        )
        from book_ingestion_v2.services.stage_launchers import (
            LAUNCHER_BY_STAGE as legacy,
        )
        assert legacy is canonical


class TestStageDataclass:
    def test_depends_on_coerced_to_tuple(self):
        # Latent-bug guard: passing a list silently survived before the
        # coercion was added.
        s = Stage(
            id="x",
            scope=StageScope.TOPIC,
            label="X",
            depends_on=["a", "b"],  # type: ignore[arg-type]
            launch=lambda *args, **kw: "",
            status_check=lambda ctx: None,
        )
        assert s.depends_on == ("a", "b")
        assert isinstance(s.depends_on, tuple)
