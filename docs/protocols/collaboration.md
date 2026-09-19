# HACP, A2A and OTLP collaboration specification

HACP coordinates bilateral coding-agent contracts, negotiation, artifact submission, counterparty verification and revision acceptance. This repository defines *planning manifests*, not HACP wire messages; validate the actual installed HACP implementation before translating them. Preserve two-peer sessions and use master task registry for global coordination. HACP COMPLETED does not imply CI success.

A2A is optional interoperability for remote agent discovery/task delivery; implement a schema-validating, authenticated adapter. Do not equate A2A task states with HACP contract states. A2A is not required for Wave 0.

OTLP carries traces, metrics and logs, never task authorization or collaboration control. Emit spans for session creation, task acceptance, artifact verification, integration tests, and merge, without sensitive payloads. Correlate qa.run.id with relevant trace references.

## Handoff rules
Task proposer defines scope, inputs, acceptance, file ownership and dependency. Counterparty accepts exact revision. Owner submits commit SHA, artifact hash and test evidence. Counterparty independently verifies and accepts or requests revision. Master merges only after independent CI and security gates. Unresolved conflicts go to technical lead/human. Agent cannot unilaterally approve its own submission.

## Protocol failure handling
Duplicate delivery: dedupe message/task IDs. Stale revision: reject. Disconnect: persist state and resume safely. Conflicting submissions: retain history, reject ambiguous acceptance. Auth failure: deny and audit. Secrets must remain outside model context. Exact supported commands and crypto properties require inspection of deployed HACP Secure version.
