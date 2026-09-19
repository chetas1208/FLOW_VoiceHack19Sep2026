# System architecture (ADR baseline)

## Product boundary
Support full-stack, agentic and hybrid QA through shared discovery, scenario, execution, evidence and verification contracts. Initial supported target: local Python agent fixture + local HTTP web fixture; general integrations are future work.

## Logical planes
1. Control: tenant/project onboarding, authorization, run scheduler, policy, task coordination.
2. Execution: isolated browser/API/agent workers, fixtures, fault injection, cleanup.
3. Telemetry: OpenTelemetry instrumentation → **OTLP** → authenticated Collector → trace/log/metric backends. No custom telemetry wire protocol.
4. Knowledge: static code facts, approved requirements, runtime observations, graph and history.
5. Verification: deterministic oracles, semantic judges (calibrated), human review; independent from test executor.

## Canonical run lifecycle
QUEUED → PROVISIONING → RUNNING → COLLECTING → VERIFYING → COMPLETED; failures can enter INFRA_ERROR, CANCELLED or INCONCLUSIVE verdict. Run lifecycle and verdict are different fields. Lease expiry must allow idempotent rescheduling; external side effects must be isolated or idempotency-keyed.

## Cold start
Repo parser + documented requirements → provisional graph; launch isolated target → browser/API/agent exploration → OTLP observed relationships → reconcile provenance → approve critical business invariants. Black-box onboarding is limited to observable behavior; do not invent requirements.

## Verification invariants
- No PASS without required assertions and evidence; FAIL only with demonstrated violation; missing evidence → INCONCLUSIVE; runner failure → INFRA_ERROR.
- QA executor cannot alter authoritative verdict or ground-truth labels.
- Test-run ID is stable; attempt ID unique on retry. Evidence immutable by content hash; separate application and QA telemetry.
- Trace absence alone is not evidence of action absence.
- No live destructive actions or real customer data by default.

## Threat model
Untrusted source repositories, tool output, browser content, A2A peers and generated scenarios; risks: prompt injection, sandbox escape, secret leakage, cross-tenant evidence access, malicious artifact, test-induced real-world side effects, judge bias. Enforce sandboxing, egress deny-by-default, scoped credentials, redaction, RBAC, artifact hashing, reviewer approvals, and separate benchmark labels.

## Graph provenance
Every edge records origin (static, runtime, approved, inferred), source reference, version, observation time and verification status. Static CAN_CALL differs from observed CALLED. Traces provide evidence but do not alone prove causal database effects.
