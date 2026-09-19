# Development

```bash
pip install -e .
flow --help
flow doctor
python -m pytest tests/flow -q
scripts/ci-local.sh
```

Linux/macOS-independent tests use `MockDesktopObserver`; ScreenCaptureKit
permission tests are opt-in macOS integration tests and are not required for
normal local CI. Do not add GitHub Actions for this project. Run the existing
ProofHound contract and compatibility tests before delivery.
