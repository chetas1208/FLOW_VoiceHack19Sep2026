# Authentication

The CLI has a credential-store abstraction. macOS uses the `security` Keychain
tool; non-macOS development uses a mode-600 file only so tests and local demos
remain runnable. Tokens are never printed by FLOW.

The `/v1/cli/auth/*` endpoints implement a local device authorization protocol
with state, nonce, and S256 PKCE. The browser receives a challenge, not a
permanent bearer token. Remote production authorization and refresh-token
rotation remain to be connected to the web identity provider.
