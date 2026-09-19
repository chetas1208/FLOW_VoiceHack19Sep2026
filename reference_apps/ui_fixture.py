"""Disposable two-server UI checkout with independently queryable backend state."""
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

@contextmanager
def ui_fixture(log_path, *, broken):
    state = {'charges': 0, 'orders': 0}

    class UI(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/':
                self.send_error(404)
                return
            html = '''<!doctype html><html><head><title>QA shop</title></head><body>
              <h1>Orders</h1><label for="order">Order ID</label>
              <input id="order" value="test-order"/>
              <button data-testid="buy">Create order</button>
              <output id="result" aria-live="polite"></output>
              <script>
              document.querySelector('[data-testid="buy"]').onclick=async()=>{
                const response=await fetch('/create',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({id:document.querySelector('#order').value})});
                const data=await response.json();
                document.querySelector('#result').textContent=data.status;
              };
              </script></body></html>'''.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self):
            if self.path != '/create':
                self.send_error(404)
                return
            size = int(self.headers['content-length'])
            json.loads(self.rfile.read(size))
            state['orders'] += 1
            if broken or state['charges'] == 0:
                state['charges'] += 1
            traceparent = self.headers.get('traceparent', '')
            with open(log_path, 'a') as output:
                if traceparent:
                    output.write('INFO trace_id=' + traceparent.split('-')[1][:32] + '\n')
                if state['charges'] > 1:
                    output.write('ERROR duplicate charge token=server-secret email=test@example.com\n')
                else:
                    output.write('INFO order created token=server-secret\n')
                output.flush()
            body = b'{"status":"Created"}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args): pass

    class Oracle(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/state':
                self.send_error(404)
                return
            body = json.dumps(state).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass

    servers = [ThreadingHTTPServer(('127.0.0.1', 0), handler) for handler in (UI, Oracle)]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for t in threads: t.start()
    try:
        yield tuple('http://127.0.0.1:' + str(server.server_port) for server in servers)
    finally:
        for server in servers: server.shutdown(); server.server_close()
        for t in threads: t.join(timeout=3)

