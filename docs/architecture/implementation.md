# Implementation blueprint and integration contracts

## Stack decisions for MVP
Python 3.12 services and runners, TypeScript/React dashboard later, PostgreSQL for metadata and initial nodes/edges, S3-compatible immutable artifact store, Playwright browser worker, OpenTelemetry SDK and Collector with OTLP, trace backend, durable queue with worker leases. Graph database optional after measured need. Container isolation and network policies mandatory before untrusted third-party apps.

## Public API draft (not implemented)
- POST /v1/projects: register tenant-scoped project, repo and allowed environments.
- POST /v1/projects/{id}/discover: request static and runtime discovery.
- GET /v1/projects/{id}/capabilities: evidence-backed feature map.
- POST /v1/scenarios: validate scenario against approved requirements and policy.
- POST /v1/runs: idempotency key + scenario/version/environment → queued run.
- GET /v1/runs/{id}: status, verdict, trace references and evidence references.
- GET /v1/findings/{id}: assertions, reproduction recipe, affected components.
- POST /v1/changes: register code/prompt/model/config change for impact analysis.
All routes require tenant identity, RBAC, request IDs, input validation and audit events. No API implementation in Week 1.

## Data/storage
PostgreSQL: tenant/project/version/requirement/scenario/run/verdict/finding metadata, task registry, graph nodes and edges. Object store: hash-addressed state snapshots, logs and artifacts with tenant ACLs and retention. OTLP collector sends traces to a trace backend; trace ID and service identity referenced by `trace-reference` contract. Do not store telemetry in HACP messages.

## Run sequence
Authorize request → pin immutable app version and scenario → provision isolated worker/fixtures → inject scoped credentials → execute → emit OTLP → capture state and evidence hashes → verify assertions in separate service → store verdict and graph edges → clean up. On failure: preserve evidence, classify infra vs application, revoke credentials and retry only if safe.

## OTLP specifics
Use OTLP/gRPC or OTLP/HTTP supported by SDK and Collector; configurable endpoint and TLS. W3C traceparent across HTTP; span links for async fan-out. Resource attrs include service.name, deployment.environment.name and tenant-safe correlation; custom qa.run.id, qa.scenario.id, qa.attempt.id versioned in our SDK. Never use trace ID as tenant authorization. Redact prompt/tool content by default; bounded attributes and retention. Sampling must preserve evidence-required spans or verdict is inconclusive.

## Graph & retrieval
Parser-derived symbols/routes/schema + approved requirements + runtime observed spans. Store edge provenance; incremental reindex by changed files and reverse dependencies; scheduled full suites mitigate graph misses. Hybrid graph traversal + lexical + vector retrieval is optional optimization after correctness.

## Failure taxonomy
TARGET_ASSERTION_FAILURE, TARGET_UNAVAILABLE, RUNNER_CRASH, FIXTURE_SETUP_FAILURE, TELEMETRY_MISSING, ORACLE_UNAVAILABLE, POLICY_DENIED, TIMEOUT, CANCELLED. Distinguish timeout of target (possibly FAIL if contract says so) from runner timeout (INFRA_ERROR). Each verdict references evidence and evaluator version.

## Framework interoperability
HACP: bilateral engineering collaboration and revision acceptance; A2A: optional adapter for external task/discovery interoperability; OTLP: telemetry only. Adapters must validate authorization, schema and artifact hashes. Actual HACP wire format requires verification against installed repo before integration.

## Security/release prerequisites
Per-tenant isolation; no production writes by default; secret manager, least privilege, sandbox egress restrictions, quotas, audit logs, retention/deletion, supply-chain scanning, benchmark separation, human review for irreversible actions. Load-test queue and Collector; define SLOs from measured pilot data, not invented guarantees.
