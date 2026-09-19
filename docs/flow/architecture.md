# FLOW architecture v2

Implemented now: local Python package, durable session domain, Unix-socket
daemon protocol, observer interfaces, mock replay observer, adaptive sampler,
privacy exclusions/text redaction, validated analyzer contract, offline event
queue, optional Keychain credentials, PKCE request construction, local CLI,
and an optional Kokoro adapter.

The device plane remains local and authoritative. It owns screen permission,
capture, redaction, Qwen semantic analysis, SQLite state, recommendations,
delegated execution, and optional audio. Remote access is a transport concern;
there is no hosted FLOW session or model backend.

The checked-in Kubernetes files are historical design artifacts only and are
not part of the supported runtime. FLOW does not require PostgreSQL, Redis,
cloud workers, or external secret management.
