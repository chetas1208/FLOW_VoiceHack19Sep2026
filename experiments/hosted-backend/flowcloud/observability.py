"""Structured JSON logging, request context, metrics, and optional OpenTelemetry spans."""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import sys
import threading
import time
from collections import defaultdict
from typing import Any, Iterator

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
context_var: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("flow_log_context", default={})

SENSITIVE = {"authorization", "token", "access_token", "refresh_token", "code_verifier", "password", "secret", "cookie"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
                                   "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        if request_id := request_id_var.get():
            payload["request_id"] = request_id
        payload.update(context_var.get())
        extra = getattr(record, "fields", None)
        if extra:
            payload.update({k: ("[redacted]" if k.lower() in SENSITIVE else v) for k, v in extra.items()})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(getattr(h, "_flow", False) for h in root.handlers):
        root.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._flow = True  # type: ignore[attr-defined]
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("alembic", "httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, message: str, **fields: Any) -> None:
    logger.info(message, extra={"fields": fields})


def bind(**fields: Any) -> None:
    context_var.set({**context_var.get(), **fields})


class Metrics:
    """Tiny Prometheus-text metrics; enough for HPA/KEDA dashboards without extra dependencies."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self.latency: dict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, amount: float = 1.0, **labels: str) -> None:
        with self._lock:
            self.counters[(name, tuple(sorted(labels.items())))] += amount

    def observe(self, route: str, seconds: float) -> None:
        with self._lock:
            samples = self.latency[route]
            samples.append(seconds)
            if len(samples) > 2000:
                del samples[:1000]

    def render(self, gauges: dict[str, float] | None = None) -> str:
        lines = []
        with self._lock:
            for (name, labels), value in sorted(self.counters.items()):
                label = ",".join(f'{k}="{v}"' for k, v in labels)
                lines.append(f"{name}{{{label}}} {value}" if label else f"{name} {value}")
            for route, samples in sorted(self.latency.items()):
                if samples:
                    ordered = sorted(samples)
                    for q in (0.5, 0.95):
                        lines.append(f'flow_request_seconds{{route="{route}",quantile="{q}"}} {ordered[int(q * (len(ordered) - 1))]:.5f}')
        for name, value in (gauges or {}).items():
            lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"


@contextlib.contextmanager
def span(name: str, **attributes: str | int | float | bool) -> Iterator[None]:
    """OpenTelemetry span when the SDK is installed; attributes must never carry screen content."""
    try:
        from opentelemetry import trace
    except ImportError:
        yield
        return
    with trace.get_tracer("flow.cloud").start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)
        yield
