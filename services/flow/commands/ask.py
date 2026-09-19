"""Evidence-grounded local session questions."""

from __future__ import annotations

from ..models import SessionStatus
from ..remote.assistant import AssistantContext, answer
from ..session_manager import SessionManager

NAME = "ask"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="ask a question answered from local session evidence")
    parser.add_argument("question")
    parser.add_argument("--session")


def run(args) -> int:
    service = SessionManager.from_environment()
    try:
        session = service.get_session(args.session) if args.session else _only_active(service)
    except ValueError as exc:
        print(f"flow ask: {exc}")
        return 2
    report = service.report(session.id)
    observations = [item.to_dict() for item in service.observations(session.id)]
    result = answer(args.question, AssistantContext(session_id=session.id, goal=session.goal,
        status=session.status.value, metrics=report["metrics"], segments=report["task_segments"],
        observations=observations))
    print(result.text)
    if result.evidence:
        print("\nEvidence")
        for item in result.evidence:
            print(f"- {item}")
    return 0 if result.grounded else 2


def _only_active(service: SessionManager):
    active = service.list_sessions(SessionStatus.ACTIVE)
    if len(active) != 1:
        raise ValueError("specify --session unless exactly one active session exists")
    return active[0]
