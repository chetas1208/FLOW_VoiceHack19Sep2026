from __future__ import annotations

from io import BytesIO
from datetime import datetime, timezone

from services.flow.intelligence import QwenVLIntelligenceEngine
from services.flow.observer import CapturedFrame


def test_qwen_adapter_normalizes_structured_output_without_model_runtime():
    def backend(image, prompt):
        assert image.mode == "RGB"
        assert "untrusted" in prompt.lower()
        return '{"activity":"Running authentication tests","activity_type":"testing",' \
               '"task_phase":"validation","goal_relevance":0.9,"progress_signal":0.8,' \
               '"blocker_signal":null,"completion_signal":false,"task_boundary":false,' \
               '"confidence":0.88,"evidence":["pytest output"]}'

    engine = QwenVLIntelligenceEngine(backend=backend)
    from PIL import Image
    image = Image.new("RGB", (2, 2), "white")
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    frame = CapturedFrame(datetime.now(timezone.utc), application="Terminal", image_bytes=encoded.getvalue())
    result = __import__("asyncio").run(engine.observe("Fix authentication", frame, {}, []))
    assert result.observation.activity_type.value == "testing"
    assert result.observation.relevance == .9


def test_qwen_adapter_status_is_explicit_when_weights_are_missing(tmp_path):
    engine = QwenVLIntelligenceEngine(tmp_path)
    assert engine.status() == "missing"


def test_model_marker_alone_or_tampered_payload_is_not_ready(tmp_path):
    import json
    from services.flow.models_registry import ModelManager, MODEL_REGISTRY

    root = tmp_path / "vision"
    root.mkdir()
    (root / "flow-model.json").write_text(json.dumps({"source": MODEL_REGISTRY["vision"].source,
                                                        "sha256": "wrong"}))
    assert ModelManager(tmp_path).status("vision")[0]["status"] == "corrupt"


def test_model_manager_allows_downloads_but_blocks_oversized_runtime(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    from services.flow.models_registry import ModelManager

    def snapshot_download(**kwargs):
        Path(kwargs["local_dir"], "weights.bin").write_bytes(b"model weights")

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))

    manager = ModelManager(tmp_path)
    installed = manager.install("vision")

    assert installed[0]["status"] == "ready"
    assert installed[0]["within_runtime_memory_budget"] is False

    try:
        manager.assert_runtime_memory_budget(manager._spec("vision"))
    except RuntimeError as exc:
        assert "runtime CPU memory limit is 500 MB" in str(exc)
    else:
        raise AssertionError("oversized model was allowed to load")
