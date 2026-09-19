# HACP integration: verified status

Verified on 2026-09-19 (macOS arm64, cargo 1.98.0) by peer b under HACP contract B-001.

## Three pieces, and what each one proves

| Piece | What it is | Verified | Command |
| --- | --- | --- | --- |
| `vendor/hacp-1.1.1/` | The user-supplied HACP crate. Its `hacp::v2` module implements the HACP/2.0 draft (package 1.1.1 ≠ wire version 2.0). | 36 upstream tests pass (31 unit tests + 5 in a second test target) | `cargo test --manifest-path integrations/hacp/vendor/hacp-1.1.1/Cargo.toml --target-dir .local-runs/cargo-verify` |
| `src/main.rs` (`proofhound-hacp-bridge`) | The upstream bilateral example. **One process plays both parties**: open session, both accept, freeze, manifest, submit, check bytes, settle, close. | Compiles, and prints `Settled: exact content, size and digest verified; session closed.` | `cargo run --manifest-path integrations/hacp/Cargo.toml --target-dir .local-runs/cargo-verify` |
| `hacp` CLI (hacp-skill 0.1.0, installed in `~/.cargo/bin`, not vendored here) | The two-process runtime. Each coding agent calls it with `--peer a` or `--peer b`. State is durable in `<project>/.hacp/` (a lock file, `session.json`, per-peer inboxes and `log.md`). It uses the `hacp::v2` contract state machine: propose/accept (only identical terms freeze), frozen revision digests, owner-only submit, counterparty-only verify that runs the frozen acceptance commands and hashes the outputs, accept/rework/reject, and dedup through `processed` message IDs. | Used live between two separate agent processes (Codex as peer a, Claude Code as peer b) in session `s-078c6282209c462b82c5ee6c6e8298a8` | `hacp --peer b status --json` |

`services/platform/hacp_mailbox.py` remains a Python **transport** demo: HMAC, membership,
replay rejection and a digest check. It does not implement the contract state machine. Its
`rust_contract_lifecycle_verified: false` output describes the mailbox itself, not the crate.

## Auditing a collaboration

```sh
python -m services.platform.hacp_evidence --project . --output .local-runs/hacp-evidence.json --require-both-peers
```

The exporter only reads `.hacp/session.json`. It validates every envelope against
`vendor/hacp-1.1.1/spec/schemas/envelope.json`, and it fails when any participant URN sent no
messages, because a self-sent conversation is not collaboration. It lists every contract's
frozen revisions, submissions, artifact hashes (re-hashed on disk to detect drift), verifier
verdicts and measured acceptance commands. A matching hash shows integrity, not correctness.

## Limits (not verified or not provided)

- The `hacp` CLI does not launch, prompt or wake coding agents. Each agent polls or waits.
  The user or launcher starts both CLIs and assigns roles. A misassigned role stalled this
  session for about 20 minutes until the user corrected it.
- The installed CLI accepts only `inputs`/`outputs`/`acceptance` in terms. A newer
  hacp-skill source adds a `requirements` field, but that source is not what is installed.
  Objectives and security constraints therefore travel as HACP messages.
- The CLI's file ownership replaces git-worktree isolation. Both peers share one tree, and
  acceptance commands run from that root.
- There is no network transport: both peers must share a filesystem. There is no
  cross-machine or signed-identity transport. Peer identity is a CLI flag, trusted locally.
- The GitHub Actions `hacp-rust-bridge` job has not run on GitHub.
