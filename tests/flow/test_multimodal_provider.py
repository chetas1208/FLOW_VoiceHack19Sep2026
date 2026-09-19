import asyncio
import json

import httpx

from services.flow.activity import ANALYZER_SYSTEM_PROMPT, OpenAICompatibleVisionAnalyzer
from services.flow.observer.frame import CapturedFrame


def test_remote_analyzer_validates_structured_provider_response_and_prompt_boundary():
    captured = {}
    def handler(request):
        captured["body"] = json.loads(request.content)
        result = {"activity_summary": "editing tests", "category": "core_task",
                  "goal_alignment": .9, "progress_signal": .5, "confidence": .8, "evidence": ["editor visible"]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}}]})
    async def run():
        analyzer = OpenAICompatibleVisionAnalyzer("https://vision.test/v1/chat/completions", "secret", transport=httpx.MockTransport(handler))
        result = await analyzer.analyze("Fix auth", CapturedFrame(__import__("datetime").datetime.now(__import__("datetime").timezone.utc), image_bytes=b"png"), {}, [])
        assert result.goal_alignment == .9
    asyncio.run(run())
    assert "UNTRUSTED DATA" in captured["body"]["messages"][0]["content"]
    assert '"secret"' not in json.dumps(captured["body"])
