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

## Verified status (2026-09-19, peer b, HACP contract B-004)

Deployed on macOS with Colima (Docker 29.7.2) and standalone `docker-compose` 5.5.0
(this host has no `docker compose` plugin, so either spelling may be needed). The
Collector (`otel/opentelemetry-collector-contrib:0.115.1`) and receiver both start.

**Defect found and fixed:** the Collector's `otlphttp` exporter gzips by default, and
the receiver rejected every export with HTTP 400. The Collector logged `Exporting failed.
Dropping data.`, so this pipeline had never delivered a span. The receiver now accepts
`Content-Encoding: gzip`. Decompression is streamed and capped at 2 MiB of output (a
decompression bomb gets 413), and other encodings get 415 (`tests/test_otlp_gzip.py`).

Live check (brings the stack up, sends a span to `127.0.0.1:4318`, and requires it to
appear in `.local-runs/telemetry.sqlite3`):

```bash
export QA_DOCKER_UID="$(id -u)" QA_DOCKER_GID="$(id -g)"
docker-compose -p agentgraph-otel -f infra/otel/compose.yaml up -d --build
QA_OTEL_COMPOSE_LIVE=1 python -m pytest -q tests/test_otel_compose_live.py
docker-compose -p agentgraph-otel -f infra/otel/compose.yaml down
```

Still not verified: production trace storage and retention, a hosted pipeline, mTLS, and
Linux CI with Docker. The receiver indexes traces only (no logs or metrics).
