# FLOW account control plane

The account layer is intentionally narrow. Neon Auth/Better Auth owns email/password authentication, browser sessions, secure HTTP-only cookies, and the authenticated user identity. FLOW stores only account metadata needed to authorize devices and manage the local CLI:

- `flow_profiles` — display preferences and timezone.
- `flow_devices` — a stable FLOW device id and revocation state.
- `flow_cli_auth_requests` — short-lived browser approval requests and PKCE challenges.
- `flow_device_credentials` — hashed, rotating refresh credentials; raw tokens are never stored.
- `flow_device_presence` — heartbeat and health metadata.

Screenshots, observations, transcripts, session timelines, task contents, source code, logs, and model prompts remain in the local FLOW store. The SQL migration is [001_account_control_plane.sql](../../services/flow/account/migrations/001_account_control_plane.sql).

## Configuration

Set `DATABASE_URL` in the deployment environment to the Neon pooled connection string. Never commit it or put it in a Vite `VITE_*` variable. Set a separate `FLOW_ACCOUNT_SIGNING_KEY` with at least 32 random characters for access-token signing. The current repository provides the account state machine and SQL contract; the live Neon migration and Vercel environment wiring still require deployment credentials and should be run by the deployment owner.

The CLI uses `FLOW_ACCOUNT_URL` (falling back to the configured FLOW web URL) and stores its refresh credential in the existing OS keychain when available, with the existing 0600 file fallback on headless systems.

## CLI flow

`flow login` creates a PKCE verifier locally, posts only the challenge and device metadata, and opens the browser approval page. After approval, the deployed control plane exchanges the one-time code plus verifier and rotates refresh credentials on every refresh. `flow logout`, `flow whoami`, `flow account`, and `flow devices` operate on the control plane; they do not upload local session data.
