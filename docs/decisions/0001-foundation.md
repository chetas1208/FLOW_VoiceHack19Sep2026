# ADR-0001: Week 1 architecture baseline
Status: proposed for team acceptance
Decision: five logical planes; OTLP only for telemetry; HACP bilateral collaboration and optional A2A adapter; schema-first APIs; separate verification authority; Postgres initial graph. Alternatives deferred: bespoke trace protocol (rejected), universal agent adapters in MVP (deferred), graph DB immediately (deferred). Consequences: less early integration surface; explicit adapters and provenance required. Revisit after pilot profiling.
