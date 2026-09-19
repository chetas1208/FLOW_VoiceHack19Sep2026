# FLOW architecture v2

Implemented now: local Python package, durable session domain, Unix-socket
daemon protocol, observer interfaces, mock replay observer, adaptive sampler,
privacy exclusions/text redaction, validated analyzer contract, offline event
queue, optional Keychain credentials, PKCE request construction, local CLI,
and an optional Kokoro adapter.

The device plane remains local. It owns screen permission, capture, redaction,
semantic analysis policy, bounded buffering, and optional audio. The cloud
boundary receives structured observations and is represented by the versioned
client/API seam. The web plane is not implemented.

The checked-in Kubernetes files are deployment design artifacts, not a claim of
a live cluster or production image. They deliberately scale API pods, not
screen capture. PostgreSQL, Redis, durable workers, migrations, and external
secret management remain production targets.
