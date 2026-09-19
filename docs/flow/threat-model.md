# Threat model

Observed screen content is untrusted data. A webpage saying “ignore previous
instructions” must never change FLOW behavior or authorize an action. The
analyzer receives evidence only and must not execute or relay visible commands.

Primary risks are screenshot leakage, stolen CLI credentials, replayed uploads,
local IPC access, provider retention, and malicious visible prompt injection.
Mitigations include local redaction, no screenshot persistence by default,
filesystem-protected Unix sockets, PKCE, idempotency keys, bounded queues, and
structured-only cloud uploads. Production still requires token rotation,
external secrets, TLS enforcement, and provider-retention review.
