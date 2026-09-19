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
