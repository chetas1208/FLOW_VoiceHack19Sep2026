import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.flow.efficiency import EfficiencyEngine
from services.flow.models_registry import ModelManager
from services.flow.vision.schema import VisionActivityType, VisionObservation


def vision(activity, kind, relevance, progress=0.0, offset=0):
    return VisionObservation(datetime.now(timezone.utc) + timedelta(seconds=offset), "app", "window", activity, kind,
                             relevance=relevance, progress_signal=progress, confidence=.9)


def test_model_manager_reports_missing_models_without_downloading():
    with tempfile.TemporaryDirectory() as directory:
        statuses = ModelManager(Path(directory)).status()
        assert {item["key"] for item in statuses} == {"vision", "voice"}
        assert all(item["status"] == "missing" for item in statuses)


def test_efficiency_engine_does_not_equate_apps_with_productivity():
    engine = EfficiencyEngine("Learn transformer attention")
    aligned = engine.update(vision("Watching a transformer attention lecture", VisionActivityType.MEDIA, .9, .4))
    unrelated = engine.update(vision("Watching unrelated entertainment", VisionActivityType.MEDIA, .05, 0.0, 60))
    assert aligned.category.value == "supporting_task"
    assert unrelated.category.value == "distraction"


def test_efficiency_engine_flags_supported_blocker_evidence():
    engine = EfficiencyEngine("Fix database connection failure")
    item = engine.update(VisionObservation(datetime.now(timezone.utc), "Terminal", None,
        "Repeated connection refused error", VisionActivityType.DEBUGGING, relevance=.9,
        progress_signal=.1, confidence=.95, possible_blocker="connection refused repeated"))
    report = engine.report()
    assert item.category.value == "core_task"
    assert report["blocker"] == "connection refused repeated"
    assert report["recommendation"] == "flag_possible_blocker"
