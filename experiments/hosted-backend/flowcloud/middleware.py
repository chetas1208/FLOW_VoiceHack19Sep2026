"""ASGI middleware: request ids, size limits, content-type policy, access logs, metrics."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .observability import Metrics, request_id_var, context_var
from .settings import Settings

log = logging.getLogger("flow.access")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")


async def _json_response(send: Send, status: int, body: dict, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    payload = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()), *(headers or [])]})
    await send({"type": "http.response.body", "body": payload})


class RequestGuardMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, metrics: Metrics) -> None:
        self.app, self.settings, self.metrics = app, settings, metrics

    def _limit(self, path: str) -> int:
        if path.endswith(":batch") or path.endswith("/summary") or path.endswith("/stop"):
            return self.settings.max_batch_body_bytes
        return self.settings.max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope["headers"]}
        supplied = headers.get("x-request-id", "")
        request_id = supplied if _REQUEST_ID.match(supplied) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        context_var.set({})
        method, path = scope["method"], scope["path"]
        rid_header = [(b"x-request-id", request_id.encode())]
        started = time.perf_counter()
        status_holder = {"status": 500}

        if method in {"POST", "PUT", "PATCH"}:
            length = headers.get("content-length")
            content_type = headers.get("content-type", "").split(";")[0].strip().lower()
            if (length and length != "0") and content_type != "application/json":
                await _json_response(send, 415, {"error": "unsupported_media_type", "message": "application/json required",
                                                 "request_id": request_id}, rid_header)
                request_id_var.reset(token)
                return
            limit = self._limit(path)
            if length and length.isdigit() and int(length) > limit:
                await _json_response(send, 413, {"error": "payload_too_large", "message": f"body exceeds {limit} bytes",
                                                 "request_id": request_id}, rid_header)
                request_id_var.reset(token)
                return
            received = 0
            too_large = False

            async def limited_receive() -> Message:
                nonlocal received, too_large
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > limit:
                        too_large = True
                        return {"type": "http.request", "body": b"", "more_body": False}
                return message
            inner_receive = limited_receive
        else:
            inner_receive = receive
            too_large = False

        async def wrapped_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            if method in {"POST", "PUT", "PATCH"}:
                # buffer only when no content-length was declared (chunked): enforce the cap up front
                if not headers.get("content-length") and headers.get("transfer-encoding"):
                    chunks, total, limit = [], 0, self._limit(path)
                    while True:
                        message = await receive()
                        chunks.append(message)
                        total += len(message.get("body", b""))
                        if total > limit:
                            await _json_response(send, 413, {"error": "payload_too_large", "request_id": request_id}, rid_header)
                            return
                        if not message.get("more_body", False):
                            break
                    replay = iter(chunks)

                    async def replay_receive() -> Message:
                        return next(replay, {"type": "http.disconnect"})
                    inner_receive = replay_receive
            await self.app(scope, inner_receive, wrapped_send)
        finally:
            elapsed = time.perf_counter() - started
            route = scope.get("route")
            template = getattr(route, "path", None) or "unmatched"
            self.metrics.inc("flow_http_requests_total", method=method, route=template, status=str(status_holder["status"]))
            self.metrics.observe(template, elapsed)
            if not template.startswith("/health"):
                log.info("request", extra={"fields": {"method": method, "route": template, "status": status_holder["status"],
                                                      "latency_ms": round(elapsed * 1000, 2)}})
            request_id_var.reset(token)
