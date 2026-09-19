"""Ephemeral known-good and known-bad applications with separate read-only oracles."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from reference_apps.fullstack.app import Handler as BrokenOrderHandler, ORDERS
from reference_apps.agentic.agent import FakeProjectTool, ProjectAgent


def send_json(handler, payload, code=200):
    body = json.dumps(payload).encode()
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


@contextmanager
def serve_pair(handler, oracle):
    a = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    b = ThreadingHTTPServer(('127.0.0.1', 0), oracle)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (a, b)]
    for thread in threads:
        thread.start()
    try:
        yield f'http://127.0.0.1:{a.server_port}', f'http://127.0.0.1:{b.server_port}'
    finally:
        for server in (a, b):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def fullstack_fixture(fixed=False):
    ORDERS.clear()

    class FixedOrderHandler(BrokenOrderHandler):
        def do_POST(self):
            if self.path != '/orders':
                self.send_error(404)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if size < 0 or size > 4096:
                    raise ValueError('invalid length')
                payload = json.loads(self.rfile.read(size))
                order_id, amount = payload['order_id'], payload['amount']
                if not isinstance(order_id, str) or not isinstance(amount, (int, float)):
                    raise ValueError('invalid order')
                entry = ORDERS.setdefault(order_id, {'amount': amount, 'charges': [amount]})
                send_json(self, {'order_id': order_id, 'charge_count': len(entry['charges'])})
            except (ValueError, KeyError, TypeError):
                self.send_error(400)

        def log_message(self, *args):
            pass

    class Oracle(QuietHandler):
        def do_GET(self):
            if self.path != '/state':
                self.send_error(404)
                return
            send_json(self, {'orders': ORDERS})

    class BrokenQuiet(BrokenOrderHandler):
        def log_message(self, *args):
            pass

    try:
        with serve_pair(FixedOrderHandler if fixed else BrokenQuiet, Oracle) as pair:
            yield pair
    finally:
        ORDERS.clear()


@contextmanager
def agentic_fixture(fixed=False):
    tool = FakeProjectTool()

    class App(QuietHandler):
        def do_POST(self):
            if self.path != '/run':
                self.send_error(404)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= 4096:
                    raise ValueError('bad length')
                name = json.loads(self.rfile.read(length))['name']
                if not isinstance(name, str) or not name:
                    raise ValueError('invalid name')
                if fixed:
                    tool.create(name)
                answer = ProjectAgent(tool).run(name)
                send_json(self, {'answer': answer})
            except (ValueError, KeyError, TypeError):
                self.send_error(400)

    class Oracle(QuietHandler):
        def do_GET(self):
            if self.path != '/state':
                self.send_error(404)
                return
            send_json(self, {'projects': tool.projects, 'tool_call_count': len(tool.calls)})

    with serve_pair(App, Oracle) as pair:
        yield pair


def manifest_for(kind, base, oracle, suffix=''):
    if kind == 'fullstack':
        return {
            'id': 'order-idempotency' + suffix, 'project_id': 'benchmark-fullstack',
            'kind': 'fullstack', 'base_url': base, 'oracle_base_url': oracle,
            'steps': [
                {'name': 'create', 'method': 'POST', 'path': '/orders',
                 'json': {'order_id': 'benchmark-order', 'amount': 50}},
                {'name': 'retry', 'method': 'POST', 'path': '/orders',
                 'json': {'order_id': 'benchmark-order', 'amount': 50}},
                {'name': 'state', 'target': 'oracle', 'method': 'GET', 'path': '/state'},
            ],
            'assertions': [
                {'id': 'accepted', 'step': 'create', 'operator': 'status_equals', 'expected': 200},
                {'id': 'exactly-once', 'step': 'state', 'pointer': '/orders/benchmark-order/charges',
                 'operator': 'length_equals', 'expected': 1},
            ]}
    if kind == 'agentic':
        return {
            'id': 'tool-actually-called' + suffix, 'project_id': 'benchmark-agentic',
            'kind': 'agentic', 'base_url': base, 'oracle_base_url': oracle,
            'steps': [
                {'name': 'task', 'method': 'POST', 'path': '/run', 'json': {'name': 'benchmark'}},
                {'name': 'state', 'target': 'oracle', 'method': 'GET', 'path': '/state'},
            ],
            'assertions': [
                {'id': 'response', 'step': 'task', 'operator': 'status_equals', 'expected': 200},
                {'id': 'project-exists', 'step': 'state', 'pointer': '/projects/benchmark',
                 'operator': 'exists', 'expected': True},
                {'id': 'tool-invoked', 'step': 'state', 'pointer': '/tool_call_count',
                 'operator': 'equals', 'expected': 1},
            ]}
    raise ValueError('unknown fixture')
