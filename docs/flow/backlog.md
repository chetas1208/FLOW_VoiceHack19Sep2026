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
- Qwen3-VL intelligence boundary, strict observation schema, and legacy
  Moondream compatibility adapter.
- Evidence-grounded `flow recommend`, `flow ask`, explicit `flow task add`,
  `flow setup`, privacy configuration, permissions, and local API aliases.
- Authenticated configured-daemon IPC with local session runtime startup on
  capable macOS hosts.
- Kubernetes API deployment design and local CI script.

## Next implementation order

1. Verify ScreenCaptureKit, active-window metadata, display selection, and
   ephemeral frame delivery on a real macOS host.
2. Verify Qwen3-VL inference and Kokoro synthesis/playback on supported hardware.
3. Add daemon restart checkpoint/recovery and observer/helper bounded backoff.
4. Complete paired remote transport and client revocation against the local daemon.
5. Add conservative OCR/region redaction providers and opt-in screenshot TTLs.

Items in the next section require macOS, installed model runtimes, or external
remote transport and are not claimed as complete by Linux unit tests.
