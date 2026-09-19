# Week 1 acceptance and handoff

## Evidence-backed completion gates
- [x] Architecture, boundaries, security assumptions and ADRs written.
- [x] Core entities have strict versioned JSON Schemas and examples.
- [x] Task ownership, dependencies and proposed bilateral HACP contracts defined.
- [x] Two reference fixtures have executable known-defect oracles and negative controls.
- [x] Local automated checks and CI workflow provided.
- [ ] Agents have accepted live HACP contracts (requires running agents and actual protocol integration).
- [ ] OTLP Collector and real execution plane deployed (Week 2).
- [ ] External developer onboarding proven (later milestone).

## Next acceptance sequence
1. Confirm actual HACP CLI/wire schema and establish real sessions; do not assume our YAML manifests are protocol-native.
2. Validate contracts with `jsonschema`, run reference tests and record CI results.
3. A4 deploys OTLP Collector and instruments QA runner; A5 implements independent oracle execution.
4. A2/A3 integrate fixtures into isolated execution workers; A1 persists graph/evidence references.
5. A0 verifies end-to-end demo and marks gates complete only with logs and artifact hashes.

## Known limitations
Fixtures intentionally contain bugs; passing fixture tests means the tests correctly *detect* these bugs, not that the applications are correct. No deployed infrastructure, live agents, authenticated A2A, CI execution on GitHub, or actual OTLP transport is claimed.
