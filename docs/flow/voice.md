# Voice

Voice is an optional pipeline: drift policy -> intervention -> `VoiceEngine`.
`MockVoiceEngine` is used in tests. `KokoroVoiceEngine` loads Kokoro lazily from
the optional `flow-agent[voice]` extra, so model weights are never bundled in
the wheel. Voice errors are surfaced to the caller and must not terminate a
session. Audio playback and model checksum/cache management are next work.
