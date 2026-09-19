"""Real HTTP test against an ephemeral loopback reference application.

Not a sandbox or an arbitrary website crawler. The independent oracle reads
server-side state rather than trusting the HTTP success response.
"""
import json
import threading
from http.server import HTTPServer
from urllib.request import Request, urlopen
from reference_apps.fullstack.app import Handler, ORDERS


def verify_retry():
    ORDERS.clear()
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}/orders'
        responses = []
        for _ in range(2):
            req = Request(url, data=json.dumps({'order_id':'qa-order','amount':50}).encode(), headers={'Content-Type':'application/json'}, method='POST')
            with urlopen(req, timeout=3) as response:
                responses.append({'status':response.status,'body':json.loads(response.read())})
        actual = len(ORDERS['qa-order']['charges'])
        return {'verdict':'PASS' if actual == 1 else 'FAIL', 'assertions':{'exactly_once':actual == 1}, 'observed':{'http_responses':responses,'server_charge_count':actual}}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        ORDERS.clear()
