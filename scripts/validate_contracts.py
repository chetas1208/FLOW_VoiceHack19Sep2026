#!/usr/bin/env python3
"""Strict schema meta-validation; dependency required, never silently skip."""
import json
import sys
from pathlib import Path
try:
    from jsonschema import Draft202012Validator
except ImportError:
    print('Missing jsonschema: pip install -r requirements-dev.txt', file=sys.stderr)
    sys.exit(2)
root = Path(__file__).resolve().parents[1]
files = sorted((root/'contracts'/'schemas').glob('*.schema.json'))
assert len(files) >= 10, 'Missing core contracts'
for path in files:
    Draft202012Validator.check_schema(json.loads(path.read_text()))
    print('VALID', path.name)
print(f'Validated {len(files)} schemas')
