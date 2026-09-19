# HACP core integration — precise status

The user-provided `hacp-1.1.1.crate` is unpacked to `vendor/hacp-1.1.1/`
with its original LICENSE. `Cargo.toml` references this **local crate path**, not
an unverified Git revision. `src/main.rs` starts from its upstream bilateral
example: it opens a session, obtains both parties' acceptance, freezes a
contract, creates an artifact manifest, submits it, independently checks bytes,
settles the contract, and closes the session.

## Build and run when Rust is available

```sh
cargo run --manifest-path integrations/hacp/Cargo.toml
```

**Rust/Cargo is absent in the current build environment**. This Rust adapter
has NOT been compiled here. Dependency crates beyond the vendored HACP source
still need a local Cargo cache or registry access.

For a working local Python *transport* proof, run:

```sh
python -m services.platform.hacp_mailbox
```

The mailbox uses the supplied HACP/2.0 envelope schema and canonical rules,
validates bilateral membership, checks an HMAC from per-peer secret keys,
rejects duplicate message IDs and invalid signatures, and performs a
three-message artifact verification exchange. **The Python transport is not
an implementation of the HACP Rust contract state machine.** It does not
launch Claude/Codex or communicate with independently hosted agents. Never
claim wire-schema validation proves full protocol conformance.
