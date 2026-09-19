# OTLP pipeline — local development configuration

The platform uses **OTLP**, not a proprietary trace wire format.

```
Application / QA runner → OTLP/HTTP or OTLP/gRPC
  → OpenTelemetry Collector → OTLP/HTTP
  → bounded Python OTLP development receiver → sanitized SQLite span index
```

Run from the repository root with Docker installed:

```bash
mkdir -p .local-runs
export QA_DOCKER_UID="$(id -u)" QA_DOCKER_GID="$(id -g)"
# The receiver uses your host UID/GID to write only to its local data volume.
docker compose -f infra/otel/compose.yaml up --build -d
export QA_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces
python scripts/demo.py
```

The container runs as an unprivileged UID and persists only allowlisted span
attributes to `.local-runs/telemetry.sqlite3`. `GET /telemetry/traces/{trace_id}`
on the local control plane retrieves indexed spans. The receiver isn't published
to the host; Collector ports are host-loopback-only.

**Deployment not verified in this environment:** Docker is not installed. The
actual exporter-to-receiver-to-SQLite path *was* separately exercised over
real HTTP by `tests/test_persistent_otlp_e2e.py` with the same receiver module.
The bundled Collector version and Compose flow still require Docker-based CI
or an operator acceptance run.

Production requires secure TLS/mTLS ingress, scoped service credentials,
network policy, a supported trace storage backend, limits/retention, backups,
audit logs and per-tenant isolation. The current receiver supports traces
only, not OTLP logs or metrics. Do not publish it directly.
