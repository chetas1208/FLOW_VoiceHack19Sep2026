# Cloud boundary

`CloudClient` owns HTTP details, client-version metadata, bearer auth, retries'
future seam, and observation idempotency keys. It uploads structured semantic
observations rather than raw frames. `OfflineQueue` is bounded and preserves
semantic events while dropping old entries at capacity; raw images are never
queued.

The local SQLite service remains usable without the cloud. Cloud outage must
not stop local session capture or fabricate classifications.
