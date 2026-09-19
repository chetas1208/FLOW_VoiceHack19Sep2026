# Manifest-based black-box QA

An example against an **owner-operated test** service and a separate,
read-only state oracle (use the ports returned by your services):

```json
{
  "id": "project-create-001",
  "project_id": "my-staging-project",
  "kind": "agentic",
  "version": "commit-sha",
  "base_url": "http://127.0.0.1:8000",
  "oracle_base_url": "http://127.0.0.1:8001",
  "steps": [
    {"name":"create", "method":"POST", "path":"/run", "json":{"name":"test-project"}},
    {"name":"inspect", "target":"oracle", "method":"GET", "path":"/state"}
  ],
  "assertions": [
    {"id":"accepted", "step":"create", "operator":"status_equals", "expected":200},
    {"id":"actually-created", "step":"inspect", "pointer":"/projects/test-project", "operator":"exists", "expected":true}
  ]
}
```

An asserted state retrieved from an oracle independent of the final agent
message is **more informative**, but not magically trustworthy: application
owners must verify their oracle's independence and source-of-truth access.

Supported operators: `equals`, `not_equals`, `contains`, `length_equals`,
`exists`, `status_equals`, `less_or_equal`. JSON Pointer uses RFC 6901 paths.
Missing JSON properties fail; non-JSON bodies lead to `INCONCLUSIVE` unless
only HTTP status is asserted. HTTP connection failures yield `INFRA_ERROR`.

Secrets must not appear in manifest JSON. For application bearer-token auth,
set `QA_TARGET_TOKEN_<NAME>` in the **runner process** and set `auth_env` to its
environment-variable name. Use `oracle_auth_env` independently for read-only
oracle auth. The runner keeps tokens outside results and span attributes.

Security limits: loopback-only by default; explicit HTTPS host allowlist via
`QA_ALLOWED_HTTPS_HOSTS` for owned staging targets only. Enforce DNS/IP egress
policies outside the runner before allowing external hosts. GET-only oracle;
DELETE disabled unless `QA_ALLOW_DESTRUCTIVE=1`; no redirects; at most 25 steps;
HTTP responses capped at 1 MiB; request timeouts capped at 20 seconds;
manifest headers restricted to harmless test fields; no arbitrary commands.

Raw responses are evaluated **in memory**, not stored. Evidence contains only
status, sizes, and assertion decisions, without raw body strings. SHA-256
proves artifact integrity, not whether a test oracle is truthful. Scenario
manifest approval and safe fixture reset remain application-owner duties.
