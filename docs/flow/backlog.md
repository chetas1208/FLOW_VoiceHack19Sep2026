# FLOW backlog status

## Completed in this backlog pass

- Installable `flow` executable and local installer.
- Credential/device/PKCE foundations and local auth endpoints.
- Unix-domain daemon IPC.
- Observer protocol with replayable mock implementation.
- Adaptive sampler and frame-change boundary.
- Privacy exclusions and semantic text redaction.
- Capture-to-observation pipeline with malformed-analysis fallback to `unknown`.
- Idle/away state model.
- Bounded offline queue with retry, backoff, and post-success acknowledgement.
- Versioned cloud client with client metadata and idempotency keys.
- Intervention confidence threshold and cooldown policy.
- Optional Kokoro adapter and voice CLI commands.
- Portable daemon session lifecycle commands (`session.start`, `status`, `pause`,
  `resume`, `stop`, and `session.list`) with explicit unavailable-capability status.
- `flow doctor` plus persisted voice enable/mute controls.
- Kubernetes API deployment design and local CI script.

## Next implementation order

1. macOS native bridge: ScreenCaptureKit permission state, active-window metadata,
   display selection, and actual ephemeral frame delivery.
2. Local daemon session runtime: observer worker ownership, restart recovery,
   sampler scheduling, local queue flush, and Ctrl-C detach behavior. The daemon
   lifecycle control surface is complete; worker ownership remains open.
3. Local redaction implementation using conservative OCR/region providers and
   explicit screenshot TTL handling for opt-in debugging.
4. Kokoro model cache/checksum management and platform audio playback.
5. Remote auth code exchange/refresh rotation and cloud WebSocket synchronization.
6. Durable PostgreSQL/Redis worker deployment, migrations, network policies,
   secrets integration, and production Kubernetes validation.

Items in the next section require macOS or external production infrastructure
and are not claimed as complete by Linux unit tests.
