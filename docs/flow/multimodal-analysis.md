# Multimodal analysis

`OpenAICompatibleVisionAnalyzer` is a configured real provider path. It sends a
single ephemeral in-memory image, goal, active context, and compact recent
history to an OpenAI-compatible chat endpoint, with a system boundary stating
that screen text is untrusted evidence. Responses are strictly validated and
malformed output becomes an unknown observation through the pipeline fallback.
Without `FLOW_VISION_API_URL` and `FLOW_VISION_API_KEY`, the provider is
explicitly unavailable.
