"""Deterministic structured-observation fixture for local development."""

from __future__ import annotations

import argparse
import time
from datetime import timedelta

from .models import ActivityCategory, Observation, utc_now
from .session_manager import SessionManager, SessionNotFound, _id


FIXTURE = [
    ("VS Code", "Implementing authentication middleware", ActivityCategory.CORE_TASK, .96),
    ("Chrome", "Reading JWT documentation", ActivityCategory.SUPPORTING_TASK, .84),
    ("VS Code", "Debugging expiry tests", ActivityCategory.CORE_TASK, .93),
    ("Twitter/X", "Unrelated feed", ActivityCategory.DISTRACTION, .06),
    ("Twitter/X", "Unrelated feed", ActivityCategory.DISTRACTION, .04),
    ("VS Code", "Returned to token expiry test", ActivityCategory.CORE_TASK, .91),
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inject deterministic FLOW observations")
    parser.add_argument("--session", required=True); parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    service = SessionManager(); start = utc_now()
    try: service.get_session(args.session)
    except SessionNotFound as exc: parser.error(str(exc))
    for index, (app, summary, category, alignment) in enumerate(FIXTURE):
        item = Observation(_id("obs"), args.session, start + timedelta(seconds=index * args.interval), "simulator",
                           app, app + " - FLOW demo", summary, category, alignment, .8 if category == ActivityCategory.CORE_TASK else .2, .95,
                           {"fixture": "prompt-1", "simulated": True})
        service.add_observation(args.session, item)
        print(f"{index + 1}/{len(FIXTURE)} {app}: {summary} [{category.value}] alignment={alignment:.2f}")
        if args.interval > 0: time.sleep(args.interval / max(args.speed, .01))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
