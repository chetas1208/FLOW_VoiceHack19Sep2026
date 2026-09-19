"""``flow validate macos``: machine-readable real-Mac validation artifact.

Statuses are only verified / failed / not_configured / skipped. Non-macOS hosts report
not_configured for macOS-only checks; nothing is ever simulated into "verified".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

NAME = "validate"
DEFAULT_OUTPUT = "artifacts/macos-validation.json"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("validate", help="validate FLOW on a real machine and write a JSON artifact")
    parser.add_argument("target", choices=["macos"])
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"artifact path (default {DEFAULT_OUTPUT})")
    parser.add_argument("--scenario", action="append", metavar="LIST",
                        help="comma list of env,permissions,models,observer,vision,voice,resources,drift,"
                             "blocker,privacy,injection,cloud,all (default all)")
    parser.add_argument("--non-interactive", action="store_true",
                        help="skip guided scenarios that need an operator (they report 'skipped')")
    parser.add_argument("--scenario-timeout", type=float, default=240.0, help="seconds per guided phase")
    parser.add_argument("--exclude-app", help="excluded app used by the privacy scenario")
    parser.add_argument("--session", help="FLOW session id to poll (default: the active session)")
    parser.add_argument("--data-dir", help="FLOW data dir holding flow.sqlite3 (default FLOW_DATA_DIR)")
    parser.add_argument("--strict", action="store_true", help="exit non-zero unless overall is verified")
    parser.add_argument("--json", action="store_true", help="print the artifact JSON on stdout")


def run(args) -> int:
    from ..validation import parse_scenarios, run_macos_validation, summary_lines, write_artifact
    from ..validation.context import ValidationContext
    try:
        selected = parse_scenarios(args.scenario)
    except ValueError as exc:
        print(f"flow validate: {exc}", file=sys.stderr)
        return 2
    ctx = ValidationContext(interactive=not args.non_interactive and sys.stdin.isatty(),
                            scenario_timeout=args.scenario_timeout, exclude_app=args.exclude_app,
                            session_id=args.session)
    if args.data_dir:
        ctx.data_dir = Path(args.data_dir).expanduser().resolve()
    if not args.non_interactive and not ctx.interactive:
        ctx.say("stdin is not a terminal: guided scenarios will be skipped")
    artifact = run_macos_validation(ctx, selected)
    target = write_artifact(artifact, args.output)
    if args.json:
        print(json.dumps(artifact, indent=2))
    else:
        print("\n".join(summary_lines(artifact)))
    print(f"artifact: {target}", file=sys.stderr if args.json else sys.stdout)
    if artifact["overall"] == "failed":
        return 1
    if args.strict and artifact["overall"] != "verified":
        return 1
    return 0
