# Portable demonstration

```bash
pip install -e .
flow doctor
FLOW_DATA_DIR=/tmp/flow-demo flow e2e --goal "Fix authentication tests"
```

The replay command runs the same privacy/pipeline/session/metrics/segment/drift
path with sanitized frames and a deterministic analyzer. It is not a claim of
real macOS capture. On macOS, `flow observer test` is the capture smoke test;
the command fails clearly until the native bridge and permission are available.
