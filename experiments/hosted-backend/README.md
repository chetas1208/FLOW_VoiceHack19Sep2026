# Archived: hosted FLOW backend experiment

An earlier campaign built a hosted FastAPI + PostgreSQL + Redis backend (`flowcloud/`) with OIDC login,
device authorization, sync and a command ledger. **The product architecture no longer includes any
FLOW-operated backend**: the daemon on the user's Mac is the API, database and agent; the Vercel app is a
static frontend that talks to that daemon directly. This code is kept only as reference (its request
guard, rate limiter, read-model builders and 47 tests informed `services/flow/server/`). It is not
installed, packaged, deployed or supported. Not on `sys.path`; tests here are not collected by CI.
