# Multi-agent Week 1 task registry

A0 orchestrator owns architecture/contracts/integration; A1 graph; A2 fullstack; A3 agentic; A4 runtime/OTLP; A5 evaluation/reporting. Six logical roles (A0 + five workers). One worktree/branch per worker. Shared contract edits proposed via A0 and accepted by affected consumers.

## Dependency DAG
W1-001 contracts (A0) → W1-002 graph (A1), W1-003 fullstack fixture (A2), W1-004 agentic fixture (A3), W1-005 OTLP design (A4), W1-006 oracle benchmark (A5). W1-002/003/004/005/006 → W1-007 integration acceptance (A0).

## Sessions proposed
H1 A0↔A1 graph contract; H2 A0↔A2 fullstack; H3 A0↔A3 agentic; H4 A0↔A4 telemetry; H5 A0↔A5 verification. Cross-team H6 A4↔A3 trace integration; H7 A1↔A5 evidence mapping. Each is a separate bilateral session. No sessions have actually been created.

## Daily synchronization
Agents submit status (planned/accepted/implementing/submitted/verified/blocked), commit SHA, tests and blockers to task registry. A0 resolves dependency changes, merges only after verification. Never claim acceptance without actual peer response.

## Worktree strategy
Branches: feat/graph, feat/fullstack, feat/agentic, feat/telemetry, feat/evaluation; shared integration branch owned by A0. Changes outside ownership require negotiated handoff. No agent writes another's worktree.
