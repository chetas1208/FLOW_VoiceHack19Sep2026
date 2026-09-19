"""Disposable multi-page lending-library app used as an *unfamiliar* onboarding target.

The QA engine has no code specific to this app. It must discover the pages, forms
and workflows itself. The app requires a bearer token on every request (a staging
API gateway pattern). It exposes an independent read-only state service and writes
a structured server log.

``release='v3'`` adds a reading-history section to /loans, a small UI change for
regression selection to detect. With ``otlp_endpoint`` the backend emits real
OTLP spans that continue the caller's W3C ``traceparent`` (its own tracer
provider; the global one is untouched).

Defect (``broken=True``): reserving the last available copy shows "Reserved" in
the UI and returns HTTP 200, but the reservation is never committed. The UI
claim and the real state disagree, and only an independent oracle can tell.
"""
import json
import threading
from contextlib import contextmanager
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NAV = ('<nav aria-label="Main"><a href="/">Home</a> <a href="/catalog">Catalog</a> '
       '<a href="/loans">My loans</a> <a href="/help">Help</a> '
       '<a href="/account/delete">Delete account</a></nav>')


def _page(title, body):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>'
            f'</head><body><header>{NAV}</header><main><h1>{escape(title)}</h1>{body}</main></body></html>')


@contextmanager
def lending_library(log_path, *, broken, token, release='v2', otlp_endpoint=None):
    lock = threading.Lock()
    state = {'books': {'b1': {'title': 'Dune', 'available': 2},
                       'b2': {'title': 'Emma', 'available': 1}},
             'reservations': []}

    provider = tracer = None
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        provider = TracerProvider(resource=Resource.create({'service.name': 'lending-library'}))
        provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
        tracer = provider.get_tracer('lending-library')

    def span(name, traceparent=''):
        from contextlib import nullcontext
        if tracer is None:
            return nullcontext()
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        parent = TraceContextTextMapPropagator().extract({'traceparent': traceparent}) if traceparent else None
        return tracer.start_as_current_span(name, context=parent)

    def log(level, message, traceparent=''):
        trace = (' trace_id=' + traceparent.split('-')[1]) if traceparent.count('-') >= 3 else ''
        with open(log_path, 'a') as output:
            output.write(f'{level} {message}{trace}\n')

    class App(BaseHTTPRequestHandler):
        def _authorized(self):
            if self.headers.get('Authorization') != 'Bearer ' + token:
                self.send_response(401)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', '12')
                self.end_headers()
                self.wfile.write(b'unauthorized')
                return False
            return True

        def _send(self, status, body, kind='text/html; charset=utf-8'):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._authorized():
                return
            if self.path == '/':
                return self._send(200, _page('Lending library', '<p>Borrow books from the community shelf.</p>'))
            if self.path == '/catalog':
                with lock:
                    rows = ''.join(
                        f'<li><span>{escape(b["title"])}</span> '
                        f'(<span data-testid="available-{k}">{b["available"]}</span> available)</li>'
                        for k, b in state['books'].items())
                    options = ''.join(f'<option value="{k}">{escape(b["title"])}</option>'
                                      for k, b in state['books'].items())
                form = ('<form id="reserve-form"><label for="member">Member ID</label>'
                        '<input id="member" name="member" required>'
                        f'<label for="book">Book</label><select id="book" name="book">{options}</select>'
                        '<button type="submit">Reserve</button></form>'
                        '<p id="status" role="status" aria-live="polite"></p>'
                        '<script>document.getElementById("reserve-form").addEventListener("submit", async e => {'
                        ' e.preventDefault();'
                        ' const r = await fetch("/api/reservations", {method: "POST",'
                        '  headers: {"Content-Type": "application/json"},'
                        '  body: JSON.stringify({member: member.value, book: book.value})});'
                        ' const data = await r.json();'
                        ' document.getElementById("status").textContent = data.message; });</script>')
                return self._send(200, _page('Catalog', f'<ul>{rows}</ul>{form}'))
            if self.path == '/loans':
                with lock:
                    count = len(state['reservations'])
                history = '<h2>Reading history</h2><p>No past loans.</p>' if release == 'v3' else ''
                return self._send(200, _page('My loans', f'<p>You have <b id="loan-count">{count}</b> reservations.</p>{history}'))
            if self.path == '/help':
                return self._send(200, _page('Help', '<p>Contact the librarian.</p><img src="/logo.png">'))
            if self.path == '/logo.png':
                return self._send(404, 'missing', 'text/plain')
            if self.path == '/account/delete':
                # Destructive GET: a crawler that follows every link would trigger this.
                log('ERROR', 'account deletion requested via GET', self.headers.get('traceparent', ''))
                return self._send(200, _page('Account deleted', '<p>Deleted.</p>'))
            return self._send(404, _page('Not found', ''))

        def do_POST(self):
            if not self._authorized():
                return
            if self.path != '/api/reservations':
                return self._send(404, '{}', 'application/json')
            size = min(int(self.headers.get('Content-Length', '0')), 4096)
            try:
                payload = json.loads(self.rfile.read(size))
                member, book = str(payload['member'])[:64], str(payload['book'])
            except (ValueError, KeyError, TypeError):
                return self._send(400, '{"message":"Invalid request"}', 'application/json')
            traceparent = self.headers.get('traceparent', '')
            with span('POST /api/reservations', traceparent), lock:
                item = state['books'].get(book)
                if item is None or not member:
                    log('WARN', 'reservation rejected', traceparent)
                    return self._send(400, '{"message":"Invalid request"}', 'application/json')
                if item['available'] < 1:
                    log('INFO', 'reservation refused: none available', traceparent)
                    return self._send(409, '{"message":"Not available"}', 'application/json')
                last_copy = item['available'] == 1
                if not (broken and last_copy):
                    with span('db.commit reservations'):
                        item['available'] -= 1
                        state['reservations'].append({'book': book, 'member_hash': hash(member) & 0xffff})
                    log('INFO', 'reservation committed', traceparent)
                else:
                    log('INFO', 'reservation accepted', traceparent)  # not committed: the defect
            return self._send(200, '{"message":"Reserved"}', 'application/json')

        def log_message(self, *args):
            pass

    class Oracle(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/state':
                self.send_error(404)
                return
            with lock:
                body = json.dumps({'reservations': len(state['reservations']),
                                   'available': {k: b['available'] for k, b in state['books'].items()}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    servers = [ThreadingHTTPServer(('127.0.0.1', 0), handler) for handler in (App, Oracle)]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        yield tuple('http://127.0.0.1:' + str(server.server_port) for server in servers)
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)
        if provider is not None:
            provider.shutdown()
