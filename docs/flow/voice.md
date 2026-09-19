# Voice

Voice is an optional pipeline: efficiency policy -> `VoiceAgent` ->
`KokoroVoiceEngine`. `MockVoiceEngine` is used in tests. Kokoro loads lazily
from the optional `flow-agent[voice]` extra, while its artifact is managed by
`flow models install voice`; model weights are never bundled in the wheel.
Voice errors are surfaced to the caller and must not terminate a session.
Audio playback requires the optional `sounddevice` runtime and a working local
audio device; this Linux environment has not verified either.
