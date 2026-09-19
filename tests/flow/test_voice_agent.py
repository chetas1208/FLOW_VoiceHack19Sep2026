import asyncio

from services.flow.efficiency import EfficiencyEngine
from services.flow.voice import MockVoiceEngine
from services.flow.voice.policy import InterventionPolicy, InterventionPolicyConfig
from services.flow.voice_agent import VoiceAgent
from services.flow.vision.schema import VisionActivityType, VisionObservation
from datetime import datetime, timezone


def test_voice_agent_speaks_once_then_applies_cooldown():
    async def run():
        engine = EfficiencyEngine("Fix auth")
        engine.update(VisionObservation(datetime.now(timezone.utc), "browser", None, "unrelated feed",
                                        VisionActivityType.BROWSING, relevance=.1, confidence=.95))
        voice = MockVoiceEngine()
        agent = VoiceAgent(voice, InterventionPolicy(InterventionPolicyConfig(.5, 1, 600)))
        assert await agent.consider(engine.state, 120)
        assert not await agent.consider(engine.state, 120)
        assert len(voice.messages) == 1
    asyncio.run(run())
