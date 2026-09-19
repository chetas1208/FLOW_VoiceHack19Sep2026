#!/bin/sh
set -eu
python -m compileall -q services
python scripts/validate_contracts.py
python -m pytest tests/flow -q
python -m build --wheel --no-isolation 2>/dev/null || python -m pip wheel . --no-deps --no-build-isolation -w /tmp/flow-dist
